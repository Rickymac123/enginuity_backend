"""Durable transactional notifications. The scheduled worker retries failed deliveries."""
import os
from datetime import datetime, timedelta
from html import escape
from typing import Optional
from sqlmodel import SQLModel, Field, Session, select
from auth.models import User
from auth.emailer import send_email


class EmailNotification(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    event_key: str = Field(unique=True, index=True)
    recipient_id: int = Field(index=True)
    subject: str
    message: str
    path: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    next_attempt_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    sent_at: Optional[datetime] = None
    attempts: int = 0


def enqueue(session, event_key, recipient_id, subject, message, path):
    if not recipient_id:
        return
    if session.exec(select(EmailNotification).where(EmailNotification.event_key == event_key)).first():
        return
    session.add(EmailNotification(event_key=event_key, recipient_id=recipient_id,
                                  subject=subject, message=message, path=path))


def deliver_pending(session: Session, limit=50):
    now = datetime.utcnow()
    from models.booking import Booking
    from models.review import Review
    # Lock completed bookings so concurrent scheduler runs cannot enqueue twice.
    completed = session.exec(select(Booking).where(Booking.status == 'completed').with_for_update(skip_locked=True)).all()
    for booking in completed:
        invite = session.exec(select(EmailNotification).where(EmailNotification.event_key == f'booking-review-invite:{booking.id}')).first()
        reviewed = session.exec(select(Review.id).where(Review.booking_id == booking.id)).first()
        if invite and invite.sent_at and invite.sent_at <= now - timedelta(days=7) and not reviewed:
            enqueue(session, f'booking-review-reminder:{booking.id}', booking.company_id,
                    'A reminder to review your ContractPros booking',
                    'If you have a moment, share your experience of your completed booking. This is your only review reminder.',
                    f'/dashboard/company/booking-requests/{booking.booking_request_id}/review')
    session.flush()
    notifications = session.exec(select(EmailNotification).where(
        EmailNotification.sent_at == None, EmailNotification.next_attempt_at <= now,
        EmailNotification.attempts < 10,
    ).order_by(EmailNotification.created_at).limit(limit).with_for_update(skip_locked=True)).all()
    sent = failed = 0
    base = os.getenv('FRONTEND_BASE_URL', 'https://www.contractpros.co.uk').rstrip('/')
    for item in notifications:
        if item.event_key.startswith(('booking-review-invite:', 'booking-review-reminder:')):
            booking_id = int(item.event_key.rsplit(':', 1)[1])
            booking = session.get(Booking, booking_id)
            reviewed = session.exec(select(Review.id).where(Review.booking_id == booking_id)).first()
            if not booking or booking.status != 'completed' or reviewed:
                # Exhaust without marking as delivered; this notification is obsolete.
                item.attempts = 10
                session.add(item)
                continue
        user = session.get(User, item.recipient_id)
        item.attempts += 1
        if not user or not user.is_active or not user.is_verified:
            item.next_attempt_at = now + timedelta(days=1)
            session.add(item)
            continue
        try:
            link = escape(base + item.path, quote=True)
            send_email(user.email, item.subject, f'<p>{escape(item.message)}</p><p><a href="{link}">Open ContractPros</a></p>')
            item.sent_at = now
            sent += 1
        except Exception:
            failed += 1
            item.next_attempt_at = now + timedelta(minutes=min(60, 2 ** item.attempts))
        session.add(item)
    session.commit()
    return {'sent': sent, 'failed': failed}
