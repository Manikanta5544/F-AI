"""
Alembic env.py — async SQLAlchemy (asyncpg) + PostgreSQL.
This file is the single source of truth for migration execution.
"""
import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

# ── Logging ───────────────────────────────────────────────────────────────────
alembic_config = context.config
if alembic_config.config_file_name is not None:
    fileConfig(alembic_config.config_file_name)

# ── Models → metadata ─────────────────────────────────────────────────────────
# Must import Base BEFORE accessing Base.metadata — side-effect registers tables.
from app.core.database import Base  # noqa: E402
from app.models.db import models    # noqa: E402, F401 — registers all ORM models

target_metadata = Base.metadata

# ── Database URL ──────────────────────────────────────────────────────────────
# Priority: env var DATABASE_URL > alembic.ini sqlalchemy.url > settings
def _get_url() -> str:
    """
    Return the async (asyncpg) database URL for online mode.
    Allows overriding via DATABASE_URL env var — useful in Docker/CI.
    """
    env_url = os.getenv("DATABASE_URL")
    if env_url:
        # Normalise: strip any +asyncpg already present, then re-add
        base = env_url.replace("postgresql+asyncpg://", "postgresql://") \
                      .replace("postgresql+psycopg2://", "postgresql://")
        return base.replace("postgresql://", "postgresql+asyncpg://", 1)

    from app.core.config import settings
    return settings.ASYNC_DATABASE_URL


# ── Offline mode (generates SQL without connecting) ───────────────────────────
def run_migrations_offline() -> None:
    """
    Emit SQL to stdout instead of executing — useful for review/audit.
    Uses the synchronous URL (strip asyncpg driver prefix).
    """
    url = _get_url().replace("+asyncpg", "")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# ── Online mode (executes against the database) ───────────────────────────────
def _do_run_migrations(sync_connection) -> None:
    """
    Synchronous callback passed to conn.run_sync().

    CRITICAL: context.configure() and context.run_migrations() must both be
    called here, against the same sync_connection object.
    Splitting them across two run_sync() calls causes Alembic to run migrations
    against an unbound context — DDL is emitted but never committed.
    """
    context.configure(
        connection=sync_connection,
        target_metadata=target_metadata,
        compare_type=True,
        # Preserve existing server defaults during autogenerate
        compare_server_default=False,
        # Render NULL/NOT NULL changes
        include_schemas=False,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """
    Connect to PostgreSQL and run all pending migrations.

    Uses engine.begin() — the connection auto-commits on clean exit and
    auto-rolls-back on exception. This is the correct pattern for DDL.
    Do NOT use engine.connect() + conn.begin() — that creates a nested
    transaction savepoint on asyncpg that silently prevents DDL commits.
    """
    url = _get_url()
    engine = create_async_engine(
        url,
        # Isolation level AUTOCOMMIT lets CREATE INDEX CONCURRENTLY work.
        # Alembic handles its own transaction via context.begin_transaction().
        isolation_level="AUTOCOMMIT",
        echo=False,
        pool_pre_ping=True,
    )

    async with engine.begin() as conn:
        await conn.run_sync(_do_run_migrations)

    await engine.dispose()


# ── Entry point ───────────────────────────────────────────────────────────────
if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())