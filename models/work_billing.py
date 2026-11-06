"""Work billing is separate from platform membership. All amounts are integer pence."""
from datetime import datetime, date
from typing import Optional
from sqlalchemy import UniqueConstraint
from sqlmodel import SQLModel, Field

class WorkBillingSettings(SQLModel, table=True):
    id: int = Field(default=1, primary_key=True)
    markup_bps: int = 2000
    revision: int = 0

class BookingRate(SQLModel, table=True):
    booking_id: int = Field(primary_key=True, foreign_key='booking.id')
    contractor_pence: int
    markup_bps: int
    unit: str = 'hour'
    day_minutes: int = 480
    revision: int = 1
    recorded_by: int
    recorded_at: datetime = Field(default_factory=datetime.utcnow)

class WorkAudit(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    actor_id: int
    entity: str
    entity_id: int
    action: str
    detail: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

class WorkTimesheet(SQLModel, table=True):
    __table_args__ = (UniqueConstraint('booking_id','week_start',name='uq_work_booking_week'),)
    id: Optional[int] = Field(default=None, primary_key=True)
    booking_id: int = Field(foreign_key='booking.id',index=True)
    week_start: date
    status: str = 'submitted'
    revision: int = 1
    submitted_by: int
    entries_json: str
    total_minutes: int
    rate_revision: int
    contractor_pence: int
    markup_bps: int
    client_rate_pence: int
    unit: str
    day_minutes: int
    net_pence: int
    correction_reason: Optional[str] = None
    approved_by: Optional[int] = None
    approved_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

class WorkInvoice(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    timesheet_id: int = Field(foreign_key='worktimesheet.id',unique=True,index=True)
    company_id: int
    status: str = 'pending'
    issue_date: date
    due_date: date
    net_pence: int
    vat_pence: int
    payload_json: str
    provider_id: Optional[str] = None
    invoice_number: Optional[str] = None
    balance_pence: Optional[int] = None
    attempts: int = 0
    last_error: Optional[str] = None
    next_attempt_at: datetime = Field(default_factory=datetime.utcnow)
    sent_at: Optional[datetime] = None

class QuickBooksClient(SQLModel, table=True):
    company_id: int = Field(primary_key=True,foreign_key='user.id')
    customer_id: str
    invoice_email: str
    revision: int = 1

class QuickBooksConnection(SQLModel, table=True):
    id: int = Field(default=1,primary_key=True)
    realm_id: str
    encrypted_refresh_token: str
    encrypted_access_token: str
    expires_at: datetime

class QuickBooksFlow(SQLModel, table=True):
    state_hash: str = Field(primary_key=True)
    admin_id: int
    expires_at: datetime
