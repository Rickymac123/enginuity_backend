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
        jobpost_id=payload.jobpost_id,
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
    enqueue(session, f"booking-request:{req.id}", talent.user_id, "New ContractPros booking request",
        "You have a new booking request. Sign in to review the details and respond.", "/dashboard/professional/booking-requests")
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


@router.get("/professional/booking-requests", response_model=List[BookingRequestRead])
def get_my_booking_requests(
    user: User = Depends(require_role("professional")),
    session: Session = Depends(get_session),
):
    talent = session.exec(
        select(Talent).where(
            Talent.user_id == user.id,
            Talent.agency_id == None,  # noqa: E711
        ).with_for_update()
    ).first()

    if not talent:
        return []

    requests = session.exec(
        select(BookingRequest)
        .where(BookingRequest.talent_id == talent.id)
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
            .where(BookingRequest.talent_id == talent.id)
            .order_by(BookingRequest.requested_at.desc())
        ).all()

    return requests


@router.post("/professional/booking-requests/{request_id}/accept", response_model=BookingRequestRead)
def accept_booking_request(
    request_id: int,
    user: User = Depends(require_role("professional")),
    session: Session = Depends(get_session),
):
    talent = session.exec(
        select(Talent).where(
            Talent.user_id == user.id,
            Talent.agency_id == None,  # noqa: E711
        ).with_for_update()
    ).first()

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
        if _conflict_exists(session, user.id, datetime.combine(day, req.start_time), datetime.combine(day, req.end_time)):
            raise HTTPException(status_code=409, detail="BOOKING_CONFLICTS_WITH_AVAILABILITY")
        day += timedelta(days=1)

    req.status = "accepted"
    req.responded_at = datetime.utcnow()

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


@router.post("/professional/booking-requests/{request_id}/decline", response_model=BookingRequestRead)
def decline_booking_request(
    request_id: int,
    payload: BookingRequestRespond,
    user: User = Depends(require_role("professional")),
    session: Session = Depends(get_session),
):
    talent = session.exec(
        select(Talent).where(
            Talent.user_id == user.id,
            Talent.agency_id == None,  # noqa: E711
        ).with_for_update()
    ).first()

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