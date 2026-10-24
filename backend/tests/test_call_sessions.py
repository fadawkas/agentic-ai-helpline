import pytest

from app.agent.state import CallState, transition_call_state
from app.telephony.sessions import CallSessionManager
from app.voice.pipeline import make_loopback_frame
from pipecat.frames.frames import InputAudioRawFrame


def test_call_state_allows_only_defined_transitions() -> None:
    assert transition_call_state(CallState.CONNECTING, CallState.ACTIVE) == CallState.ACTIVE
    assert transition_call_state(CallState.ACTIVE, CallState.ENDING) == CallState.ENDING
    with pytest.raises(ValueError):
        transition_call_state(CallState.ENDED, CallState.ACTIVE)


class FakeAriClient:
    def __init__(self, *, fail_media_hangup: bool = False):
        self.fail_media_hangup = fail_media_hangup
        self.calls: list[tuple[str, str]] = []

    async def create_bridge(self, bridge_id: str) -> None:
        self.calls.append(("create_bridge", bridge_id))

    async def create_media_channel(self, *, session_id: str, channel_id: str) -> None:
        self.calls.append(("create_media", channel_id))

    async def add_channels(self, bridge_id: str, channel_ids: list[str]) -> None:
        self.calls.append(("add_channels", ",".join(channel_ids)))

    async def answer(self, channel_id: str) -> None:
        self.calls.append(("answer", channel_id))

    async def hangup(self, channel_id: str) -> None:
        self.calls.append(("hangup", channel_id))
        if self.fail_media_hangup and channel_id.startswith("media-"):
            raise RuntimeError("simulated hangup failure")

    async def destroy_bridge(self, bridge_id: str) -> None:
        self.calls.append(("destroy_bridge", bridge_id))


@pytest.mark.asyncio
async def test_call_session_setup_and_hangup_are_isolated_and_idempotent() -> None:
    ari = FakeAriClient()
    manager = CallSessionManager(ari)

    session = await manager.start_call("caller-1")
    assert await manager.start_call("caller-1") is session
    assert manager.get_by_media_channel(session.media_channel_id) is session

    session.pipeline_ready.set()
    assert session.setup_task is not None
    await session.setup_task
    assert session.state == CallState.ACTIVE

    await manager.end_call(session, hangup_caller=False)
    await manager.end_call(session, hangup_caller=False)

    assert session.state == CallState.ENDED
    assert manager.get_by_caller_channel("caller-1") is None
    assert ("hangup", "caller-1") not in ari.calls
    assert ("destroy_bridge", session.bridge_id) in ari.calls


@pytest.mark.asyncio
async def test_cleanup_continues_when_a_resource_hangup_fails() -> None:
    ari = FakeAriClient(fail_media_hangup=True)
    manager = CallSessionManager(ari)
    session = await manager.start_call("caller-2")
    session.pipeline_ready.set()
    assert session.setup_task is not None
    await session.setup_task

    await manager.end_call(session, hangup_caller=True)

    assert session.state == CallState.ENDED
    assert ("hangup", "caller-2") in ari.calls
    assert ("destroy_bridge", session.bridge_id) in ari.calls


def test_loopback_frame_preserves_audio_and_format() -> None:
    frame = InputAudioRawFrame(audio=b"\x01\x02", sample_rate=16000, num_channels=1)

    output = make_loopback_frame(frame)

    assert output.audio == frame.audio
    assert output.sample_rate == frame.sample_rate
    assert output.num_channels == frame.num_channels
