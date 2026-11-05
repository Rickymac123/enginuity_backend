from app.billing import require_subscription
from datetime import datetime, timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db import get_session
from app.notifications import enqueue
from auth.deps import require_role
from auth.models import User

from models.booking_request import (
    BookingRequest,
    BookingRequestCreate,
    BookingRequestRead,
    BookingRequestRespond,
)
from models.booking import Booking
from models.jobpost import JobPost
from models.talent import Talent
from models.application import TalentApplication

router = APIRouter(tags=["booking_requests"])


def _is_expired(req: BookingRequest) -> bool:
    return datetime.utcnow() > req.expires_at


@router.post("/company/booking-requests", response_model=BookingRequestRead)
def create_booking_request(
    payload: BookingRequestCreate,
    user: User = Depends(require_role("company")),
    session: Session = Depends(get_session),
    subscription_access = Depends(require_subscription),
):
    if payload.end_date < payload.start_date or (payload.end_date - payload.start_date).days > 366 or payload.end_time <= payload.start_time:
        raise HTTPException(status_code=422, detail="INVALID_BOOKING_DATES_OR_TIMES")
    talent = session.exec(select(Talent).where(Talent.id == payload.talent_id).with_for_update()).first()
    if not talent:
        raise HTTPException(status_code=404, detail="TALENT_NOT_FOUND")

    if payload.jobpost_id is not None:
        job = session.get(JobPost, payload.jobpost_id)
        if not job or getattr(job, "company_id", None) != user.id:
            raise HTTPException(status_code=403, detail="NOT_ALLOWED_FOR_JOB")

    if payload.jobpost_id is not None and job.is_archived:
        raise HTTPException(status_code=409, detail="JOB_CLOSED")

    if payload.application_id is not None:
        application = session.get(TalentApplication, payload.application_id)
        if not application:
            raise HTTPException(status_code=404, detail="APPLICATION_NOT_FOUND")

        if application.status in {"withdrawn", "rejected"}:
            raise HTTPException(status_code=409, detail="APPLICATION_NO_LONGER_ACTIVE")

        job = session.get(JobPost, application.jobpost_id)
        if not job or getattr(job, "company_id", None) != user.id:
            raise HTTPException(status_code=403, detail="NOT_ALLOWED_FOR_APPLICATION")

        if job.is_archived:
            raise HTTPException(status_code=409, detail="JOB_CLOSED")
        if application.talent_id != payload.talent_id:
            raise HTTPException(status_code=400, detail="APPLICATION_TALENT_MISMATCH")

    if payload.application_id is not None and payload.jobpost_id is not None and application.jobpost_id != payload.jobpost_id:
        raise HTTPException(status_code=400, detail="APPLICATION_JOB_MISMATCH")

    existing_pending = session.exec(
        select(BookingRequest).where(
            BookingRequest.company_id == user.id,
            BookingRequest.talent_id == payload.talent_id,
            BookingRequest.status == "pending",
        )
    ).all()

    updated = False
    for existing in existing_pending:
        if _is_expired(existing):
            existing.status = "expired"
            session.add(existing)
            updated = True

    if updated:
        session.flush()

    still_pending = session.exec(
        select(BookingRequest).where(
            BookingRequest.company_id == user.id,
            BookingRequest.talent_id == payload.talent_id,
            BookingRequest.status == "pending",
        )
    ).first()

    if still_pending:
        raise HTTPException(status_code=400, detail="PENDING_BOOKING_REQUEST_ALREADY_EXISTS")

    req = BookingRequest(
        company_id=user.id,
        talent_id=payload.talent_id,
        jobpost_id=application.jobpost_id if payload.application_id is not None else payload.jobpost_id,
        application_id=payload.application_id,
        start_date=payload.start_date,
        end_date=payload.end_date,
        start_time=payload.start_time,
        end_time=payload.end_time,
        site_name=payload.site_name.strip(),
        site_address=payload.site_address.strip(),
        contact_name=payload.contact_name.strip(),
        contact_phone=payload.contact_phone.strip(),
        notes=payload.notes.strip() if payload.notes else None,
    )

    session.add(req)
    session.flush()
    enqueue(session, f"booking-request:{req.id}", talent.user_id or talent.agency_id, "New ContractPros booking request",
        "You have a new booking request. Sign in to review the details and respond.", f"/dashboard/{'professional' if talent.user_id else 'agency'}/booking-requests")
    session.commit()
    session.refresh(req)
    return req


@router.get("/company/booking-requests", response_model=List[BookingRequestRead])
def get_company_booking_requests(
    user: User = Depends(require_role("company")),
    session: Session = Depends(get_session),
):
    requests = session.exec(
        select(BookingRequest)
        .where(BookingRequest.company_id == user.id)
        .order_by(BookingRequest.requested_at.desc())
    ).all()

    updated = False
    for req in requests:
        if req.status == "pending" and _is_expired(req):
            req.status = "expired"
            session.add(req)
            updated = True

    if updated:
        session.commit()
        requests = session.exec(
            select(BookingRequest)
            .where(BookingRequest.company_id == user.id)
            .order_by(BookingRequest.requested_at.desc())
        ).all()

    return requests


@router.get("/agency/booking-requests", response_model=List[BookingRequestRead])
@router.get("/professional/booking-requests", response_model=List[BookingRequestRead])
def get_my_booking_requests(
    user: User = Depends(require_role("professional", "agency")),
    session: Session = Depends(get_session),
):
    ownership = (Talent.agency_id == user.id) & (Talent.user_id == None) if user.role == "agency" else (Talent.user_id == user.id) & (Talent.agency_id == None)  # noqa: E711
    talent_ids = session.exec(select(Talent.id).where(ownership)).all()

    if not talent_ids:
        return []

    requests = session.exec(
        select(BookingRequest)
        .where(BookingRequest.talent_id.in_(talent_ids))
        .order_by(BookingRequest.requested_at.desc())
    ).all()

    updated = False
    for req in requests:
        if req.status == "pending" and _is_expired(req):
            req.status = "expired"
            session.add(req)
            updated = True

    if updated:
        session.commit()
        requests = session.exec(
            select(BookingRequest)
            .where(BookingRequest.talent_id.in_(talent_ids))
            .order_by(BookingRequest.requested_at.desc())
        ).all()

    return requests


@router.post("/agency/booking-requests/{request_id}/accept", response_model=BookingRequestRead)
@router.post("/professional/booking-requests/{request_id}/accept", response_model=BookingRequestRead)
def accept_booking_request(
    request_id: int,
    user: User = Depends(require_role("professional", "agency")),
    session: Session = Depends(get_session),
):
    ownership = (Talent.agency_id == user.id) & (Talent.user_id == None) if user.role == "agency" else (Talent.user_id == user.id) & (Talent.agency_id == None)  # noqa: E711
    requested_talent = select(BookingRequest.talent_id).where(BookingRequest.id == request_id).scalar_subquery()
    talent = session.exec(select(Talent).where(ownership, Talent.id == requested_talent).with_for_update()).first()

    if not talent:
        raise HTTPException(status_code=404, detail="TALENT_PROFILE_NOT_FOUND")

    req = session.get(BookingRequest, request_id)
    if not req or req.talent_id != talent.id:
        raise HTTPException(status_code=404, detail="BOOKING_REQUEST_NOT_FOUND")

    if req.status != "pending":
        raise HTTPException(status_code=400, detail="BOOKING_REQUEST_NOT_PENDING")

    if _is_expired(req):
        req.status = "expired"
        session.add(req)
        session.commit()
        raise HTTPException(status_code=400, detail="BOOKING_REQUEST_EXPIRED")

    from app.routers.talent import require_representation
    require_representation(talent)

    application = None
    if req.application_id is not None:
        application = session.exec(select(TalentApplication).where(
            TalentApplication.id == req.application_id).with_for_update()).first()
        if not application or application.status in {"withdrawn", "rejected"}:
            raise HTTPException(status_code=409, detail="APPLICATION_NO_LONGER_ACTIVE")

    # Older application-based requests may not have copied the job reference.
    if application:
        if application.talent_id != req.talent_id:
            raise HTTPException(status_code=409, detail="APPLICATION_TALENT_MISMATCH")
        if req.jobpost_id is not None and req.jobpost_id != application.jobpost_id:
            raise HTTPException(status_code=409, detail="APPLICATION_JOB_MISMATCH")
        req.jobpost_id = application.jobpost_id

    conflict = session.exec(select(Booking).where(
        Booking.talent_id == talent.id,
        Booking.status != "cancelled",
        Booking.start_date <= req.end_date, Booking.end_date >= req.start_date,
        Booking.start_time < req.end_time, Booking.end_time > req.start_time,
    )).first()
    if conflict:
        raise HTTPException(status_code=409, detail="BOOKING_OVERLAP")

    from app.routers.availability import _conflict_exists
    day = req.start_date
    while day <= req.end_date:
        if talent.user_id and _conflict_exists(session, talent.user_id, datetime.combine(day, req.start_time), datetime.combine(day, req.end_time)):
            raise HTTPException(status_code=409, detail="BOOKING_CONFLICTS_WITH_AVAILABILITY")
        day += timedelta(days=1)

    req.status = "accepted"
    req.responded_at = datetime.utcnow()
    if application:
        application.status = "accepted"
        application.updated_at = req.responded_at
        session.add(application)

    booking = Booking(
        booking_request_id=req.id,
        company_id=req.company_id,
        talent_id=req.talent_id,
        jobpost_id=req.jobpost_id,
        application_id=req.application_id,
        start_date=req.start_date,
        end_date=req.end_date,
        start_time=req.start_time,
        end_time=req.end_time,
        site_name=req.site_name,
        site_address=req.site_address,
        contact_name=req.contact_name,
        contact_phone=req.contact_phone,
        notes=req.notes,
    )

    session.add(req)
    session.add(booking)
    enqueue(session, f"booking-accepted:{req.id}", req.company_id, "Booking request accepted",
        "Your booking request has been accepted. Sign in to view the confirmed details.", "/dashboard/company/booking-requests")
    session.commit()
    session.refresh(req)
    return req


@router.post("/agency/booking-requests/{request_id}/decline", response_model=BookingRequestRead)
@router.post("/professional/booking-requests/{request_id}/decline", response_model=BookingRequestRead)
def decline_booking_request(
    request_id: int,
    payload: BookingRequestRespond,
    user: User = Depends(require_role("professional", "agency")),
    session: Session = Depends(get_session),
):
    ownership = (Talent.agency_id == user.id) & (Talent.user_id == None) if user.role == "agency" else (Talent.user_id == user.id) & (Talent.agency_id == None)  # noqa: E711
    requested_talent = select(BookingRequest.talent_id).where(BookingRequest.id == request_id).scalar_subquery()
    talent = session.exec(select(Talent).where(ownership, Talent.id == requested_talent).with_for_update()).first()

    if not talent:
        raise HTTPException(status_code=404, detail="TALENT_PROFILE_NOT_FOUND")

    req = session.get(BookingRequest, request_id)
    if not req or req.talent_id != talent.id:
        raise HTTPException(status_code=404, detail="BOOKING_REQUEST_NOT_FOUND")

    if req.status != "pending":
        raise HTTPException(status_code=400, detail="BOOKING_REQUEST_NOT_PENDING")

    if _is_expired(req):
        req.status = "expired"
        session.add(req)
        session.commit()
        raise HTTPException(status_code=400, detail="BOOKING_REQUEST_EXPIRED")

    if not (payload.decline_reason or "").strip():
        raise HTTPException(status_code=400, detail="DECLINE_REASON_REQUIRED")

    req.status = "declined"
    req.decline_reason = payload.decline_reason.strip()
    req.responded_at = datetime.utcnow()

    session.add(req)
    enqueue(session, f"booking-declined:{req.id}", req.company_id, "Booking request declined",
        "Your booking request has been declined. Sign in to view the response.", "/dashboard/company/booking-requests")
    session.commit()
    session.refresh(req)
    return req

@router.post('/company/booking-requests/{request_id}/cancel', response_model=BookingRequestRead)
def cancel_pending_booking_request(request_id: int,
    user: User = Depends(require_role('company')),
    session: Session = Depends(get_session)):
    req = session.get(BookingRequest, request_id)
    if not req or req.company_id != user.id:
        raise HTTPException(status_code=404, detail='BOOKING_REQUEST_NOT_FOUND')
    # Use the same talent lock as acceptance, then reload the request's current status.
    talent = session.exec(select(Talent).where(Talent.id == req.talent_id).with_for_update()).first()
    session.refresh(req)
    if req.status != 'pending':
        raise HTTPException(status_code=409, detail='Only pending requests can be cancelled. Contact the professional to discuss an accepted booking.')
    req.status = 'cancelled'
    req.responded_at = datetime.utcnow()
    session.add(req)
    if talent:
        role = 'professional' if talent.user_id else 'agency'
        enqueue(session, f'booking-cancelled:{req.id}', talent.user_id or talent.agency_id,
            'Booking request cancelled', 'The company has cancelled this pending request. No booking has been confirmed.',
            f'/dashboard/{role}/booking-requests')
    session.commit(); session.refresh(req)
    return req
