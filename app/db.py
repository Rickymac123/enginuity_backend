import os
from sqlmodel import create_engine, Session

DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    # Render / production (Postgres)
    engine = create_engine(DATABASE_URL, echo=False)
else:
    # Local development (SQLite)
    sqlite_file_name = "database.db"
    sqlite_url = f"sqlite:///{sqlite_file_name}"
    engine = create_engine(
        sqlite_url,
        echo=True,
        connect_args={"check_same_thread": False},
    )


def get_session():
    with Session(engine) as session:
        yield session