import sys
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path

from loguru import logger as pipecat_logger

from fastapi import FastAPI
from qdrant_client import AsyncQdrantClient

from app.api.health import router as health_router
from app.api.demo import router as demo_router
from app.api.admin import router as admin_router
from app.api.telephony import router as telephony_router
from app.core.config import settings
from app.db.postgres import create_postgres_pool
from app.rag.knowledge import KnowledgeBase
from app.rag.management import KnowledgeManager, initialize_knowledge_tables
from app.rag.validator import DocumentValidator
from app.telephony.ari import AriClient, AriEventLoop
from app.telephony.sessions import CallSessionManager


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Pipecat DEBUG logs include private conversation content.
    pipecat_logger.remove()
    pipecat_logger.add(sys.stderr, level="INFO")
    if settings.voice_agent_enabled:
        settings.validate_voice_agent()
    if settings.telephony_enabled:
        settings.validate_telephony()
    app.state.postgres_pool = await create_postgres_pool(settings)
    await initialize_knowledge_tables(app.state.postgres_pool, settings)
    app.state.qdrant_client = AsyncQdrantClient(url=settings.qdrant_url, timeout=2.5)
    app.state.knowledge_base = None
    app.state.document_validator = None
    app.state.knowledge_manager = None
    if settings.openrouter_api_key and settings.openrouter_api_key.get_secret_value().strip():
        app.state.knowledge_base = KnowledgeBase(
            settings, app.state.qdrant_client, postgres_pool=app.state.postgres_pool
        )
        await app.state.knowledge_base.initialize()
        app.state.document_validator = DocumentValidator(settings)
        app.state.knowledge_manager = KnowledgeManager(
            app.state.postgres_pool, app.state.knowledge_base,
            app.state.document_validator, settings,
        )
        await app.state.knowledge_manager.seed_baseline(
            Path("/app/knowledge/baseline-manifest.json")
        )
        await app.state.knowledge_base.load_sparse_index()
        await app.state.knowledge_manager.resume_jobs()
    else:
        app.state.knowledge_manager = None
    app.state.ari_client = None
    app.state.call_sessions = None
    app.state.ari_events = None
    if settings.telephony_enabled:
        app.state.ari_client = AriClient(settings)
        app.state.call_sessions = CallSessionManager(app.state.ari_client)
        app.state.ari_events = AriEventLoop(
            app.state.ari_client,
            app.state.call_sessions,
            settings.asterisk_ai_extension,
        )
        app.state.ari_events.start()
    app.state.voice_sample_rate = settings.voice_sample_rate
    app.state.settings = settings
    app.state.demo_sessions = set()
    app.state.demo_session_starts = deque()
    yield
    if app.state.ari_events is not None:
        await app.state.ari_events.close()
        await app.state.call_sessions.close_all()
        await app.state.ari_client.close()
    if app.state.knowledge_manager is not None:
        await app.state.knowledge_manager.close()
    if app.state.knowledge_base is not None:
        await app.state.knowledge_base.close()
    if app.state.document_validator is not None:
        await app.state.document_validator.close()
    await app.state.qdrant_client.close()
    await app.state.postgres_pool.close()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.include_router(health_router)
app.include_router(demo_router)
app.include_router(telephony_router)
app.include_router(admin_router)
