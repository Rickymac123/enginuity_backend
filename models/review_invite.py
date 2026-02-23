from datetime import datetime
from typing import Optional

from sqlmodel import SQLModel, Field


class ReviewInvite(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    professional_id: int = Field(foreign_key="user.id", index=True)

    token_hash: str = Field(index=True, unique=True)

    expires_at: datetime
    max_uses: int = 1
    uses: int = 0

    reminder_sent_at: Optional[datetime] = Field(default=None, index=True)

    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)