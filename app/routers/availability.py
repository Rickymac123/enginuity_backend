# app/routers/availability.py

from __future__ import annotations

from datetime import datetime, timedelta
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
    if end_at <= start_at:
        raise HTTPException(status_code=400, detail="end_at must be after start_at")
    if status not in ALLOWED_STATUS:
        raise HTTPException(
            status_code=400,
            detail=f"status must be one of {sorted(ALLOWED_STATUS)}",
        )


def _blocks_overlap(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and a_end > b_start


def _parse_exdates(exdates: Optional[str]) -> set[datetime]:
    if not exdates:
        return set()

    out: set[datetime] = set()
    for raw in exdates.split(","):
        s = raw.strip()
        if not s:
            continue
        try:
            out.add(isoparse(s))
        except Exception:
            raise HTTPException(status_code=400, detail=f"Invalid exdates datetime: {s}")
    return out


def _generate_occurrences(block: Availability, window_start: datetime, window_end: datetime):
    duration = block.end_at - block.start_at

    # Non-recurring
    if not block.rrule:
        if _blocks_overlap(block.start_at, block.end_at, window_start, window_end):
            yield (block.start_at, block.end_at)
        return

    try:
        rule = rrulestr(block.rrule, dtstart=block.start_at)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid rrule")

    ex = _parse_exdates(block.exdates)

    for dt in rule.between(window_start, window_end, inc=True):
        if dt in ex:
            continue
        yield (dt, dt + duration)


def _conflict_exists(
    session: Session,
    user_id: int,
    new_start: datetime,
    new_end: datetime,
    *,
    exclude_id: Optional[int] = None,
) -> bool:
    window_end = max(new_end, datetime.utcnow()) + timedelta(days=RECURRENCE_LOOKAHEAD_DAYS)

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
    if end <= start:
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
    block = session.get(Availability, block_id)
    if not block or block.user_id != user.id:
        raise HTTPException(status_code=404, detail="Availability block not found")

    data = availability_in.model_dump(exclude_unset=True)

    new_start = data.get("start_at", block.start_at)
    new_end = data.get("end_at", block.end_at)
    new_status = data.get("status", block.status)

    _validate_block(new_start, new_end, str(new_status))

    if str(new_status) == "busy":
        if _conflict_exists(session, user.id, new_start, new_end, exclude_id=block.id):
            raise HTTPException(status_code=409, detail="Overlaps with existing busy block")

    for key, value in data.items():
        setattr(block, key, value)

    block.updated_at = datetime.utcnow()

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
    block = session.get(Availability, block_id)
    if not block or block.user_id != user.id:
        raise HTTPException(status_code=404, detail="Availability block not found")

    session.delete(block)
    session.commit()