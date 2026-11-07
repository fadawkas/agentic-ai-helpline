from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import app.main as main
from app.api.health import router as health_router
from app.api.telephony import router as telephony_router
from app.core.config import Settings


@pytest.mark.asyncio
@pytest.mark.parametrize("telephony_enabled", [False, True])
async def test_lifespan_only_starts_and_closes_enabled_telephony(monkeypatch, telephony_enabled):
    settings = Settings(
        postgres_password="test-only", voice_agent_enabled=False,
        telephony_enabled=telephony_enabled, openrouter_api_key=None,
        asterisk_ari_username="test-only", asterisk_ari_password="test-only",
    )
    pool = SimpleNamespace(close=AsyncMock())
    qdrant = SimpleNamespace(close=AsyncMock())
    ari = SimpleNamespace(close=AsyncMock())
    sessions = SimpleNamespace(close_all=AsyncMock())
    events = SimpleNamespace(start=Mock(), close=AsyncMock())
    ari_factory = Mock(return_value=ari)
    monkeypatch.setattr(main, "settings", settings)
    monkeypatch.setattr(main, "create_postgres_pool", AsyncMock(return_value=pool))
    monkeypatch.setattr(main, "initialize_knowledge_tables", AsyncMock())
    monkeypatch.setattr(main, "AsyncQdrantClient", Mock(return_value=qdrant))
    monkeypatch.setattr(main, "AriClient", ari_factory)
    monkeypatch.setattr(main, "CallSessionManager", Mock(return_value=sessions))
    monkeypatch.setattr(main, "AriEventLoop", Mock(return_value=events))
    app = FastAPI()
    async with main.lifespan(app):
        assert (app.state.ari_events is not None) == telephony_enabled
        assert (app.state.call_sessions is not None) == telephony_enabled
        assert not app.state.demo_sessions
    assert ari_factory.call_count == int(telephony_enabled)
    assert events.start.call_count == int(telephony_enabled)
    assert events.close.await_count == int(telephony_enabled)
    assert sessions.close_all.await_count == int(telephony_enabled)
    assert ari.close.await_count == int(telephony_enabled)
    qdrant.close.assert_awaited_once()
    pool.close.assert_awaited_once()


@pytest.mark.parametrize("connected,expected_status", [(None, 200), (True, 200), (False, 503)])
def test_readiness_requires_ari_only_when_enabled(monkeypatch, connected, expected_status):
    from app.api import health

    app = FastAPI()
    app.include_router(health_router)
    app.state.postgres_pool = object()
    app.state.qdrant_client = SimpleNamespace(get_collections=AsyncMock())
    app.state.ari_events = None if connected is None else SimpleNamespace(is_connected=connected)
    monkeypatch.setattr(health, "postgres_is_ready", AsyncMock(return_value=True))
    with TestClient(app) as client:
        response = client.get("/api/health/ready")
    assert response.status_code == expected_status
    assert response.json()["dependencies"]["asterisk_ari"] == (
        "disabled" if connected is None else "ok" if connected else "unavailable"
    )


def test_media_endpoint_rejects_disabled_telephony():
    app = FastAPI()
    app.state.call_sessions = None
    app.include_router(telephony_router)
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect(f"/media?session_id={'a' * 32}"):
                pass
    assert error.value.code == 1008


def test_browser_settings_do_not_require_telephony_secrets():
    settings = Settings(postgres_password="test-only", asterisk_ari_password="")
    assert not settings.telephony_enabled
    with pytest.raises(ValueError, match="Telephony requires"):
        settings.validate_telephony()
