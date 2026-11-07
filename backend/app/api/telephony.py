import asyncio
import logging

from fastapi import APIRouter, Query, WebSocket

from app.voice.pipeline import run_loopback, run_voice_agent

logger = logging.getLogger(__name__)
router = APIRouter(tags=["telephony"])


@router.websocket("/media")
async def asterisk_media(
    websocket: WebSocket,
    session_id: str = Query(min_length=32, max_length=32),
) -> None:
    sessions = websocket.app.state.call_sessions
    if sessions is None:
        await websocket.close(code=1008)
        return
    session = await sessions.claim_media_websocket(session_id)
    if session is None:
        await websocket.close(code=1008)
        return

    try:
        await websocket.accept()
        pipeline_task = asyncio.create_task(
            (
                run_voice_agent(
                    websocket,
                    websocket.app.state.settings,
                    session.pipeline_ready,
                    session,
                    sessions,
                    websocket.app.state.knowledge_base,
                )
                if websocket.app.state.settings.voice_agent_enabled
                else run_loopback(
                    websocket,
                    websocket.app.state.voice_sample_rate,
                    session.pipeline_ready,
                )
            ),
            name=f"media-pipeline-{session.session_id}",
        )
        session.media_pipeline_task = pipeline_task
        await pipeline_task
    except asyncio.CancelledError:
        raise
    except Exception as error:
        logger.warning(
            "Media pipeline ended for session %s: %s",
            session.session_id,
            type(error).__name__,
        )
    finally:
        if session.media_pipeline_task is not None and session.media_pipeline_task.done():
            session.media_pipeline_task = None
        await sessions.end_call(session, hangup_caller=True)
