from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field

class IR35Record(SQLModel, table=True):
    booking_id: int = Field(primary_key=True, foreign_key='booking.id')
    revision: int = 0
    answers_json: str = '{}'
    notes: str = ''
    updated_by: Optional[int] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    question_version: str = 'guidance-1'

class IR35History(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    booking_id: int = Field(index=True, foreign_key='booking.id')
    revision: int
    actor_id: int
    actor_role: str
    answers_json: str
    notes: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    question_version: str = 'guidance-1'

class IR35Attachment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    booking_id: int = Field(index=True, foreign_key='booking.id')
    key: str
    uploaded_by: int
    uploaded_role: str
    assessment_revision: int
    uploaded_at: datetime = Field(default_factory=datetime.utcnow)
