from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select
from fastapi_users import exceptions

import auth.database  # Register the existing tables before creating a synthetic database.
from auth.models import User
from auth.deps import current_user
from auth.registration import create_account
from app.db import get_session
from app.routers.marketing_metrics import router
from models.registration_metrics import (
    RegistrationEvent, RegistrationCoverage, ensure_registration_coverage, registration_summary,
)


@pytest.fixture
def context():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield engine, session
    engine.dispose()


def payload(email="new@example.com"):
    values = dict(email=email, role="professional", first_name="Test", last_name="User",
                  profession_category="engineering", profession="Engineer", location="UK",
                  postcode="TEST", password="unused")
    class Payload(SimpleNamespace):
        def model_dump(self, exclude):
            return {k: v for k, v in vars(self).items() if k not in exclude}
    return Payload(**values)


def test_coverage_does_not_invent_registration_dates(context):
    engine, s = context
    s.add(User(email="old@example.com", hashed_password="unused", role="admin")); s.commit()
    ensure_registration_coverage(engine)
    first = s.get(RegistrationCoverage, 1).started_at
    ensure_registration_coverage(engine); s.expire_all()
    result = registration_summary(s)
    assert s.get(RegistrationCoverage, 1).started_at == first
    assert result["total_accounts"] == 1
    assert result["recorded_registrations"] == 0 and result["period_total"] is None
    assert result["existing_accounts_at_installation"] == 1
    assert "old@example.com" not in str(result)
    assert s.exec(select(RegistrationEvent)).all() == []


def test_registration_events_commit_and_rollback_with_account(context):
    engine, s = context
    ensure_registration_coverage(engine)
    create_account(s, payload(), "synthetic-hash")
    s.rollback()
    assert s.exec(select(User)).all() == [] and s.exec(select(RegistrationEvent)).all() == []
    create_account(s, payload(), "synthetic-hash"); s.commit()
    events = s.exec(select(RegistrationEvent)).all()
    assert len(events) == 1 and events[0].role == "professional"
    assert set(events[0].model_dump()) == {"id", "created_at", "role"}
    with pytest.raises(exceptions.UserAlreadyExists):
        create_account(s, payload(), "synthetic-hash")
    s.rollback()
    assert len(s.exec(select(RegistrationEvent)).all()) == 1


def test_british_summer_time_window_and_exclusive_end(context):
    engine, s = context
    s.add(RegistrationCoverage(started_at=datetime(2026, 6, 1), existing_accounts=0))
    for dt in [datetime(2026, 7, 6, 22, 59), datetime(2026, 7, 6, 23),
               datetime(2026, 7, 7, 10), datetime(2026, 7, 7, 12)]:
        s.add(RegistrationEvent(created_at=dt, role="professional"))
    s.commit()
    result = registration_summary(s, "today", datetime(2026, 7, 7, 12, tzinfo=timezone.utc))
    assert result["window_start"] == "2026-07-06T23:00:00Z"
    assert result["period_total"] == 2 and result["daily"][0]["recorded"] == 2
    assert result["complete_period"] is True
    assert registration_summary(s, "30d", datetime(2026, 7, 7, 12, tzinfo=timezone.utc))["period_total"] == 3


def test_machine_endpoint_is_disabled_then_token_scoped(context, monkeypatch):
    engine, s = context
    ensure_registration_coverage(engine)
    app = FastAPI(); app.include_router(router)
    app.dependency_overrides[get_session] = lambda: s
    client = TestClient(app)
    monkeypatch.delenv("MIA_SIGNUP_METRICS_TOKEN", raising=False)
    assert client.get("/internal/marketing/signups").status_code == 503
    monkeypatch.setenv("MIA_SIGNUP_METRICS_TOKEN", "synthetic-count-token-" + "a"*40)
    assert client.get("/internal/marketing/signups").status_code == 401
    assert client.get("/internal/marketing/signups", headers={"Authorization": "Bearer wrong"}).status_code == 401
    response = client.get("/internal/marketing/signups", headers={
        "Authorization": "Bearer synthetic-count-token-" + "a"*40})
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert client.get("/internal/marketing/signups?period=all", headers={
        "Authorization": "Bearer synthetic-count-token-" + "a"*40}).status_code == 422
    assert client.post("/internal/marketing/signups").status_code == 405
    assert client.get("/admin/marketing-signups").status_code == 401
    active = User(email="private@example.com", hashed_password="not-returned", role="professional")
    app.dependency_overrides[current_user] = lambda: active
    for role in ["professional", "company", "agency"]:
        active.role = role
        assert client.get("/admin/marketing-signups").status_code == 403
    active.role = "admin"
    result = client.get("/admin/marketing-signups")
    assert result.status_code == 200
    assert "private@example.com" not in result.text and "not-returned" not in result.text
