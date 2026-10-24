import asyncpg

from app.core.config import Settings


async def create_postgres_pool(settings: Settings) -> asyncpg.Pool:
    return await asyncpg.create_pool(
        host=settings.postgres_host,
        port=settings.postgres_port,
        user=settings.postgres_user,
        password=settings.postgres_password.get_secret_value(),
        database=settings.postgres_database,
        min_size=1,
        max_size=10,
        timeout=5,
        command_timeout=5,
    )


async def postgres_is_ready(pool: asyncpg.Pool) -> bool:
    try:
        return await pool.fetchval("SELECT 1") == 1
    except Exception:
        return False
