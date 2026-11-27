"""Anonymous registration events; existing user dates are deliberately not backfilled."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import SQLModel, Field, Session, select

from auth.models import User


def utc_now():
    # UTC-naive storage matches SQLite and PostgreSQL timestamp comparisons.
    return datetime.now(timezone.utc).replace(tzinfo=None)


class RegistrationEvent(SQLModel, table=True):
    id: str = Field(default_factory=lambda: uuid4().hex, primary_key=True)
    created_at: datetime = Field(default_factory=utc_now, index=True, nullable=False)
    role: str = Field(nullable=False)
    # No user identifier, email, IP address or marketing attribution is retained.


class RegistrationCoverage(SQLModel, table=True):
    id: int = Field(default=1, primary_key=True)
    started_at: datetime = Field(default_factory=utc_now, nullable=False)
    existing_accounts: int = Field(nullable=False)


def ensure_registration_coverage(engine):
    with Session(engine) as session:
        if session.get(RegistrationCoverage, 1):
            return
        existing = session.exec(select(func.count()).select_from(User)).one()
        session.add(RegistrationCoverage(existing_accounts=existing))
        try:
            session.commit()
        except IntegrityError:
            # Another startup process may have installed the singleton first.
            session.rollback()
            if session.get(RegistrationCoverage, 1) is None:
                raise


def registration_summary(session, period="7d", now=None):
    if period not in {"today", "7d", "30d"}:
        raise ValueError("Unsupported reporting period")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    local = now.astimezone(ZoneInfo("Europe/London"))
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    days = {"today": 1, "7d": 7, "30d": 30}[period]
    start_local = midnight - timedelta(days=days - 1)
    start = start_local.astimezone(timezone.utc).replace(tzinfo=None)
    end = now.astimezone(timezone.utc).replace(tzinfo=None)
    total = session.exec(select(func.count()).select_from(User)).one()
    coverage = session.get(RegistrationCoverage, 1)
    if coverage is None:
        return {"status": "unavailable", "total_accounts": total,
                "recorded_registrations": None, "period_total": None,
                "coverage_started_at": None, "daily": [],
                "notice": "Registration recording has not been commissioned."}

    def count(a, b):
        return session.exec(select(func.count()).select_from(RegistrationEvent).where(
            RegistrationEvent.created_at >= max(a, coverage.started_at),
            RegistrationEvent.created_at < b)).one()

    recorded = count(start, end)
    daily = []
    for i in range(days):
        a = start_local + timedelta(days=i)
        b = min(a + timedelta(days=1), local)
        au = a.astimezone(timezone.utc).replace(tzinfo=None)
        bu = b.astimezone(timezone.utc).replace(tzinfo=None)
        daily.append({"date": a.date().isoformat(),
                      "recorded": count(au, bu) if bu > coverage.started_at else None,
                      "complete": au >= coverage.started_at})
    complete = coverage.started_at <= start
    return {
        "status": "ready", "site": "contract-pros", "period": period,
        "total_accounts": total, "recorded_registrations": recorded,
        "period_total": recorded if complete else None,
        "complete_period": complete,
        "coverage_started_at": coverage.started_at.isoformat() + "Z",
        "existing_accounts_at_installation": coverage.existing_accounts,
        "window_start": start.isoformat() + "Z", "window_end": end.isoformat() + "Z",
        "refreshed_at": end.isoformat() + "Z", "daily": daily,
        "source": "Contract Pros committed account-creation events",
        "notice": "Successful account creations, including unverified and test accounts; not paying customers. "
                  "Existing registration dates are unknown. Totals include administrator accounts. "
                  "No marketing attribution is inferred. Anonymous events remain after account deletion.",
    }
