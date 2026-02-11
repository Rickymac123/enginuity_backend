# auth/database.py

from models.profile import UserProfile  # noqa: F401

from typing import Generator

from sqlmodel import SQLModel, Session, create_engine

DATABASE_URL = "sqlite:///./database.db"

engine = create_engine(
    DATABASE_URL,
    echo=True,
)


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a sync SQLModel Session."""
    with Session(engine) as session:
        yield session


def init_db() -> None:
    """Create all tables."""
    SQLModel.metadata.create_all(engine)
