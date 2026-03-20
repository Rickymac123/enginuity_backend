from typing import Optional
from datetime import datetime, date, time, timedelta

from sqlmodel import SQLModel, Field


class BookingRequest(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    company_id: int = Field(index=True, nullable=False)
    talent_id: int = Field(index=True, nullable=False)

    jobpost_id: Optional[int] = Field(default=None, foreign_key="jobpost.id", index=True)
    application_id: Optional[int] = Field(default=None, index=True)

    status: str = Field(default="pending", index=True)  # pending / accepted / declined / expired

    start_date: date
    end_date: date
    start_time: time
    end_time: time

    site_name: str
    site_address: str
    contact_name: str
    contact_phone: str

    notes: Optional[str] = None
    decline_reason: Optional[str] = None

    requested_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    expires_at: datetime = Field(
        default_factory=lambda: datetime.utcnow() + timedelta(days=3),
        index=True,
    )
    responded_at: Optional[datetime] = None


class BookingRequestCreate(SQLModel):
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


class BookingRequestRespond(SQLModel):
    decline_reason: Optional[str] = None


class BookingRequestRead(SQLModel):
    id: int
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
    decline_reason: Optional[str] = None

    requested_at: datetime
    expires_at: datetime
    responded_at: Optional[datetime] = None