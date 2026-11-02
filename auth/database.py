# auth/database.py
from typing import Generator
from sqlmodel import SQLModel, Session

from app.db import engine, get_session  # Shared dependency: one session per request.

# IMPORTANT: ensure models are imported so SQLModel registers tables
from auth.models import User  # noqa: F401
from app.rate_limits import RequestWindow  # noqa: F401
from app.notifications import EmailNotification  # noqa: F401
from models.social_auth import SocialIdentity, SocialFlow, RegistrationEmail  # noqa: F401
from models.profile import UserProfile  # noqa: F401
from models.review import Review  # noqa: F401
from models.review_invite import ReviewInvite  # noqa: F401
from models.review_verification import ReviewVerification  # noqa: F401
from models.qualification import Qualification  # noqa: F401
from models.booking_request import BookingRequest  # noqa: F401
from models.booking import Booking  # noqa: F401
from models.jobpost import JobPost  # noqa: F401
# add other SQLModel tables you have (JobPost, Company, etc) as noqa imports too

def init_db() -> None:
    print("INIT_DB tables:", sorted(SQLModel.metadata.tables.keys()))
    SQLModel.metadata.create_all(engine)