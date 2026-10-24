import logging
from typing import Any

from pipecat.frames.frames import LLMContextFrame
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import Frame, FrameDirection, FrameProcessor

from app.agent.jev import (
    AgentPersonality,
    JevRouter,
    latest_user_text,
    personality_instruction,
)
from app.agent.tools import CallControlTools
from app.safety.engine import (
    SafetyConfirmationState,
    SafetyEngine,
    SafetyState,
    SafetyStateTracker,
    advance_confirmation_state,
)
from app.telephony.sessions import CallSession

logger = logging.getLogger(__name__)
_POLICY_MARKER = "__voice_turn_policy__"


def _latest_user_message(context: LLMContext) -> Any | None:
    return next(
        (
            message
            for message in reversed(context.get_messages())
            if isinstance(message, dict) and message.get("role") == "user"
        ),
        None,
    )


def _safety_instruction(
    state: SafetyState, confirmation_state: SafetyConfirmationState
) -> str:
    if confirmation_state == SafetyConfirmationState.CONFIRMATION_PENDING:
        if state == SafetyState.IMMEDIATE_DANGER:
            return (
                "Lapisan keselamatan utama: tanyakan apakah pengguna sedang dalam bahaya "
                "langsung, dorong dukungan manusia tepercaya atau layanan darurat setempat "
                "yang mereka ketahui, dan jangan mengarang nomor. Pengguna sebelumnya meminta "
                "mengakhiri panggilan; dengarkan jawabannya, jangan ulangi pertanyaan konfirmasi, "
                "dan hormati jika mereka mengulangi permintaan mengakhiri."
            )
        if state == SafetyState.POTENTIAL_CRISIS:
            return (
                "Lapisan keselamatan utama: klarifikasi dengan tenang apakah pengguna aman "
                "saat ini dan dorong dukungan manusia tepercaya. Pengguna sebelumnya meminta "
                "mengakhiri panggilan; dengarkan jawabannya, jangan ulangi pertanyaan konfirmasi, "
                "dan hormati jika mereka mengulangi permintaan mengakhiri."
            )
        return (
            "Pengguna sudah diminta satu kali untuk mengonfirmasi keselamatannya sebelum "
            "mengakhiri panggilan. Dengarkan jawabannya. Jika belum jelas, lanjutkan "
            "percakapan dengan lembut; jangan mengakhiri panggilan otomatis. Jika pengguna "
            "mengulangi permintaan untuk mengakhiri, hormati dan gunakan end_call."
        )
    if state == SafetyState.IMMEDIATE_DANGER:
        return (
            "Lapisan keselamatan: prioritaskan keselamatan saat ini. Tanyakan apakah "
            "pengguna sedang dalam bahaya langsung; dorong mereka mendekati orang "
            "tepercaya dan menghubungi layanan darurat setempat yang mereka ketahui. "
            "Jangan mengarang nomor bantuan, mendiagnosis, atau mengakhiri panggilan "
            "secara otomatis. Namun, jika pengguna secara eksplisit meminta mengakhiri "
            "panggilan, hormati permintaannya dan gunakan end_call dengan reason USER_REQUEST."
        )
    if state == SafetyState.POTENTIAL_CRISIS:
        return (
            "Lapisan keselamatan: tanggapi dengan tenang dan empatik. Klarifikasi apakah "
            "pengguna aman saat ini dan dorong dukungan manusia tepercaya. Jangan diam "
            "atau menyimpulkan bahaya langsung tanpa klarifikasi."
        )
    if state == SafetyState.NEEDS_SUPPORT:
        return (
            "Lapisan keselamatan: validasi perasaan tanpa menganggap diagnosis dan "
            "tanyakan dukungan seperti apa yang diinginkan pengguna."
        )
    return ""


class AgentPolicyProcessor(FrameProcessor):
    def __init__(
        self,
        safety: SafetyEngine,
        jev: JevRouter,
        session: CallSession,
        call_tools: CallControlTools,
    ):
        super().__init__()
        self._safety = safety
        self._safety_tracker = SafetyStateTracker()
        self._jev = jev
        self._session = session
        self._call_tools = call_tools
        self._last_user_message: Any | None = None
        self._completed_turns = 0
        self._safety_state = SafetyState.NORMAL
        self._personality = AgentPersonality.NEUTRAL

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMContextFrame) and direction == FrameDirection.DOWNSTREAM:
            context = frame.context
            messages = [
                message
                for message in context.get_messages()
                if not (
                    isinstance(message, dict)
                    and message.get("name") == _POLICY_MARKER
                )
            ]
            context.set_messages(messages)
            latest_message = _latest_user_message(context)
            if latest_message is not None and latest_message is not self._last_user_message:
                self._last_user_message = latest_message
                self._completed_turns += 1
                self._session.completed_user_turns = self._completed_turns
                text = latest_user_text(context)
                evaluation = self._safety.evaluate(text)
                self._safety_state = self._safety_tracker.update(evaluation)
                self._session.safety_state = self._safety_state

                self._session.safety_confirmation_state = advance_confirmation_state(
                    self._session.safety_confirmation_state,
                    confirmation_turn=self._session.safety_confirmation_turn,
                    current_turn=self._completed_turns,
                    text=text,
                    evaluation=evaluation,
                )
                if (
                    self._session.safety_confirmation_state
                    == SafetyConfirmationState.CALLER_REPORTS_SAFE
                ):
                    self._safety_state = self._safety_tracker.record_user_safe_report()
                    self._session.safety_state = self._safety_state

                    if self._session.safety_confirmation_state in {
                        SafetyConfirmationState.CALLER_REPORTS_SAFE,
                        SafetyConfirmationState.CALLER_DECLINES,
                    }:
                        # Honor the caller's original end request after the one-step
                        # confirmation. This path is Python-controlled, not model-gated.
                        await self._call_tools.finish_after_confirmation()
                        return

                decision = await self._jev.route(
                    context,
                    turn=self._completed_turns,
                    safety_state=self._safety_state,
                )
                self._personality = (
                    AgentPersonality.NEUTRAL
                    if self._safety_state
                    in {SafetyState.POTENTIAL_CRISIS, SafetyState.IMMEDIATE_DANGER}
                    else decision.personality
                )
                logger.info(
                    "Turn policy applied: safety=%s personality=%s confidence=%.2f code=%s turn=%d",
                    self._safety_state.value,
                    decision.personality.value,
                    decision.confidence,
                    decision.reasoning_code.value,
                    self._completed_turns,
                )
            instruction = " ".join(
                part
                for part in (
                    _safety_instruction(
                        self._safety_state,
                        self._session.safety_confirmation_state,
                    ),
                    personality_instruction(self._personality),
                )
                if part
            )
            updated_messages = context.get_messages()
            system_count = 0
            while (
                system_count < len(updated_messages)
                and isinstance(updated_messages[system_count], dict)
                and updated_messages[system_count].get("role") == "system"
            ):
                system_count += 1
            updated_messages.insert(
                system_count,
                {"role": "system", "name": _POLICY_MARKER, "content": instruction},
            )
            context.set_messages(updated_messages)
        await self.push_frame(frame, direction)
