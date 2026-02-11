from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select, and_

from app.db import get_session
from auth.deps import require_role
from auth.models import User
from models.availability import (
    AvailabilityBlock,
    AvailabilityCreate,
    AvailabilityRead,
    AvailabilityUpdate,
)

router = APIRouter(tags=["availability"])

ALLOWED_STATUS = {"busy", "available"}


def _validate_block(start_at: datetime, end_at: datetime, status: str) -> None:
    if not start_at or not end_at:
        raise HTTPException(status_code=400, detail="start_at and end_at are required")
    if end_at <= start_at:
        raise HTTPException(status_code=400, detail="end_at must be after start_at")
    if status not in ALLOWED_STATUS:
        raise HTTPException(status_code=400, detail=f"status must be one of {sorted(ALLOWED_STATUS)}")


def _overlaps_exist(
    session: Session,
    user_id: int,
    start_at: datetime,
    end_at: datetime,
    *,
    exclude_id: Optional[int] = None,
) -> bool:
    # Overlap condition: existing.start < new_end AND existing.end > new_start
    stmt = (
        select(AvailabilityBlock)
        .where(
            AvailabilityBlock.user_id == user_id,
            AvailabilityBlock.status == "busy",
            AvailabilityBlock.start_at < end_at,
            AvailabilityBlock.end_at > start_at,
        )
    )
    if exclude_id is not None:
        stmt = stmt.where(AvailabilityBlock.id != exclude_id)

    return session.exec(stmt).first() is not None


@router.get("/professional/availability", response_model=List[AvailabilityRead])
def list_my_availability(
    user: User = Depends(require_role("professional")),
    session: Session = Depends(get_session),
    start: Optional[datetime] = Query(default=None, description="Filter: start_at >= start (UTC)"),
    end: Optional[datetime] = Query(default=None, description="Filter: start_at < end (UTC)"),
):
    stmt = select(AvailabilityBlock).where(AvailabilityBlock.user_id == user.id)

    if start is not None:
        stmt = stmt.where(AvailabilityBlock.start_at >= start)
    if end is not None:
        stmt = stmt.where(AvailabilityBlock.start_at < end)

    stmt = stmt.order_by(AvailabilityBlock.start_at)
    return session.exec(stmt).all()


@router.post("/professional/availability", response_model=AvailabilityRead)
def create_availability(
    availability_in: AvailabilityCreate,
    user: User = Depends(require_role("professional")),
    session: Session = Depends(get_session),
):
    _validate_block(availability_in.start_at, availability_in.end_at, availability_in.status)

    # Basic overlap protection for non-recurring blocks.
    # If rrule is present, we still prevent overlap for the base block (best-effort).
    if availability_in.status == "busy":
        if _overlaps_exist(session, user.id, availability_in.start_at, availability_in.end_at):
            raise HTTPException(status_code=409, detail="Overlaps with an existing busy block")

    block = AvailabilityBlock(
        user_id=user.id,
        start_at=availability_in.start_at,
        end_at=availability_in.end_at,
        status=availability_in.status,
        title=availability_in.title,
        notes=availability_in.notes,
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
    block = session.get(AvailabilityBlock, block_id)
    if not block or block.user_id != user.id:
        raise HTTPException(status_code=404, detail="Availability block not found")

    data = availability_in.model_dump(exclude_unset=True)

    new_start = data.get("start_at", block.start_at)
    new_end = data.get("end_at", block.end_at)
    new_status = data.get("status", block.status)

    _validate_block(new_start, new_end, new_status)

    # Overlap protection if resulting block is busy
    if new_status == "busy":
        if _overlaps_exist(session, user.id, new_start, new_end, exclude_id=block.id):
            raise HTTPException(status_code=409, detail="Overlaps with an existing busy block")

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
    block = session.get(AvailabilityBlock, block_id)
    if not block or block.user_id != user.id:
        raise HTTPException(status_code=404, detail="Availability block not found")

    session.delete(block)
    session.commit()