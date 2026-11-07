import asyncio
import logging
from dataclasses import dataclass, field
from collections.abc import Awaitable, Callable
from typing import Protocol
from uuid import uuid4

from app.agent.state import CallState, transition_call_state
from app.safety.engine import SafetyConfirmationState, SafetyState

logger = logging.getLogger(__name__)


class AriCallControl(Protocol):
    async def create_bridge(self, bridge_id: str) -> None: ...

    async def add_channels(self, bridge_id: str, channel_ids: list[str]) -> None: ...

    async def answer(self, channel_id: str) -> None: ...

    async def create_media_channel(self, *, session_id: str, channel_id: str) -> None: ...

    async def hangup(self, channel_id: str) -> None: ...

    async def destroy_bridge(self, bridge_id: str) -> None: ...


@dataclass
class CallSession:
    session_id: str
    caller_channel_id: str
    bridge_id: str
    media_channel_id: str
    state: CallState = CallState.CONNECTING
    setup_task: asyncio.Task[None] | None = None
    media_pipeline_task: asyncio.Task[None] | None = None
    pipeline_ready: asyncio.Event = field(default_factory=asyncio.Event)
    media_websocket_claimed: bool = False
    cleanup_started: bool = False
    safety_state: SafetyState = SafetyState.NORMAL
    completed_user_turns: int = 0
    safety_confirmation_state: SafetyConfirmationState = SafetyConfirmationState.NOT_REQUIRED
    safety_confirmation_turn: int | None = None
    safety_confirmation_prompted_turn: int | None = None
    safety_confirmation_clarification_sent: bool = False
    pending_end_request: bool = False
    lifecycle_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def transition(self, target: CallState) -> None:
        self.state = transition_call_state(self.state, target)


class CallControl(Protocol):
    async def begin_ending(self, session: CallSession) -> bool: ...

    async def end_call(self, session: CallSession, *, hangup_caller: bool) -> None: ...


class CallSessionManager:
    def __init__(self, ari: AriCallControl):
        self._ari = ari
        self._sessions_by_id: dict[str, CallSession] = {}
        self._sessions_by_caller: dict[str, CallSession] = {}
        self._sessions_by_media: dict[str, CallSession] = {}
        self._lock = asyncio.Lock()

    def all_sessions(self) -> list[CallSession]:
        return list(self._sessions_by_id.values())

    def get_by_session_id(self, session_id: str) -> CallSession | None:
        return self._sessions_by_id.get(session_id)

    def get_by_caller_channel(self, channel_id: str) -> CallSession | None:
        return self._sessions_by_caller.get(channel_id)

    def get_by_media_channel(self, channel_id: str) -> CallSession | None:
        return self._sessions_by_media.get(channel_id)

    async def start_call(self, caller_channel_id: str) -> CallSession:
        async with self._lock:
            existing = self._sessions_by_caller.get(caller_channel_id)
            if existing:
                return existing

            session_id = uuid4().hex
            session = CallSession(
                session_id=session_id,
                caller_channel_id=caller_channel_id,
                bridge_id=f"voice-{session_id}",
                media_channel_id=f"media-{session_id}",
            )
            self._sessions_by_id[session_id] = session
            self._sessions_by_caller[caller_channel_id] = session
            self._sessions_by_media[session.media_channel_id] = session
            session.setup_task = asyncio.create_task(
                self._setup_call(session), name=f"setup-call-{session_id}"
            )
            return session

    async def claim_media_websocket(self, session_id: str) -> CallSession | None:
        async with self._lock:
            session = self._sessions_by_id.get(session_id)
            if (
                session is None
                or session.state not in {CallState.CONNECTING, CallState.ACTIVE}
                or session.media_websocket_claimed
            ):
                return None
            session.media_websocket_claimed = True
            return session

    async def begin_ending(self, session: CallSession) -> bool:
        async with session.lifecycle_lock:
            if session.state != CallState.ACTIVE:
                return False
            session.transition(CallState.ENDING)
            return True

    async def _setup_call(self, session: CallSession) -> None:
        try:
            await self._ari.create_bridge(session.bridge_id)
            await self._ari.create_media_channel(
                session_id=session.session_id,
                channel_id=session.media_channel_id,
            )
            await asyncio.wait_for(session.pipeline_ready.wait(), timeout=10)
            if session.state != CallState.CONNECTING:
                return
            await self._ari.add_channels(
                session.bridge_id,
                [session.caller_channel_id, session.media_channel_id],
            )
            await self._ari.answer(session.caller_channel_id)
            session.transition(CallState.ACTIVE)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.warning(
                "Call setup failed for session %s: %s",
                session.session_id,
                type(error).__name__,
            )
            await self.end_call(session, hangup_caller=True)

    async def end_call(self, session: CallSession, *, hangup_caller: bool) -> None:
        async with session.lifecycle_lock:
            if session.state == CallState.ENDED or session.cleanup_started:
                return
            if session.state != CallState.ENDING:
                session.transition(CallState.ENDING)
            session.cleanup_started = True

            current_task = asyncio.current_task()
            owned_tasks = [session.setup_task, session.media_pipeline_task]
            pending_tasks = [
                task for task in owned_tasks if task is not None and task is not current_task
            ]
            for task in pending_tasks:
                task.cancel()
            if pending_tasks:
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*pending_tasks, return_exceptions=True), timeout=2
                    )
                except TimeoutError:
                    logger.warning("Timed out cancelling call tasks for %s", session.session_id)

            cleanup_operations: list[tuple[str, Callable[[], Awaitable[None]]]] = [
                ("media channel", lambda: self._ari.hangup(session.media_channel_id)),
            ]
            if hangup_caller:
                cleanup_operations.append(
                    ("caller channel", lambda: self._ari.hangup(session.caller_channel_id))
                )
            cleanup_operations.append(
                ("bridge", lambda: self._ari.destroy_bridge(session.bridge_id))
            )
            for resource_name, cleanup in cleanup_operations:
                try:
                    await cleanup()
                except Exception as error:
                    logger.warning(
                        "Failed to clean up %s for session %s: %s",
                        resource_name,
                        session.session_id,
                        type(error).__name__,
                    )
            session.transition(CallState.ENDED)

        async with self._lock:
            self._sessions_by_id.pop(session.session_id, None)
            self._sessions_by_caller.pop(session.caller_channel_id, None)
            self._sessions_by_media.pop(session.media_channel_id, None)

    async def close_all(self) -> None:
        sessions = self.all_sessions()
        if sessions:
            await asyncio.gather(
                *(self.end_call(session, hangup_caller=True) for session in sessions),
                return_exceptions=True,
            )
