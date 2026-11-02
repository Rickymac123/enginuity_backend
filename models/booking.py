from typing import Optional
from datetime import datetime, date, time

from sqlmodel import SQLModel, Field


class Booking(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    booking_request_id: int = Field(index=True, unique=True)

    company_id: int = Field(index=True, nullable=False)
    jobpost_id: Optional[int] = Field(default=None, foreign_key="jobpost.id", index=True)
    application_id: Optional[int] = Field(default=None, index=True)
    talent_id: int = Field(foreign_key="talent.id", index=True, nullable=False)

    status: str = Field(default="confirmed", index=True)  # confirmed / completed / cancelled

    start_date: date
    end_date: date
    start_time: time
    end_time: time

    site_name: str
    site_address: str
    contact_name: str
    contact_phone: str

    notes: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class BookingCreate(SQLModel):
    booking_request_id: int
    company_id: int
    talent_id: int
    jobpost_id: Optional[int] = None
    application_id: Optional[int] = None

    start_date: date
    end_date: date
    start_time: time
    end_time: time

    site_name: str
    site_address: str
    contact_name: str
    contact_phone: str

    notes: Optional[str] = None


class BookingRead(SQLModel):
    id: int
    booking_request_id: int
    company_id: int
    talent_id: int
    jobpost_id: Optional[int] = None
    application_id: Optional[int] = None

    status: str

    start_date: date
    end_date: date
    start_time: time
    end_time: time

    site_name: str
    site_address: str
    contact_name: str
    contact_phone: str

    notes: Optional[str] = None

    created_at: datetime
    updated_at: datetime