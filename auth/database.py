# auth/database.py
from typing import Generator
from sqlmodel import SQLModel, Session

from app.db import engine  # <- single source of truth

# IMPORTANT: ensure models are imported so SQLModel registers tables
from auth.models import User  # noqa: F401
from models.profile import UserProfile  # noqa: F401
from models.review import Review  # noqa: F401
from models.review_invite import ReviewInvite  # noqa: F401
from models.review_verification import ReviewVerification  # noqa: F401
from models.qualification import Qualification  # noqa: F401
from models.booking_request import BookingRequest  # noqa: F401
from models.booking import Booking  # noqa: F401
# add other SQLModel tables you have (JobPost, Company, etc) as noqa imports too

def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session

def init_db() -> None:
    print("INIT_DB tables:", sorted(SQLModel.metadata.tables.keys()))
    SQLModel.metadata.create_all(engine)