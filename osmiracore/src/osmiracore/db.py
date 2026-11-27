"""Database engine and session handling (SQLAlchemy 2, SQLite)."""

from collections.abc import Iterator
from pathlib import Path

from fastapi import Request
from sqlalchemy import Engine, create_engine, event, inspect
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def make_engine(db_path: Path) -> Engine:
    engine = create_engine(f"sqlite:///{db_path}")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record) -> None:  # noqa: ANN001
        # SQLite ignores foreign keys (and ON DELETE CASCADE) unless asked.
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    return engine


class OutdatedSchema(RuntimeError):
    """The database was created by an older OsmiraCore."""


def init_db(engine: Engine) -> None:
    """Create missing tables. No migrations yet (ADR 0008): an existing table
    whose columns differ from the code makes the start fail with a clear
    message instead of obscure errors later."""
    from osmiracore import models  # noqa: F401  (registers the tables)

    existing = inspect(engine)
    problems: list[str] = []
    for table in Base.metadata.sorted_tables:
        if not existing.has_table(table.name):
            continue
        columns = {c["name"]: c for c in existing.get_columns(table.name)}
        for column in table.columns:
            found = columns.get(column.name)
            if found is None:
                problems.append(f"{table.name}.{column.name} is missing")
            elif bool(found["nullable"]) != bool(column.nullable) and not column.primary_key:
                problems.append(f"{table.name}.{column.name} nullability changed")
    if problems:
        raise OutdatedSchema(
            f"database {engine.url.database} was created by an older OsmiraCore "
            f"({'; '.join(problems)}). There are no migrations yet (ADR 0008): "
            "delete this file to start again with an empty database."
        )
    Base.metadata.create_all(engine)


def get_session(request: Request) -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    session_factory: sessionmaker[Session] = request.app.state.session_factory
    with session_factory() as session:
        yield session
