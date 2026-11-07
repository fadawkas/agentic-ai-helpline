import asyncio
import json
from collections import deque
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pipecat.frames.frames import InputAudioRawFrame, InterruptionFrame, OutputAudioRawFrame
from starlette.websockets import WebSocketDisconnect

from app.api import demo
from app.agent.state import CallState
from app.core.config import Settings
from app.telephony.sessions import CallSession

ORIGIN = {"origin": "http://testserver"}


def demo_app() -> FastAPI:
    app = FastAPI()
    app.state.settings = Settings(
        postgres_password="test-only", asterisk_ari_username="test-only",
        asterisk_ari_password="test-only", voice_agent_enabled=True,
        deepgram_api_key="test-only", openrouter_api_key="test-only",
        fish_audio_api_key="test-only", fish_reference_id="test-only",
    )
    app.state.knowledge_base = object()
    app.state.demo_sessions = set()
    app.state.demo_session_starts = deque()
    app.include_router(demo.router)
    return app


def test_real_browser_transport_streams_pcm_and_stops_on_disconnect(monkeypatch) -> None:
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.worker import PipelineParams, PipelineWorker
    from pipecat.workers.runner import WorkerRunner
    from app.voice.pipeline import AudioLoopbackProcessor, PipelineReadyProcessor

    app = demo_app()
    ended = Event()

    async def loopback(websocket, settings, ready, *args, transport, **kwargs):
        worker = PipelineWorker(
            Pipeline([transport.input(), AudioLoopbackProcessor(), transport.output(), PipelineReadyProcessor(ready)]),
            params=PipelineParams(audio_in_sample_rate=16000, audio_out_sample_rate=16000),
        )

        @transport.event_handler("on_client_disconnected")
        async def disconnected(_transport, _websocket):
            await worker.cancel()

        runner = WorkerRunner(handle_sigint=False)
        try:
            await runner.add_workers(worker)
            await runner.run()
        finally:
            ended.set()

    monkeypatch.setattr(demo, "run_voice_agent", loopback)
    with TestClient(app) as client:
        with client.websocket_connect("/api/demo/voice", headers=ORIGIN) as ws:
            assert ws.receive_json()["type"] == "ready"
            pcm = b"\x01\x00" * 3840
            ws.send_bytes(pcm)
            received = b""
            while len(received) < len(pcm):
                received += ws.receive_bytes()
            assert received == pcm
        assert ended.wait(2)
    assert not app.state.demo_sessions


def test_public_demo_connects_without_telephony_and_releases_slot(monkeypatch) -> None:
    app = demo_app()
    ended = Event()

    async def pipeline(websocket, settings, ready, session, sessions, knowledge_base, *, transport):
        assert settings.voice_sample_rate == 16000
        assert session.state == CallState.ACTIVE
        assert isinstance(transport, demo.FastAPIWebsocketTransport)
        ready.set()
        try:
            audio = await websocket.receive_bytes()
            await websocket.send_bytes(audio)
            await websocket.receive_bytes()
        except WebSocketDisconnect:
            pass
        finally:
            ended.set()

    monkeypatch.setattr(demo, "run_voice_agent", pipeline)
    with TestClient(app) as client:
        with client.websocket_connect("/api/demo/voice", headers=ORIGIN) as ws:
            assert ws.receive_json() == {"type": "ready", "sample_rate": 16000}
            ws.send_bytes(b"\x01\x00" * 320)
            assert ws.receive_bytes() == b"\x01\x00" * 320
        assert ended.wait(2)
    assert not app.state.demo_sessions


@pytest.mark.parametrize("headers", [{}, {"origin": "https://other-site.example"}])
def test_demo_rejects_missing_or_foreign_origin(headers) -> None:
    with TestClient(demo_app()) as client:
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect("/api/demo/voice", headers=headers):
                pass
        assert error.value.code == 1008


@pytest.mark.parametrize("unavailable", ["disabled", "knowledge", "credentials", "capacity"])
def test_demo_rejects_unavailable_service_without_starting_pipeline(monkeypatch, unavailable) -> None:
    app = demo_app()
    pipeline = AsyncMock()
    monkeypatch.setattr(demo, "run_voice_agent", pipeline)
    if unavailable == "disabled":
        app.state.settings.voice_agent_enabled = False
    elif unavailable == "knowledge":
        app.state.knowledge_base = None
    elif unavailable == "credentials":
        app.state.settings.fish_audio_api_key = None
    else:
        app.state.demo_sessions.update(str(i) for i in range(demo.MAX_DEMO_SESSIONS))
    with TestClient(app) as client:
        with client.websocket_connect("/api/demo/voice", headers=ORIGIN) as ws:
            with pytest.raises(WebSocketDisconnect) as error:
                ws.receive_json()
            assert error.value.code == 1013
    pipeline.assert_not_called()


@pytest.mark.parametrize("expired", [False, True])
def test_session_start_throttle_expires_and_bounds_churn(monkeypatch, expired) -> None:
    app = demo_app()
    monkeypatch.setattr(demo, "time", SimpleNamespace(monotonic=lambda: 100.0))
    app.state.demo_session_starts.extend(
        [39.0 if expired else 99.0] * demo.MAX_DEMO_STARTS_PER_MINUTE
    )
    pipeline = AsyncMock(side_effect=RuntimeError("test pipeline ended"))
    monkeypatch.setattr(demo, "run_voice_agent", pipeline)
    with TestClient(app) as client:
        with client.websocket_connect("/api/demo/voice", headers=ORIGIN) as ws:
            with pytest.raises(WebSocketDisconnect) as error:
                ws.receive_json()
            assert error.value.code == (1011 if expired else 1013)
    assert pipeline.await_count == (1 if expired else 0)
    assert len(app.state.demo_session_starts) == (1 if expired else demo.MAX_DEMO_STARTS_PER_MINUTE)
    assert not app.state.demo_sessions


def test_pipeline_failure_releases_slot_and_returns_safe_error(monkeypatch) -> None:
    app = demo_app()
    monkeypatch.setattr(demo, "run_voice_agent", AsyncMock(side_effect=RuntimeError("private error")))
    with TestClient(app) as client:
        with client.websocket_connect("/api/demo/voice", headers=ORIGIN) as ws:
            with pytest.raises(WebSocketDisconnect) as error:
                ws.receive_json()
            assert error.value.code == 1011
            assert "private" not in error.value.reason
    assert not app.state.demo_sessions


def test_demo_duration_cancels_pipeline_and_releases_slot(monkeypatch) -> None:
    app = demo_app()
    ended = Event()

    async def pipeline(websocket, settings, ready, *args, **kwargs):
        ready.set()
        try:
            await asyncio.Event().wait()
        finally:
            ended.set()

    monkeypatch.setattr(demo, "run_voice_agent", pipeline)
    monkeypatch.setattr(demo, "DEMO_DURATION_SECONDS", 0.1)
    with TestClient(app) as client:
        with client.websocket_connect("/api/demo/voice", headers=ORIGIN) as ws:
            assert ws.receive_json()["type"] == "ready"
            with pytest.raises(WebSocketDisconnect) as error:
                ws.receive_json()
            assert error.value.code == 1000
    assert ended.wait(2)
    assert not app.state.demo_sessions


@pytest.mark.asyncio
async def test_browser_serializer_pcm_and_interruption() -> None:
    serializer = demo.BrowserAudioSerializer(16000)
    pcm = b"\x00\x01" * 320
    frame = await serializer.deserialize(pcm)
    assert isinstance(frame, InputAudioRawFrame)
    assert frame.audio == pcm and frame.sample_rate == 16000 and frame.num_channels == 1
    assert await serializer.serialize(OutputAudioRawFrame(pcm, 16000, 1)) == pcm
    assert json.loads(await serializer.serialize(InterruptionFrame())) == {"type": "interruption"}


@pytest.mark.asyncio
@pytest.mark.parametrize("packet", [b"", b"\x00", b"\x00" * 8002, '{"type":"end_call"}'])
async def test_browser_serializer_rejects_invalid_packets(packet) -> None:
    with pytest.raises(ValueError):
        await demo.BrowserAudioSerializer(16000).deserialize(packet)


@pytest.mark.asyncio
async def test_browser_call_control_closes_socket_without_sip() -> None:
    websocket = AsyncMock()
    websocket.application_state = demo.WebSocketState.CONNECTED
    websocket.client_state = demo.WebSocketState.CONNECTED
    control = demo.BrowserCallControl(websocket)
    session = CallSession("demo", "", "", "")
    session.transition(CallState.ACTIVE)
    assert await control.begin_ending(session)
    assert not await control.begin_ending(session)
    await control.end_call(session, hangup_caller=True)
    await control.end_call(session, hangup_caller=True)
    websocket.close.assert_awaited_once_with(code=1000)
    assert session.state == CallState.ENDED


@pytest.mark.asyncio
@pytest.mark.parametrize("peer_already_left", [False, True])
async def test_browser_cleanup_tolerates_client_disconnect(peer_already_left) -> None:
    websocket = AsyncMock()
    websocket.application_state = demo.WebSocketState.CONNECTED
    websocket.client_state = (
        demo.WebSocketState.DISCONNECTED if peer_already_left else demo.WebSocketState.CONNECTED
    )
    websocket.close.side_effect = WebSocketDisconnect(code=1006)
    control = demo.BrowserCallControl(websocket)
    session = CallSession("demo", "", "", "")
    session.transition(CallState.ACTIVE)

    await control.end_call(session, hangup_caller=False)
    await control.end_call(session, hangup_caller=False)

    assert session.state == CallState.ENDED
    if peer_already_left:
        websocket.close.assert_not_awaited()
    else:
        websocket.close.assert_awaited_once_with(code=1000)
