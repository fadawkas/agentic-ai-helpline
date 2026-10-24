import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.telephony import router


class EmptyCallSessions:
    async def claim_media_websocket(self, session_id: str):
        return None


def test_unknown_media_session_is_rejected_with_policy_close() -> None:
    app = FastAPI()
    app.state.call_sessions = EmptyCallSessions()
    app.include_router(router)

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as disconnected:
            with client.websocket_connect(f"/media?session_id={'a' * 32}"):
                pass

    assert disconnected.value.code == 1008
