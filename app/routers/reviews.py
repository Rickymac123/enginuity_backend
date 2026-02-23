# app/routers/reviews.py

import os
import secrets
import hashlib
from datetime import datetime, timedelta
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query, Header
from sqlmodel import Session, select

from auth.database import get_session
from auth.users import fastapi_users
from auth.models import User
from auth.emailer import send_email

from auth.schemas import SubmitImportedReview
from models.review import Review
from models.review_invite import ReviewInvite
from models.review_verification import ReviewVerification

router = APIRouter(tags=["reviews"])

FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://localhost:3000").rstrip("/")
REMINDER_JOB_SECRET = os.getenv("REMINDER_JOB_SECRET", "")

current_active_user = fastapi_users.current_user(active=True)


def utcnow() -> datetime:
    return datetime.utcnow()


def require_professional(user: User = Depends(current_active_user)) -> User:
    if getattr(user, "role", None) != "professional":
        raise HTTPException(status_code=403, detail="PROFESSIONAL_ONLY")
    return user


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def send_review_verification_email(to_email: str, verify_url: str) -> None:
    html = f"""
    <div style="font-family:Arial,sans-serif;line-height:1.5">
        <h2>Confirm your review</h2>
        <p>Thank you for submitting a review for ContractPros.</p>
        <p>Please confirm your review by clicking below:</p>
        <p style="margin:18px 0">
            <a href="{verify_url}"
               style="display:inline-block;padding:10px 14px;background:#6d28d9;color:#fff;text-decoration:none;border-radius:8px">
                Confirm review
            </a>
        </p>
        <p style="font-size:12px;color:#666">This link expires in 14 days.</p>
        <p style="font-size:12px;color:#666">If you did not submit this review, you can ignore this email.</p>
    </div>
    """
    send_email(
        to_email=to_email,
        subject="Confirm your review – ContractPros",
        html=html,
    )


@router.post("/professional/review-invites")
def create_review_invite(
    session: Session = Depends(get_session),
    user: User = Depends(require_professional),
) -> Dict[str, Any]:
    raw_token = generate_token()

    invite = ReviewInvite(
        professional_id=user.id,
        token_hash=hash_token(raw_token),
        expires_at=utcnow() + timedelta(days=14),
        uses=0,
        max_uses=1,
    )

    session.add(invite)
    session.commit()
    session.refresh(invite)

    return {
        "invite_url": f"{FRONTEND_BASE_URL}/reviews/submit?token={raw_token}",
        "expires_at": invite.expires_at,
    }


@router.post("/public/reviews/submit")
def submit_imported_review(
    payload: SubmitImportedReview,
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    token_hash = hash_token(payload.invite_token)

    invite = session.exec(
        select(ReviewInvite).where(ReviewInvite.token_hash == token_hash)
    ).first()
    if not invite:
        raise HTTPException(status_code=400, detail="INVALID_INVITE")

    now = utcnow()
    if invite.expires_at < now:
        raise HTTPException(status_code=400, detail="INVITE_EXPIRED")

    if invite.uses >= invite.max_uses:
        raise HTTPException(status_code=400, detail="INVITE_ALREADY_USED")

    review = Review(
        professional_id=invite.professional_id,
        rating=payload.rating,
        title=payload.title,
        comment=payload.comment,
        reviewer_name=payload.reviewer_name,
        reviewer_email=payload.reviewer_email,
        reviewer_company=payload.reviewer_company,
        reviewer_role=payload.reviewer_role,
        status="pending",
        source="imported",
        is_public=payload.is_public,
        invite_id=invite.id,
    )

    session.add(review)
    session.commit()
    session.refresh(review)

    raw_verify_token = generate_token()
    verification = ReviewVerification(
        review_id=review.id,
        token_hash=hash_token(raw_verify_token),
        expires_at=now + timedelta(days=14),
    )

    session.add(verification)

    invite.uses += 1
    session.add(invite)

    session.commit()

    verify_url = f"{FRONTEND_BASE_URL}/reviews/verify?token={raw_verify_token}"

    email_sent = True
    try:
        send_review_verification_email(
            to_email=payload.reviewer_email,
            verify_url=verify_url,
        )
    except Exception as e:
        email_sent = False
        print(f"❌ Review verification email failed: {e}")

    # IMPORTANT: don't 500 if SMTP is blocked (Render often blocks outbound SMTP)
    return {
        "detail": "REVIEW_CREATED_PENDING_VERIFICATION"
        if email_sent
        else "REVIEW_CREATED_EMAIL_NOT_SENT",
        "email_sent": email_sent,
    }


@router.post("/public/reviews/verify")
def verify_review(
    token: str = Query(...),
    session: Session = Depends(get_session),
) -> Dict[str, str]:
    token_hash = hash_token(token)

    verification = session.exec(
        select(ReviewVerification).where(
            ReviewVerification.token_hash == token_hash
        )
    ).first()
    if not verification:
        raise HTTPException(status_code=400, detail="INVALID_TOKEN")

    now = utcnow()

    if verification.used_at:
        raise HTTPException(status_code=400, detail="TOKEN_ALREADY_USED")

    if verification.expires_at < now:
        raise HTTPException(status_code=400, detail="TOKEN_EXPIRED")

    review = session.exec(
        select(Review).where(Review.id == verification.review_id)
    ).first()
    if not review:
        raise HTTPException(status_code=400, detail="REVIEW_NOT_FOUND")

    review.status = "verified"
    review.verified_at = now
    session.add(review)

    verification.used_at = now
    session.add(verification)

    session.commit()
    return {"detail": "VERIFIED"}


@router.post("/internal/jobs/review-reminders")
def send_review_reminders(
    session: Session = Depends(get_session),
    x_job_secret: str = Header(default=""),
) -> Dict[str, Any]:
    if not REMINDER_JOB_SECRET or x_job_secret != REMINDER_JOB_SECRET:
        raise HTTPException(status_code=401, detail="UNAUTHORIZED")

    now = utcnow()
    cutoff = now - timedelta(days=7)

    verifications: List[ReviewVerification] = session.exec(
        select(ReviewVerification).where(
            ReviewVerification.used_at == None,        # noqa: E711
            ReviewVerification.expires_at > now,
            ReviewVerification.created_at <= cutoff,
            ReviewVerification.reminded_at == None,    # noqa: E711
        )
    ).all()

    sent = 0
    failed = 0

    for v in verifications:
        review = session.exec(
            select(Review).where(Review.id == v.review_id)
        ).first()
        if not review or not getattr(review, "reviewer_email", None):
            continue

        raw = generate_token()
        v.token_hash = hash_token(raw)
        v.expires_at = now + timedelta(days=7)
        v.reminded_at = now

        verify_url = f"{FRONTEND_BASE_URL}/reviews/verify?token={raw}"

        try:
            send_review_verification_email(
                to_email=review.reviewer_email,
                verify_url=verify_url,
            )
            sent += 1
        except Exception as e:
            failed += 1
            print(f"❌ Review reminder email failed: review_id={review.id} err={e}")

        session.add(v)

    session.commit()
    return {"sent": sent, "failed": failed, "candidates": len(verifications)}