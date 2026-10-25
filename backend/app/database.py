import os
from pathlib import Path
from typing import Iterator

from fastapi import Request
from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import ArgumentError, SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.engine import make_url


DEFAULT_DATABASE_PATH = Path(__file__).resolve().parents[1] / ".data" / "devpilot.db"


class Base(DeclarativeBase):
    pass


class Database:
    def __init__(self, engine: Engine):
        self.engine = engine
        self.session_factory = sessionmaker(
            bind=engine,
            autoflush=False,
            expire_on_commit=False,
        )


def _configured_database_url(database_url: str | None = None) -> str:
    configured = database_url
    if configured is None:
        configured = os.environ.get("DEVPILOT_DATABASE_URL", "").strip()
    if not configured:
        return f"sqlite:///{DEFAULT_DATABASE_PATH.as_posix()}"

    try:
        parsed = make_url(configured)
    except (ArgumentError, TypeError, ValueError):
        raise RuntimeError("The configured local database setting is invalid.") from None
    if parsed.get_backend_name() != "sqlite":
        raise RuntimeError("This DevPilot version supports SQLite only.")
    return configured


def create_database(database_url: str | None = None) -> Database:
    url = _configured_database_url(database_url)
    try:
        parsed = make_url(url)
        filename = parsed.database
        if filename and filename != ":memory:" and not filename.startswith("file:"):
            Path(filename).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(
            url,
            connect_args={"check_same_thread": False},
        )
    except (OSError, SQLAlchemyError, TypeError, ValueError):
        raise RuntimeError("The local database could not be configured.") from None
    return Database(engine)


def initialize_database(database: Database) -> None:
    # Import registers the model with the shared declarative metadata.
    from app.models import Decision  # noqa: F401

    try:
        Base.metadata.create_all(database.engine)
    except SQLAlchemyError:
        raise RuntimeError("The local database could not be initialized.") from None


def get_db(request: Request) -> Iterator[Session]:
    session = request.app.state.database.session_factory()
    try:
        yield session
    finally:
        session.close()
