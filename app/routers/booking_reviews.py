"""Company completion and reviews for actual platform bookings."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlmodel import Session, select
from app.db import get_session
from app.notifications import enqueue
from auth.deps import current_user
from auth.models import User
from models.booking import Booking
from models.booking_request import BookingRequest
from models.talent import Talent
from models.review import Review

router = APIRouter()


def owned(session, user, request_id):
    booking = session.exec(select(Booking).where(Booking.booking_request_id == request_id).with_for_update()).first()
    if not booking or user.role != 'company' or booking.company_id != user.id:
        raise HTTPException(404, 'BOOKING_NOT_FOUND')
    return booking


def has_ended(booking):
    end = datetime.combine(booking.end_date, booking.end_time, tzinfo=ZoneInfo('Europe/London'))
    return datetime.now(timezone.utc) >= end.astimezone(timezone.utc)


def review_for(session, booking):
    return session.exec(select(Review).where(Review.booking_id == booking.id)).first()


def details(session, booking):
    talent = session.get(Talent, booking.talent_id)
    review = review_for(session, booking)
    return {'status': booking.status, 'can_complete': booking.status == 'confirmed' and has_ended(booking),
            'review_available': bool(talent and talent.user_id), 'reviewed': bool(review),
            'site_name': booking.site_name, 'end_date': str(booking.end_date),
            'rating': review.rating if review else None}


@router.get('/bookings/by-request/{request_id}/review')
def get_review(request_id: int, user: User = Depends(current_user), session: Session = Depends(get_session)):
    return details(session, owned(session, user, request_id))


@router.post('/bookings/by-request/{request_id}/complete')
def complete(request_id: int, user: User = Depends(current_user), session: Session = Depends(get_session)):
    booking = owned(session, user, request_id)
    if booking.status == 'completed':
        return details(session, booking)
    if booking.status != 'confirmed':
        raise HTTPException(409, 'Only confirmed bookings can be completed.')
    if not has_ended(booking):
        raise HTTPException(409, 'The booking has not ended yet (Europe/London time).')
    request = session.get(BookingRequest, request_id)
    if not request or request.status != 'accepted':
        raise HTTPException(409, 'Booking request state changed. Refresh and try again.')
    now = datetime.utcnow()
    booking.status = 'completed'
    booking.updated_at = now
    booking.notes = '\n\n'.join(filter(None, [booking.notes, f'Completed by company account #{user.id} at {now.isoformat()} UTC.']))
    request.status = 'completed'
    request.responded_at = now
    talent = session.get(Talent, booking.talent_id)
    if talent and talent.user_id:
        enqueue(session, f'booking-review-invite:{booking.id}', user.id,
                'How did your ContractPros booking go?',
                'Your booking is marked completed. Share an honest review of the professional you worked with.',
                f'/dashboard/company/booking-requests/{request_id}/review')
    if talent and (talent.user_id or talent.agency_id):
        role = 'professional' if talent.user_id else 'agency'
        enqueue(session, f'booking-completed:{booking.id}', talent.user_id or talent.agency_id,
                'ContractPros booking completed', 'The client marked your booking completed. Sign in to view the details.',
                f'/dashboard/{role}/booking-requests')
    session.add(booking); session.add(request); session.commit()
    return details(session, booking)


class ReviewInput(BaseModel):
    rating: int = Field(ge=1, le=5, strict=True)
    comment: str = Field(min_length=50, max_length=3000)

    @field_validator('comment')
    @classmethod
    def trim_comment(cls, value):
        value = value.strip()
        if len(value) < 50:
            raise ValueError('Please write at least 50 characters about the work.')
        return value


@router.post('/bookings/by-request/{request_id}/review', status_code=201)
def submit_review(request_id: int, payload: ReviewInput, user: User = Depends(current_user), session: Session = Depends(get_session)):
    booking = owned(session, user, request_id)
    if booking.status != 'completed':
        raise HTTPException(409, 'Complete the booking before leaving a review.')
    if review_for(session, booking):
        raise HTTPException(409, 'A review has already been submitted for this booking.')
    talent = session.get(Talent, booking.talent_id)
    if not talent or not talent.user_id:
        raise HTTPException(409, 'Reviews are currently available for individual professional accounts only.')
    review = Review(booking_id=booking.id, professional_id=talent.user_id, company_id=user.id,
        rating=payload.rating, comment=payload.comment,
        reviewer_name=(' '.join(filter(None, [user.first_name, user.last_name])).strip() or 'Client'),
        reviewer_email=user.email, reviewer_company=user.company_name,
        source='platform', status='verified', verified_at=datetime.utcnow(), is_public=True)
    session.add(review)
    enqueue(session, f'booking-reviewed:{booking.id}', talent.user_id,
            'You received a ContractPros review', 'A client has reviewed a completed booking. Sign in to read their feedback.',
            '/dashboard/professional/preview')
    session.commit()
    return {'reviewed': True}
