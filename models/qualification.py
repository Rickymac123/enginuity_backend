from datetime import datetime
from typing import Optional

from sqlmodel import SQLModel, Field


class Qualification(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    # Link to Talent (professional profile)
    talent_id: int = Field(foreign_key="talent.id", index=True)

    # Core fields
    name: str
    issuer: Optional[str] = None
    credential_ref: Optional[str] = None

    # Verification (admin-controlled)
    is_verified: bool = Field(default=False)
    verified_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    verified_at: Optional[datetime] = None

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)