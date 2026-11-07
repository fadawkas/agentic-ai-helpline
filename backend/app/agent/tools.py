import asyncio
import logging
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.direct_function import tool_options
from pipecat.frames.frames import FunctionCallResultProperties
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.services.llm_service import FunctionCallParams

from app.agent.state import CallState
from app.safety.engine import (
    SafetyConfirmationState,
    SafetyEngine,
    SafetyState,
    caller_explicitly_requests_end,
)
from app.telephony.sessions import CallControl, CallSession

logger = logging.getLogger(__name__)

SKIP_TURN_REASONS = (
    "USER_REQUESTED_SILENCE",
    "WAITING_FOR_USER",
    "CONTINUE_LISTENING",
)
END_CALL_REASONS = ("USER_REQUEST", "CONVERSATION_COMPLETE")

DEFAULT_FAREWELL = (
    "Baik, saya akhiri panggilan ini sekarang. Terima kasih sudah berbicara dengan saya."
)
SAFETY_CONFIRMATION_QUESTION = (
    "Sebelum kita akhiri, saya khawatir dengan keselamatanmu. Apakah kamu aman saat ini? "
    "Jika tetap ingin mengakhiri panggilan, katakan saja. Jika ada bahaya langsung, "
    "dekati orang tepercaya atau hubungi layanan darurat setempat yang kamu ketahui."
)
SAFETY_CLARIFICATION_QUESTION = (
    "Saya belum yakin apakah kamu aman. Kamu ingin tetap berbicara, atau tetap "
    "mengakhiri panggilan?"
)
SAFETY_CONTINUE_MESSAGE = "Kita tidak perlu memutuskan sekarang. Saya bisa tetap mendengarkan."
SAFETY_CONFIRMATION_PLAYBACK_TIMEOUT = 16.0
SAFETY_FOLLOW_UP = (
    "Pengguna menyampaikan kemungkinan risiko keselamatan. Jangan diam atau mengakhiri "
    "panggilan atas dasar ini. Tanggapi dengan empati, tanyakan apakah pengguna sedang "
    "dalam bahaya langsung, dan dorong dukungan manusia tepercaya atau layanan darurat "
    "setempat yang mereka ketahui. Jangan mengarang nomor bantuan."
)


class SkipTurnArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Literal[
        "USER_REQUESTED_SILENCE",
        "WAITING_FOR_USER",
        "CONTINUE_LISTENING",
    ]


class EndCallArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Literal["USER_REQUEST", "CONVERSATION_COMPLETE"]
    farewell: str | None = Field(default=None, max_length=180)


class PlaybackController(Protocol):
    async def interrupt_and_wait(self, tts: Any, timeout: float = 2.0) -> None: ...

    async def speak_and_wait(
        self, tts: Any, text: str, timeout: float = 8.0
    ) -> None: ...


def recent_user_text(context: LLMContext, max_messages: int = 4) -> str:
    user_messages = [
        message.get("content", "")
        for message in context.get_messages()
        if isinstance(message, dict) and message.get("role") == "user"
    ][-max_messages:]
    return " ".join(text for text in user_messages if isinstance(text, str)).casefold()


def has_recent_safety_concern(context: LLMContext) -> bool:
    state = SafetyEngine().evaluate(recent_user_text(context)).state
    return state in {SafetyState.POTENTIAL_CRISIS, SafetyState.IMMEDIATE_DANGER}


def has_explicit_end_request(context: LLMContext) -> bool:
    text = recent_user_text(context, max_messages=1)
    return caller_explicitly_requests_end(text)


class CallControlTools:
    def __init__(
        self,
        *,
        session: CallSession,
        sessions: CallControl,
        tts: Any,
        playback: PlaybackController,
    ) -> None:
        self._session = session
        self._sessions = sessions
        self._tts = tts
        self._playback = playback
        self._ending_lock = asyncio.Lock()

    def schemas(self) -> list[FunctionSchema]:
        return [
            FunctionSchema(
                name="skip_turn",
                description=(
                    "Tetap diam pada giliran ini sesuai permintaan pengguna, lalu terus "
                    "mendengarkan. Jangan gunakan untuk melewati respons keselamatan."
                ),
                properties={
                    "reason": {
                        "type": "string",
                        "enum": list(SKIP_TURN_REASONS),
                    }
                },
                required=["reason"],
            ),
            FunctionSchema(
                name="end_call",
                description=(
                    "Akhiri panggilan hanya jika pengguna secara eksplisit memintanya "
                    "atau percakapan benar-benar selesai. Jangan putuskan panggilan hanya "
                    "karena pengguna sedang tertekan. Ucapkan salam perpisahan singkat."
                ),
                properties={
                    "reason": {"type": "string", "enum": list(END_CALL_REASONS)},
                    "farewell": {
                        "type": "string",
                        "description": "Salam perpisahan singkat dalam Bahasa Indonesia.",
                        "maxLength": 180,
                    },
                },
                required=["reason"],
            ),
        ]

    async def skip_turn(self, params: FunctionCallParams) -> None:
        logger.info("Call control requested: skip_turn")
        try:
            arguments = SkipTurnArguments.model_validate(dict(params.arguments))
        except ValidationError:
            logger.warning("Call control rejected: invalid_arguments")
            await params.result_callback(
                {"status": "rejected", "reason": "invalid_arguments"},
                properties=FunctionCallResultProperties(run_llm=True),
            )
            return

        if self._session.state != CallState.ACTIVE:
            await params.result_callback(
                {"status": "rejected", "reason": "call_is_ending"},
                properties=FunctionCallResultProperties(run_llm=False),
            )
            return

        if has_recent_safety_concern(params.context):
            await params.result_callback(
                {"status": "rejected", "reason": "safety_policy", "guidance": SAFETY_FOLLOW_UP},
                properties=FunctionCallResultProperties(run_llm=True),
            )
            return

        await self._playback.interrupt_and_wait(self._tts)
        await params.result_callback(
            {"status": "skipped", "reason": arguments.reason},
            properties=FunctionCallResultProperties(run_llm=False),
        )
        logger.info("Call control tool completed: skip_turn")

    @tool_options(cancel_on_interruption=False, timeout_secs=28)
    async def end_call(self, params: FunctionCallParams) -> None:
        logger.info("Call control requested: end_call")
        try:
            arguments = EndCallArguments.model_validate(dict(params.arguments))
        except ValidationError:
            logger.warning("Call control rejected: invalid_arguments")
            await params.result_callback(
                {"status": "rejected", "reason": "invalid_arguments"},
                properties=FunctionCallResultProperties(run_llm=True),
            )
            return

        explicit_request = has_explicit_end_request(params.context)
        confirmation_state = self._session.safety_confirmation_state
        confirmed_pending_end = self._session.pending_end_request and confirmation_state in {
            SafetyConfirmationState.CALLER_REPORTS_SAFE,
            SafetyConfirmationState.CALLER_DECLINES,
        }
        if (
            arguments.reason == "USER_REQUEST"
            and not explicit_request
            and not confirmed_pending_end
        ):
            logger.warning("Call control rejected: no_explicit_user_request")
            await params.result_callback(
                {
                    "status": "rejected",
                    "reason": "no_explicit_user_request",
                    "instruction": "Continue the conversation and do not end the call.",
                },
                properties=FunctionCallResultProperties(run_llm=True),
            )
            return

        if (
            self._session.pending_end_request
            and self._session.safety_confirmation_state
            == SafetyConfirmationState.CONFIRMATION_PENDING
        ):
            await self._handle_pending_confirmation(params)
            return

        safety_concern = (
            self._session.safety_state
            in {SafetyState.POTENTIAL_CRISIS, SafetyState.IMMEDIATE_DANGER}
            or has_recent_safety_concern(params.context)
        )
        if self._session.pending_end_request and not confirmed_pending_end:
            await self._handle_pending_confirmation(params)
            return

        if safety_concern and not confirmed_pending_end:
            if explicit_request:
                self._session.pending_end_request = True
                self._session.safety_confirmation_state = (
                    SafetyConfirmationState.CONFIRMATION_PENDING
                )
                self._session.safety_confirmation_turn = self._session.completed_user_turns
                self._session.safety_confirmation_prompted_turn = (
                    self._session.completed_user_turns
                )
                try:
                    await self._playback.interrupt_and_wait(self._tts)
                    await self._playback.speak_and_wait(
                        self._tts,
                        SAFETY_CONFIRMATION_QUESTION,
                        timeout=SAFETY_CONFIRMATION_PLAYBACK_TIMEOUT,
                    )
                    await params.result_callback(
                        {
                            "status": "safety_confirmation_required",
                            "question": SAFETY_CONFIRMATION_QUESTION,
                            "instruction": "Wait for the caller's next turn.",
                        },
                        properties=FunctionCallResultProperties(run_llm=False),
                    )
                except TimeoutError:
                    logger.warning(
                        "Safety confirmation playback timed out for session %s",
                        self._session.session_id,
                    )
                    await params.result_callback(
                        {
                            "status": "confirmation_pending_audio_timeout",
                            "instruction": "Do not repeat automatically; wait for the next caller turn.",
                        },
                        properties=FunctionCallResultProperties(run_llm=False),
                    )
                except Exception as error:
                    logger.warning(
                        "Safety confirmation playback failed for session %s: %s",
                        self._session.session_id,
                        type(error).__name__,
                    )
                    await params.result_callback(
                        {
                            "status": "safety_confirmation_required",
                            "question": SAFETY_CONFIRMATION_QUESTION,
                        },
                        properties=FunctionCallResultProperties(run_llm=True),
                    )
                return
            await params.result_callback(
                {"status": "rejected", "reason": "safety_policy", "guidance": SAFETY_FOLLOW_UP},
                properties=FunctionCallResultProperties(run_llm=True),
            )
            return

        async with self._ending_lock:
            if not await self._sessions.begin_ending(self._session):
                await params.result_callback(
                    {"status": "already_ending_or_ended"},
                    properties=FunctionCallResultProperties(run_llm=False),
                )
                return

            farewell = (arguments.farewell or DEFAULT_FAREWELL).strip() or DEFAULT_FAREWELL
            self._session.pending_end_request = False
            try:
                await self._playback.interrupt_and_wait(self._tts)
                await self._playback.speak_and_wait(self._tts, farewell)
            except asyncio.CancelledError:
                asyncio.create_task(
                    self._sessions.end_call(self._session, hangup_caller=True),
                    name=f"end-call-tool-cancelled-{self._session.session_id}",
                )
                raise
            except TimeoutError:
                logger.warning("Call farewell playback timed out for session %s", self._session.session_id)
            except Exception as error:
                logger.warning(
                    "Call farewell failed for session %s: %s",
                    self._session.session_id,
                    type(error).__name__,
                )

            try:
                await params.result_callback(
                    {"status": "ending"},
                    properties=FunctionCallResultProperties(run_llm=False),
                )
            finally:
                asyncio.create_task(
                    self._sessions.end_call(self._session, hangup_caller=True),
                    name=f"end-call-tool-{self._session.session_id}",
                )
        logger.info("Call control tool completed: end_call")

    async def _handle_pending_confirmation(self, params: FunctionCallParams) -> None:
        current_turn = self._session.completed_user_turns
        if self._session.safety_confirmation_prompted_turn == current_turn:
            await params.result_callback(
                {"status": "safety_confirmation_pending"},
                properties=FunctionCallResultProperties(run_llm=False),
            )
            return

        self._session.safety_confirmation_prompted_turn = current_turn
        if not self._session.safety_confirmation_clarification_sent:
            self._session.safety_confirmation_clarification_sent = True
            prompt = SAFETY_CLARIFICATION_QUESTION
        else:
            prompt = SAFETY_CONTINUE_MESSAGE
        try:
            await self._playback.interrupt_and_wait(self._tts)
            await self._playback.speak_and_wait(
                self._tts, prompt, timeout=SAFETY_CONFIRMATION_PLAYBACK_TIMEOUT
            )
        except TimeoutError:
            logger.warning(
                "Safety confirmation follow-up playback timed out for session %s",
                self._session.session_id,
            )
        except Exception as error:
            logger.warning(
                "Safety confirmation follow-up failed for session %s: %s",
                self._session.session_id,
                type(error).__name__,
            )
        await params.result_callback(
            {"status": "safety_confirmation_pending", "spoken_text": prompt},
            properties=FunctionCallResultProperties(run_llm=False),
        )

    async def finish_after_confirmation(self) -> bool:
        """End an already-requested call after caller safety confirmation/decline."""
        if not self._session.pending_end_request or self._session.safety_confirmation_state not in {
            SafetyConfirmationState.CALLER_REPORTS_SAFE,
            SafetyConfirmationState.CALLER_DECLINES,
        }:
            return False
        async with self._ending_lock:
            if not await self._sessions.begin_ending(self._session):
                return False
            self._session.pending_end_request = False
            try:
                await self._playback.interrupt_and_wait(self._tts)
                await self._playback.speak_and_wait(self._tts, DEFAULT_FAREWELL)
            except asyncio.CancelledError:
                asyncio.create_task(
                    self._sessions.end_call(self._session, hangup_caller=True),
                    name=f"confirmed-end-tool-cancelled-{self._session.session_id}",
                )
                raise
            except TimeoutError:
                logger.warning(
                    "Confirmed-end farewell timed out for session %s",
                    self._session.session_id,
                )
            except Exception as error:
                logger.warning(
                    "Confirmed-end farewell failed for session %s: %s",
                    self._session.session_id,
                    type(error).__name__,
                )
            finally:
                asyncio.create_task(
                    self._sessions.end_call(self._session, hangup_caller=True),
                    name=f"confirmed-end-tool-{self._session.session_id}",
                )
        return True
