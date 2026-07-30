"""Database engine/session construction."""
from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def build_engine(url: str | None = None):
    url = url or os.getenv("DATABASE_URL", "sqlite:///./vidcar.db")
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    elif url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://") :]
    kwargs: dict = {"pool_pre_ping": True}
    if url in {"sqlite://", "sqlite:///:memory:"}:
        kwargs.update(
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    return create_engine(url, **kwargs)


def build_session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
