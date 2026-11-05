from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field

class ClientPaymentTerms(SQLModel, table=True):
    user_id: int = Field(primary_key=True, foreign_key='user.id')
    payment_due_days: int = 7
    revision: int = 1
    updated_by: int = Field(foreign_key='user.id')
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class ClientPaymentTermsAudit(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key='user.id', index=True)
    payment_due_days: int
    revision: int
    changed_by: int = Field(foreign_key='user.id')
    changed_at: datetime = Field(default_factory=datetime.utcnow)
