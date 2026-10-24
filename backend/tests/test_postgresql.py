import pytest

from app.db.postgres import postgres_is_ready


class FakePostgresPool:
    def __init__(self, result: int | None = 1, error: Exception | None = None):
        self.result = result
        self.error = error
        self.queries: list[str] = []

    async def fetchval(self, query: str) -> int | None:
        self.queries.append(query)
        if self.error:
            raise self.error
        return self.result


@pytest.mark.asyncio
async def test_postgresql_readiness_executes_select_one() -> None:
    pool = FakePostgresPool()

    assert await postgres_is_ready(pool)
    assert pool.queries == ["SELECT 1"]


@pytest.mark.asyncio
async def test_postgresql_readiness_reports_failure() -> None:
    pool = FakePostgresPool(error=ConnectionError("database unavailable"))

    assert not await postgres_is_ready(pool)
