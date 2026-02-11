from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import SQLModel, Field


class TalentApplicationBase(SQLModel):
    jobpost_id: int
    talent_id: int
    status: str = Field(default="pending", index=True)
    notes: Optional[str] = None


class TalentApplication(TalentApplicationBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TalentApplicationCreate(SQLModel):
    talent_id: int
    notes: Optional[str] = None


class TalentApplicationUpdate(SQLModel):
    status: Optional[str] = None
    notes: Optional[str] = None


class TalentApplicationRead(TalentApplicationBase):
    id: int
    created_at: datetime
    updated_at: datetime
