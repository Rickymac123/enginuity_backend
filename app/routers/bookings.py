from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db import get_session
from auth.deps import current_user
from auth.models import User

from models.booking import Booking, BookingCreate
from models.jobpost import JobPost
from models.talent import Talent

router = APIRouter(tags=["bookings"])


@router.post("/bookings/", response_model=Booking)
def create_booking(
    booking_in: BookingCreate,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    job = session.get(JobPost, booking_in.jobpost_id)
    if not job or job.company_id != user.id:
        raise HTTPException(status_code=404, detail="Job not found or not yours")

    talent = session.get(Talent, booking_in.talent_id)
    if not talent:
        raise HTTPException(status_code=404, detail="Talent not found")

    booking = Booking(
        jobpost_id=booking_in.jobpost_id,
        talent_id=booking_in.talent_id,
        start_date=booking_in.start_date,
        end_date=booking_in.end_date,
    )

    session.add(booking)
    session.commit()
    session.refresh(booking)
    return booking


@router.get("/bookings/", response_model=List[Booking])
def list_bookings(
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    job_ids = session.exec(select(JobPost.id).where(JobPost.company_id == user.id)).all()
    if not job_ids:
        return []
    statement = select(Booking).where(Booking.jobpost_id.in_(job_ids))
    return session.exec(statement).all()