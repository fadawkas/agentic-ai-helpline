from fastapi import APIRouter, Request, Response

from app.db.postgres import postgres_is_ready

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("/live")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def readiness(request: Request, response: Response) -> dict[str, object]:
    checks: dict[str, str] = {}
    checks["postgresql"] = (
        "ok" if await postgres_is_ready(request.app.state.postgres_pool) else "unavailable"
    )
    try:
        await request.app.state.qdrant_client.get_collections()
        checks["qdrant"] = "ok"
    except Exception:
        checks["qdrant"] = "unavailable"
    checks["asterisk_ari"] = (
        "disabled" if request.app.state.ari_events is None
        else "ok" if request.app.state.ari_events.is_connected else "unavailable"
    )

    ready = all(status in {"ok", "disabled"} for status in checks.values())
    if not ready:
        response.status_code = 503
    return {"status": "ok" if ready else "unavailable", "dependencies": checks}
