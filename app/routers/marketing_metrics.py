"""Fixed aggregate-only endpoints. No account details or write operations."""
import hmac
import os
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlmodel import Session

from app.db import get_session
from auth.deps import require_admin
from models.registration_metrics import registration_summary

router = APIRouter(tags=["marketing metrics"])
Period = Literal["today", "7d", "30d"]


def metrics_access(authorization: str = Header(default="")):
    expected = os.environ.get("MIA_SIGNUP_METRICS_TOKEN", "")
    if len(expected) < 32:
        raise HTTPException(status_code=503, detail="Count-only reporting connection is not configured")
    if len(authorization) > 512 or not hmac.compare_digest(
        authorization.encode("utf-8"), ("Bearer " + expected).encode("utf-8")
    ):
        raise HTTPException(status_code=401, detail="Count-only reporting authentication required")


def summary(response, session, period):
    response.headers["Cache-Control"] = "no-store"
    return registration_summary(session, period)


@router.get("/internal/marketing/signups", dependencies=[Depends(metrics_access)])
def machine_signups(response: Response, period: Period = "7d",
                    session: Session = Depends(get_session)):
    return summary(response, session, period)


@router.get("/admin/marketing-signups", dependencies=[Depends(require_admin)])
def admin_signups(response: Response, period: Period = "7d",
                  session: Session = Depends(get_session)):
    return summary(response, session, period)
