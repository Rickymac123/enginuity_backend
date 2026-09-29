"""Allowlisted review fields shared by client-facing profile views."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class PublicReview(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: Optional[int] = None
    rating: int
    title: Optional[str] = None
    comment: Optional[str] = None
    reviewer_name: str
    reviewer_company: Optional[str] = None
    reviewer_role: Optional[str] = None
    source: str
    status: str
    verified_at: Optional[datetime] = None
    created_at: datetime


def public_review(review):
    return PublicReview.model_validate(review).model_dump(mode="json")
