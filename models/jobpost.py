# models/jobpost.py

from typing import Optional
from datetime import datetime
from sqlmodel import SQLModel, Field


class JobPostBase(SQLModel):
    title: str
    description: str

    location: Optional[str] = None
    profession: Optional[str] = None
    day_rate_min: Optional[float] = None
    day_rate_max: Optional[float] = None


class JobPost(JobPostBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    company_id: int = Field(foreign_key="user.id", index=True, nullable=False)

    # Soft delete
    is_archived: bool = Field(default=False, index=True)
    archived_at: Optional[datetime] = Field(default=None, index=True)


class JobPostCreate(JobPostBase):
    pass


class JobPostUpdate(SQLModel):
    title: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    profession: Optional[str] = None
    day_rate_min: Optional[float] = None
    day_rate_max: Optional[float] = None