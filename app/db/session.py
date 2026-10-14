"""Engine and session factory."""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


def make_engine(url: str) -> Engine:
    # Pin the session time zone so timestamps come back in UTC on every machine, and give
    # up after 5 seconds if the database is down instead of waiting silently.
    return create_engine(
        url,
        pool_pre_ping=True,
        connect_args={"options": "-c timezone=UTC", "connect_timeout": 5},
    )


def check_database(url: str) -> None:
    """Exit with a clear message if the database cannot be reached."""
    engine = make_engine(url)
    try:
        with engine.connect():
            pass
    except OperationalError:
        host = engine.url.render_as_string(hide_password=True)
        raise SystemExit(
            f"Cannot connect to the database at {host}.\n"
            "Start it first: `docker compose up -d db` (or start your local PostgreSQL)."
        ) from None
    finally:
        engine.dispose()


@lru_cache
def get_engine() -> Engine:
    return make_engine(get_settings().database_url)


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed afterwards."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
