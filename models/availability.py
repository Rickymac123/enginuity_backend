# models/availability.py

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional, Literal

from sqlmodel import SQLModel, Field, Index


class AvailabilityStatus(str, Enum):
    busy = "busy"
    available = "available"


# -------------------------------------------------
# Base (shared fields)
# -------------------------------------------------
class AvailabilityBase(SQLModel):
    """
    Calendar-style availability blocks for a professional.

    Store datetimes in UTC (recommended). If you want to track the user's
    intended timezone for display/recurrence expansion, use timezone.
    """

    # UTC datetimes
    start_at: datetime = Field(index=True)
    end_at: datetime = Field(index=True)

    # busy | available
    status: AvailabilityStatus = Field(default=AvailabilityStatus.busy, index=True)

    # Optional label / notes
    title: Optional[str] = None
    notes: Optional[str] = None

    # Optional IANA timezone (e.g. "Europe/London") for UI/recurrence expansion
    timezone: Optional[str] = Field(default=None, index=True)

    # ---- Recurrence (optional) ----

    # Groups recurring blocks together
    series_id: Optional[str] = Field(default=None, index=True)

    # RFC5545 RRULE string
    # Example: "FREQ=WEEKLY;BYDAY=MO,TU;UNTIL=20260630T000000Z"
    rrule: Optional[str] = None

    # Excluded occurrences (keep as string for now; can move to JSON later)
    # Example: "2026-02-10T09:00:00Z,2026-02-17T09:00:00Z"
    exdates: Optional[str] = None


# -------------------------------------------------
# Table
# -------------------------------------------------
class Availability(AvailabilityBase, table=True):
    __tablename__ = "availability"
    __table_args__ = (
        Index("ix_availability_user_start", "user_id", "start_at"),
        Index("ix_availability_user_end", "user_id", "end_at"),
        Index("ix_availability_user_status", "user_id", "status"),
        Index("ix_availability_user_series", "user_id", "series_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)

    # Owner (professional user)
    user_id: int = Field(index=True)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# -------------------------------------------------
# Schemas
# -------------------------------------------------
class AvailabilityCreate(AvailabilityBase):
    pass


class AvailabilityRead(AvailabilityBase):
    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime


class AvailabilityUpdate(SQLModel):
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    status: Optional[AvailabilityStatus] = None

    title: Optional[str] = None
    notes: Optional[str] = None
    timezone: Optional[str] = None

    series_id: Optional[str] = None
    rrule: Optional[str] = None
    exdates: Optional[str] = None