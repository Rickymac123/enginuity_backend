# auth/database.py

import os
from typing import Generator

from sqlmodel import SQLModel, Session, create_engine

from models.profile import UserProfile  # noqa: F401


def _get_database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        return "sqlite:///./database.db"

    # SQLAlchemy expects postgresql:// not postgres://
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)

    return url


DATABASE_URL = _get_database_url()

engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session


def init_db() -> None:
    SQLModel.metadata.create_all(engine)