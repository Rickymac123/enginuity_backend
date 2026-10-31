from datetime import datetime, timedelta
from sqlmodel import SQLModel, Session, create_engine
from sqlalchemy.pool import StaticPool
from app.routers import reviews
from models.review import Review
from models.review_verification import ReviewVerification
from auth.models import User


def test_reminder_query_and_failed_delivery_retry(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(reviews, "REMINDER_JOB_SECRET", "local-test")
    with Session(engine) as session:
        assert {k:v for k,v in reviews.send_review_reminders(session, "local-test").items() if k != "notifications"} == {"sent": 0, "failed": 0, "candidates": 0}
        now = datetime.utcnow()
        review = Review(professional_id=1, reviewer_name="Test", reviewer_email="test@example.com", rating=5, comment="Test", status="pending", source="imported")
        session.add(review); session.commit(); session.refresh(review)
        verification = ReviewVerification(review_id=review.id, token_hash="original", created_at=now-timedelta(days=8), expires_at=now+timedelta(days=6))
        session.add(verification); session.commit()
        def fail(**kwargs): raise RuntimeError("simulated mail failure")
        monkeypatch.setattr(reviews, "send_review_verification_email", fail)
        assert {k:v for k,v in reviews.send_review_reminders(session, "local-test").items() if k != "notifications"} == {"sent": 0, "failed": 1, "candidates": 1}
        session.refresh(verification)
        assert verification.token_hash == "original" and verification.reminded_at is None
        delivered = []
        monkeypatch.setattr(reviews, "send_review_verification_email", lambda **kwargs: delivered.append(kwargs))
        assert reviews.send_review_reminders(session, "local-test")["sent"] == 1
        session.refresh(verification)
        assert verification.token_hash != "original" and verification.reminded_at is not None
        assert verification.expires_at - verification.reminded_at == timedelta(days=14)
        assert reviews.send_review_reminders(session, "local-test")["candidates"] == 0
        assert len(delivered) == 1
    engine.dispose()
