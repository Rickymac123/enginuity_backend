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


from datetime import datetime
from pydantic import BaseModel, Field, field_validator
from models.booking_request import BookingRequest
from app.notifications import enqueue


class CancellationInput(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator('reason')
    @classmethod
    def trim_reason(cls, value):
        if not value.strip():
            raise ValueError('Enter a cancellation reason')
        return value.strip()


@router.post('/bookings/by-request/{request_id}/cancel', response_model=Booking)
def cancel_confirmed_booking(request_id: int, payload: CancellationInput,
        user: User = Depends(current_user), session: Session = Depends(get_session)):
    # Use the same talent lock as acceptance to serialize changes to commitments.
    talent_id = select(Booking.talent_id).where(Booking.booking_request_id == request_id).scalar_subquery()
    talent = session.exec(select(Talent).where(Talent.id == talent_id).with_for_update()).first()
    booking = session.exec(select(Booking).where(Booking.booking_request_id == request_id).with_for_update()).first()
    allowed = booking and talent and (
        (user.role == 'company' and booking.company_id == user.id) or
        (user.role == 'professional' and talent.user_id == user.id and talent.agency_id is None) or
        (user.role == 'agency' and talent.agency_id == user.id and talent.user_id is None))
    if not allowed:
        raise HTTPException(status_code=404, detail='BOOKING_NOT_FOUND')
    if booking.status == 'cancelled':
        return booking
    if booking.status != 'confirmed':
        raise HTTPException(status_code=409, detail='BOOKING_NOT_CONFIRMED')
    req = session.get(BookingRequest, request_id)
    if not req or req.status != 'accepted':
        raise HTTPException(status_code=409, detail='BOOKING_REQUEST_STATE_CHANGED')
    now = datetime.utcnow()
    audit = f'Cancelled by {user.role} account #{user.id} at {now.isoformat()} UTC. Reason: {payload.reason}'
    booking.status = 'cancelled'
    booking.updated_at = now
    booking.notes = '\n\n'.join(filter(None, [booking.notes, audit]))
    req.status = 'cancelled'
    req.responded_at = now
    req.notes = '\n\n'.join(filter(None, [req.notes, audit]))
    recipient = (talent.user_id or talent.agency_id) if user.role == 'company' else booking.company_id
    role = ('professional' if talent.user_id else 'agency') if user.role == 'company' else 'company'
    enqueue(session, f'confirmed-booking-cancelled:{booking.id}', recipient,
        'ContractPros booking cancelled', 'A confirmed booking has been cancelled. Sign in to view the reason and details.',
        f'/dashboard/{role}/booking-requests')
    session.add(booking)
    session.add(req)
    session.commit()
    session.refresh(booking)
    return booking

from app.routers.booking_reviews import router as booking_reviews_router
router.include_router(booking_reviews_router)
