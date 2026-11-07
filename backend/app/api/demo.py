import asyncio
import json
import logging
import time
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect, WebSocketState
from pipecat.frames.frames import Frame, InputAudioRawFrame, InterruptionFrame, OutputAudioRawFrame
from pipecat.serializers.base_serializer import FrameSerializer
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport

from app.agent.state import CallState
from app.telephony.sessions import CallSession
from app.voice.pipeline import run_voice_agent

router = APIRouter(tags=["demo"])
logger = logging.getLogger(__name__)
DEMO_DURATION_SECONDS = 300
MAX_DEMO_SESSIONS = 3
MAX_DEMO_STARTS_PER_MINUTE = 6


class BrowserAudioSerializer(FrameSerializer):
    """Binary PCM16 little-endian mono; JSON is reserved for server control events."""

    def __init__(self, sample_rate: int):
        super().__init__()
        self.sample_rate = sample_rate

    async def serialize(self, frame: Frame) -> str | bytes | None:
        if isinstance(frame, OutputAudioRawFrame):
            return frame.audio
        if isinstance(frame, InterruptionFrame):
            return json.dumps({"type": "interruption"})
        return None

    async def deserialize(self, data: str | bytes) -> Frame | None:
        # Limit each packet to 250 ms; never accept arbitrary client pipeline frames.
        if not isinstance(data, bytes) or not data or len(data) % 2:
            raise ValueError("Expected PCM16 audio")
        if len(data) > self.sample_rate // 2:
            raise ValueError("Audio packet too large")
        return InputAudioRawFrame(audio=data, sample_rate=self.sample_rate, num_channels=1)


class BrowserCallControl:
    def __init__(self, websocket: WebSocket):
        self.websocket = websocket

    async def begin_ending(self, session: CallSession) -> bool:
        async with session.lifecycle_lock:
            if session.state != CallState.ACTIVE:
                return False
            session.transition(CallState.ENDING)
            return True

    async def end_call(self, session: CallSession, *, hangup_caller: bool) -> None:
        async with session.lifecycle_lock:
            if session.state == CallState.ENDED:
                return
            if session.state != CallState.ENDING:
                session.transition(CallState.ENDING)
            session.transition(CallState.ENDED)
            if (
                self.websocket.application_state == WebSocketState.CONNECTED
                and self.websocket.client_state == WebSocketState.CONNECTED
            ):
                try:
                    await self.websocket.close(code=1000)
                except WebSocketDisconnect:
                    # The peer can leave between the state check and the close send.
                    pass


@router.websocket("/api/demo/voice")
async def browser_voice(websocket: WebSocket) -> None:
    # Public does not mean cross-origin: prevent other sites embedding paid sessions.
    origin = urlsplit(websocket.headers.get("origin", ""))
    if origin.scheme not in {"http", "https"} or origin.netloc != websocket.headers.get("host"):
        await websocket.close(code=1008)
        return

    await websocket.accept()
    # Browser wire format is fixed at 16 kHz independently of SIP configuration.
    settings = websocket.app.state.settings.model_copy(update={"voice_sample_rate": 16000})
    if not settings.voice_agent_enabled or websocket.app.state.knowledge_base is None:
        await websocket.close(code=1013, reason="Layanan suara belum tersedia.")
        return
    try:
        settings.validate_voice_agent()
    except ValueError:
        await websocket.close(code=1013, reason="Layanan suara belum dikonfigurasi.")
        return

    active = websocket.app.state.demo_sessions
    if len(active) >= MAX_DEMO_SESSIONS:
        await websocket.close(code=1013, reason="Layanan sedang sibuk. Silakan coba beberapa saat lagi.")
        return
    # Bound paid-session churn as well as concurrency. This is process-local;
    # public deployments still need gateway rate limits and provider spending caps.
    starts = websocket.app.state.demo_session_starts
    now = time.monotonic()
    while starts and starts[0] <= now - 60:
        starts.popleft()
    if len(starts) >= MAX_DEMO_STARTS_PER_MINUTE:
        await websocket.close(code=1013, reason="Terlalu banyak percakapan baru. Tunggu sebentar, lalu coba lagi.")
        return
    starts.append(now)
    session = CallSession(uuid4().hex, "", "", "")
    active.add(session.session_id)
    session.transition(CallState.ACTIVE)
    control = BrowserCallControl(websocket)
    tasks: list[asyncio.Task] = []
    try:
        transport = FastAPIWebsocketTransport(
            websocket=websocket,
            params=FastAPIWebsocketParams(
                audio_in_enabled=True,
                audio_out_enabled=True,
                audio_in_sample_rate=settings.voice_sample_rate,
                audio_out_sample_rate=settings.voice_sample_rate,
                audio_in_channels=1,
                audio_out_channels=1,
                serializer=BrowserAudioSerializer(settings.voice_sample_rate),
            ),
        )
        async with asyncio.timeout(DEMO_DURATION_SECONDS):
            pipeline = asyncio.create_task(run_voice_agent(
                websocket, settings, session.pipeline_ready, session, control,
                websocket.app.state.knowledge_base, transport=transport,
            ))
            ready = asyncio.create_task(session.pipeline_ready.wait())
            tasks.extend([pipeline, ready])
            done, _ = await asyncio.wait(tasks, timeout=30, return_when=asyncio.FIRST_COMPLETED)
            if pipeline in done:
                await pipeline
            elif ready in done:
                await websocket.send_json({"type": "ready", "sample_rate": settings.voice_sample_rate})
                await pipeline
            else:
                await websocket.close(code=1013, reason="Koneksi AI terlalu lama. Coba lagi.")
    except TimeoutError:
        if websocket.application_state == WebSocketState.CONNECTED:
            await websocket.close(code=1000, reason="Sesi 5 menit telah selesai. Kamu dapat memulai percakapan baru.")
    except asyncio.CancelledError:
        raise
    except Exception as error:
        logger.warning("Browser demo ended: %s", type(error).__name__)
        if websocket.application_state == WebSocketState.CONNECTED:
            await websocket.close(code=1011, reason="Koneksi AI terputus. Silakan coba lagi.")
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        try:
            await control.end_call(session, hangup_caller=False)
        finally:
            active.discard(session.session_id)
