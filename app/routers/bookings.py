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
    raise HTTPException(status_code=410, detail="Use booking requests; professionals must accept before a booking is confirmed")


@router.get("/bookings/", response_model=List[Booking])
def list_bookings(
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    if user.role == "company":
        return session.exec(select(Booking).where(Booking.company_id == user.id)).all()
    if user.role == "professional":
        talent_ids = session.exec(select(Talent.id).where(Talent.user_id == user.id)).all()
    elif user.role == "agency":
        talent_ids = session.exec(select(Talent.id).where(Talent.agency_id == user.id)).all()
    else:
        raise HTTPException(status_code=403, detail="NOT_ALLOWED")
    return session.exec(select(Booking).where(Booking.talent_id.in_(talent_ids))).all() if talent_ids else []
