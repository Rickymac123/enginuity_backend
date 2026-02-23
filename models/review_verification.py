from datetime import datetime
from typing import Optional

from sqlmodel import SQLModel, Field


class ReviewVerification(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    review_id: int = Field(foreign_key="review.id", index=True)

    token_hash: str = Field(index=True, unique=True)

    expires_at: datetime
    used_at: Optional[datetime] = None

    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    reminded_at: Optional[datetime] = Field(default=None, index=True)