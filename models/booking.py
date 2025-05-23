from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime

class Booking(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    engineer_id: int
    job_id: int
    company_id: int
    status: str = "Pending"  # e.g. "Pending", "Confirmed", "Completed", "Cancelled"
    created_at: datetime = Field(default_factory=datetime.utcnow)

