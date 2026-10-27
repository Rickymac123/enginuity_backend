"""Shared database limits for public authentication and review endpoints."""
import hashlib
import time
from sqlmodel import SQLModel, Field
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert


class RequestWindow(SQLModel, table=True):
    key: str = Field(primary_key=True)
    window: int = Field(index=True)
    count: int = 0


def consume(session, identifier: str, maximum: int, seconds=300) -> bool:
    window = int(time.time()) // seconds
    key = hashlib.sha256(f'{window}:{identifier}'.encode()).hexdigest()
    insert = pg_insert if session.bind.dialect.name == 'postgresql' else sqlite_insert
    statement = insert(RequestWindow).values(key=key, window=window, count=1)
    statement = statement.on_conflict_do_update(index_elements=['key'],
        set_={'count': RequestWindow.count + 1}, where=RequestWindow.count < maximum).returning(RequestWindow.count)
    result = session.execute(statement).first()
    session.execute(delete(RequestWindow).where(RequestWindow.window < window - 2))
    session.commit()
    return result is not None
