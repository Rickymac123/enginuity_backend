from datetime import datetime
from typing import Optional

from sqlmodel import SQLModel, Field


# -------------------------------------------------
# Base (shared fields)
# -------------------------------------------------
class AvailabilityBlockBase(SQLModel):
    """
    Represents a block of time where the engineer is NOT available.
    Think calendar events, not day flags.
    """

    # UTC datetimes (frontend can convert from/to local time)
    start_at: datetime = Field(index=True)
    end_at: datetime = Field(index=True)

    # busy | available (default to busy; available can be used later as override)
    status: str = Field(default="busy", index=True)

    # Optional label / notes
    title: Optional[str] = None
    notes: Optional[str] = None

    # ---- Recurrence (optional) ----

    # Groups recurring blocks together
    series_id: Optional[str] = Field(default=None, index=True)

    # RFC5545 RRULE string
    # Example: "FREQ=WEEKLY;BYDAY=MO,TU;UNTIL=20260630T000000Z"
    rrule: Optional[str] = None

    # Excluded occurrences (ISO datetimes, comma-separated or JSON later)
    # Example: "2026-02-10T09:00:00Z,2026-02-17T09:00:00Z"
    exdates: Optional[str] = None


# -------------------------------------------------
# Table
# -------------------------------------------------
class AvailabilityBlock(AvailabilityBlockBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    # Owner (professional user)
    user_id: int = Field(index=True)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# -------------------------------------------------
# Schemas
# -------------------------------------------------
class AvailabilityCreate(AvailabilityBlockBase):
    pass


class AvailabilityRead(AvailabilityBlockBase):
    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime


class AvailabilityUpdate(SQLModel):
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    status: Optional[str] = None
    title: Optional[str] = None
    notes: Optional[str] = None

    series_id: Optional[str] = None
    rrule: Optional[str] = None
    exdates: Optional[str] = None