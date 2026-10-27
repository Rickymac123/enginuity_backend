# app/routers/availability.py

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from models.talent import Talent
from models.booking import Booking
from typing import List, Optional

from dateutil.parser import isoparse
from dateutil.rrule import rrulestr
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from app.db import get_session
from auth.deps import require_role
from auth.models import User
from models.availability import (
    Availability,
    AvailabilityCreate,
    AvailabilityRead,
    AvailabilityUpdate,
)

router = APIRouter(tags=["availability"])

ALLOWED_STATUS = {"busy", "available"}
RECURRENCE_LOOKAHEAD_DAYS = 365


# -------------------------------------------------
# Helpers
# -------------------------------------------------
def _validate_block(start_at: datetime, end_at: datetime, status: str) -> None:
    if start_at is None or end_at is None:
        raise HTTPException(status_code=400, detail="start_at and end_at are required")
    if _aware(end_at) <= _aware(start_at):
        raise HTTPException(status_code=400, detail="end_at must be after start_at")
    if status not in ALLOWED_STATUS:
        raise HTTPException(
            status_code=400,
            detail=f"status must be one of {sorted(ALLOWED_STATUS)}",
        )


def _aware(value: datetime, zone: str = "Europe/London") -> datetime:
    try: tz = ZoneInfo(zone or "Europe/London")
    except ZoneInfoNotFoundError:
        raise HTTPException(status_code=400, detail="Invalid timezone")
    return (value.replace(tzinfo=tz) if value.tzinfo is None else value).astimezone(timezone.utc)


def _blocks_overlap(a_start, a_end, b_start, b_end):
    return _aware(a_start) < _aware(b_end) and _aware(a_end) > _aware(b_start)


def _generate_occurrences(block, window_start, window_end):
    zone = block.timezone or "Europe/London"
    begin, finish = _aware(window_start), _aware(window_end)
    start, end = _aware(block.start_at, zone), _aware(block.end_at, zone)
    if finish <= begin or finish - begin > timedelta(days=367):
        raise HTTPException(status_code=400, detail="Calendar window must be between 0 and 367 days")
    if not block.rrule:
        if start < finish and end > begin: yield start, end
        return
    # Keep recurring wall-clock times stable through daylight-saving changes.
    local_start = start.astimezone(ZoneInfo(zone))
    local_end = end.astimezone(ZoneInfo(zone))
    duration = local_end.replace(tzinfo=None) - local_start.replace(tzinfo=None)
    if duration <= timedelta(0):
        raise HTTPException(status_code=400, detail="Invalid recurrence duration")
    rule_text = block.rrule.removeprefix("RRULE:")
    parts = dict(part.split("=", 1) for part in rule_text.split(";") if "=" in part)
    if parts.get("FREQ") not in {"DAILY", "WEEKLY", "MONTHLY", "YEARLY"}:
        raise HTTPException(status_code=400, detail="Use daily, weekly, monthly or yearly recurrence")
    if any(key in parts for key in {"BYSECOND", "BYMINUTE", "BYHOUR"}):
        raise HTTPException(status_code=400, detail="Intraday recurrence is not supported")
    try:
        if int(parts.get("INTERVAL", "1")) < 1: raise ValueError()
        rule = rrulestr(rule_text, dtstart=local_start)
        excluded = {_aware(isoparse(item.strip()), zone) for item in (block.exdates or "").split(",") if item.strip()}
        for count, occurrence in enumerate(rule.xafter(begin - duration, inc=True)):
            if count > 1000: raise ValueError()
            occ_start = _aware(occurrence)
            if occ_start >= finish: break
            occ_end = _aware(occurrence + duration)
            if occ_start not in excluded and occ_end > begin:
                yield occ_start, occ_end
    except (ValueError, TypeError, OverflowError):
        raise HTTPException(status_code=400, detail="Invalid or excessive recurrence")


def _lock_calendar(session, user_id):
    session.exec(select(Talent).where(Talent.user_id == user_id).with_for_update()).first()


def _validate_schedule(session, block, exclude_id=None):
    _validate_block(block.start_at, block.end_at, block.status)
    begin = _aware(block.start_at, block.timezone or "Europe/London")
    # Validate the rule before saving, and check its next year against existing commitments.
    occurrences = list(_generate_occurrences(block, begin, begin + timedelta(days=366)))
    for start, end in occurrences:
        if _conflict_exists(session, block.user_id, start, end, exclude_id=exclude_id):
            raise HTTPException(status_code=409, detail="Overlaps with an existing commitment")
        talent = session.exec(select(Talent).where(Talent.user_id == block.user_id)).first()
        if talent:
            for booking in session.exec(select(Booking).where(Booking.talent_id == talent.id, Booking.status != "cancelled")).all():
                day = booking.start_date
                while day <= booking.end_date:
                    if _blocks_overlap(start, end, datetime.combine(day, booking.start_time), datetime.combine(day, booking.end_time)):
                        raise HTTPException(status_code=409, detail="Overlaps with a confirmed booking")
                    day += timedelta(days=1)


def _conflict_exists(
    session: Session,
    user_id: int,
    new_start: datetime,
    new_end: datetime,
    *,
    exclude_id: Optional[int] = None,
) -> bool:
    window_end = new_end

    stmt = select(Availability).where(
        Availability.user_id == user_id,
        Availability.status == "busy",
    )
    blocks = session.exec(stmt).all()

    for block in blocks:
        if exclude_id and block.id == exclude_id:
            continue

        for occ_start, occ_end in _generate_occurrences(block, new_start, window_end):
            if _blocks_overlap(occ_start, occ_end, new_start, new_end):
                return True

    return False


# -------------------------------------------------
# Routes
# -------------------------------------------------

@router.get("/professional/availability", response_model=List[AvailabilityRead])
def list_my_availability(
    user: User = Depends(require_role("professional")),
    session: Session = Depends(get_session),
    start: Optional[datetime] = Query(default=None),
    end: Optional[datetime] = Query(default=None),
):
    """
    If start & end provided:
        return expanded occurrences within that range
    Else:
        return raw stored blocks
    """

    stmt = select(Availability).where(Availability.user_id == user.id)
    blocks = session.exec(stmt).all()

    if not start or not end:
        return blocks

    expanded: List[AvailabilityRead] = []

    for block in blocks:
        for occ_start, occ_end in _generate_occurrences(block, start, end):
            expanded.append(
                AvailabilityRead(
                    id=block.id,
                    user_id=block.user_id,
                    start_at=occ_start,
                    end_at=occ_end,
                    status=block.status,
                    title=block.title,
                    notes=block.notes,
                    timezone=block.timezone,
                    series_id=block.series_id,
                    rrule=block.rrule,
                    exdates=block.exdates,
                    created_at=block.created_at,
                    updated_at=block.updated_at,
                )
            )

    return sorted(expanded, key=lambda x: x.start_at)


# NEW ENDPOINT — Explicit occurrence expansion
@router.get("/professional/availability/occurrences")
def list_occurrences(
    user: User = Depends(require_role("professional")),
    session: Session = Depends(get_session),
    start: datetime = Query(..., description="Window start (UTC ISO)"),
    end: datetime = Query(..., description="Window end (UTC ISO)"),
):
    if _aware(end) <= _aware(start):
        raise HTTPException(status_code=400, detail="end must be after start")

    blocks = session.exec(
        select(Availability).where(Availability.user_id == user.id)
    ).all()

    results = []

    for block in blocks:
        for occ_start, occ_end in _generate_occurrences(block, start, end):
            results.append(
                {
                    "id": block.id,
                    "start_at": occ_start,
                    "end_at": occ_end,
                    "status": block.status,
                    "title": block.title,
                    "notes": block.notes,
                    "series_id": block.series_id,
                }
            )

    results.sort(key=lambda x: x["start_at"])
    return results


@router.post("/professional/availability", response_model=AvailabilityRead)
def create_availability(
    availability_in: AvailabilityCreate,
    user: User = Depends(require_role("professional")),
    session: Session = Depends(get_session),
):
    _lock_calendar(session, user.id)
    _validate_block(availability_in.start_at, availability_in.end_at, availability_in.status)

    if availability_in.status == "busy":
        if _conflict_exists(session, user.id, availability_in.start_at, availability_in.end_at):
            raise HTTPException(status_code=409, detail="Overlaps with existing busy block")

    block = Availability(
        user_id=user.id,
        start_at=availability_in.start_at,
        end_at=availability_in.end_at,
        status=availability_in.status,
        title=availability_in.title,
        notes=availability_in.notes,
        timezone=availability_in.timezone,
        series_id=availability_in.series_id,
        rrule=availability_in.rrule,
        exdates=availability_in.exdates,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )

    _validate_schedule(session, block, exclude_id=block.id)
    session.add(block)
    session.commit()
    session.refresh(block)
    return block


@router.patch("/professional/availability/{block_id}", response_model=AvailabilityRead)
def update_availability(
    block_id: int,
    availability_in: AvailabilityUpdate,
    user: User = Depends(require_role("professional")),
    session: Session = Depends(get_session),
):
    _lock_calendar(session, user.id)
    block = session.get(Availability, block_id)
    if not block or block.user_id != user.id:
        raise HTTPException(status_code=404, detail="Availability block not found")

    data = availability_in.model_dump(exclude_unset=True)

    new_start = data.get("start_at", block.start_at)
    new_end = data.get("end_at", block.end_at)
    new_status = data.get("status", block.status)

    _validate_block(new_start, new_end, getattr(new_status, "value", new_status))

    if getattr(new_status, "value", new_status) == "busy":
        if _conflict_exists(session, user.id, new_start, new_end, exclude_id=block.id):
            raise HTTPException(status_code=409, detail="Overlaps with existing busy block")

    for key, value in data.items():
        setattr(block, key, value)

    block.updated_at = datetime.utcnow()

    _validate_schedule(session, block, exclude_id=block.id)
    session.add(block)
    session.commit()
    session.refresh(block)
    return block


@router.delete("/professional/availability/{block_id}", status_code=204)
def delete_availability(
    block_id: int,
    user: User = Depends(require_role("professional")),
    session: Session = Depends(get_session),
):
    _lock_calendar(session, user.id)
    block = session.get(Availability, block_id)
    if not block or block.user_id != user.id:
        raise HTTPException(status_code=404, detail="Availability block not found")

    session.delete(block)
    session.commit()