"""Lightweight, versioned migration runner.

Creates the base schema from SQLAlchemy metadata, then applies ordered,
idempotent migration steps and records them in ``schema_migrations``.
Works identically on SQLite and PostgreSQL.
"""

from __future__ import annotations

import logging
from typing import Callable

from sqlalchemy import text
from sqlalchemy.engine import Engine

from database.models import Base, get_engine

logger = logging.getLogger("localai.migrations")

Migration = tuple[str, str, Callable[[Engine], None]]


def _sql(statement: str) -> Callable[[Engine], None]:
    def _run(engine: Engine) -> None:
        with engine.begin() as conn:
            conn.execute(text(statement))

    return _run


def _seed_reference_tables(engine: Engine) -> None:
    # Populated at runtime by registries; nothing to do at schema level.
    return None


MIGRATIONS: list[Migration] = [
    ("0001_initial", "Base schema from ORM metadata", _seed_reference_tables),
    (
        "0002_tasks_progress",
        "Ensure tasks.progress and index on status exist",
        _sql("CREATE INDEX IF NOT EXISTS ix_tasks_status ON tasks (status)"),
    ),
    (
        "0003_artifacts_task_index",
        "Index artifact->task lookups",
        _sql("CREATE INDEX IF NOT EXISTS ix_artifacts_task ON artifacts (task_id)"),
    ),
    (
        "0004_memory_scope_index",
        "Index memory scope/owner",
        _sql("CREATE INDEX IF NOT EXISTS ix_memory_scope_owner ON memory (scope, owner_id)"),
    ),
]


def _ensure_migrations_table(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version VARCHAR(64) PRIMARY KEY, "
                "description TEXT, "
                "applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
            )
        )


def applied_versions(engine: Engine) -> set[str]:
    _ensure_migrations_table(engine)
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT version FROM schema_migrations")).fetchall()
    return {r[0] for r in rows}


def init_db(engine: Engine | None = None) -> list[str]:
    """Create schema and apply pending migrations. Returns new versions."""
    engine = engine or get_engine()
    Base.metadata.create_all(engine)
    _ensure_migrations_table(engine)
    done = applied_versions(engine)
    newly: list[str] = []
    for version, description, fn in MIGRATIONS:
        if version in done:
            continue
        try:
            fn(engine)
        except Exception as exc:  # pragma: no cover - surfaced to caller
            logger.warning("Migration %s reported: %s", version, exc)
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO schema_migrations (version, description) VALUES (:v, :d)"),
                {"v": version, "d": description},
            )
        newly.append(version)
        logger.info("Applied migration %s (%s)", version, description)
    return newly


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    print("new migrations:", init_db())
