from datetime import datetime
from typing import Optional

from sqlmodel import SQLModel, Field
from sqlalchemy import CheckConstraint


class Review(SQLModel, table=True):
    __table_args__ = (
        CheckConstraint("rating >= 1 AND rating <= 5", name="ck_review_rating_1_5"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)

    professional_id: int = Field(foreign_key="user.id", index=True)
    company_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)

    rating: int = Field(index=True)
    title: Optional[str] = None
    comment: Optional[str] = None  # validated in API (>=50 chars for imported)

    reviewer_name: str
    reviewer_email: str
    reviewer_company: Optional[str] = None
    reviewer_role: Optional[str] = None

    source: str = Field(default="imported", index=True)  # imported | platform
    status: str = Field(default="pending", index=True)   # pending | verified | rejected
    verified_at: Optional[datetime] = None

    invite_id: Optional[int] = Field(default=None, foreign_key="reviewinvite.id", index=True)

    is_public: bool = Field(default=True, index=True)

    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)