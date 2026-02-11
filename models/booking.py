# models/booking.py

from typing import Optional
from datetime import datetime, date

from sqlmodel import SQLModel, Field


class Booking(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    jobpost_id: int = Field(foreign_key="jobpost.id", index=True, nullable=False)
    talent_id: int = Field(foreign_key="talent.id", index=True, nullable=False)

    status: str = Field(default="pending", index=True)  # pending / confirmed / cancelled

    start_date: Optional[date] = None
    end_date: Optional[date] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)


class BookingCreate(SQLModel):
    jobpost_id: int
    talent_id: int
    start_date: Optional[date] = None
    end_date: Optional[date] = None
