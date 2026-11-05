from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field

class BillingAccount(SQLModel, table=True):
    user_id: int = Field(primary_key=True, foreign_key='user.id')
    customer_id: Optional[str] = Field(default=None, unique=True, index=True)
    subscription_id: Optional[str] = Field(default=None, unique=True)
    status: str = 'none'
    interval: Optional[str] = None
    paid_until: Optional[datetime] = None
    cancel_at_period_end: bool = False
    checkout_attempt: Optional[str] = None
    checkout_interval: Optional[str] = None
    checkout_id: Optional[str] = None
    checkout_url: Optional[str] = None
    checkout_expires: Optional[datetime] = None

class LaunchOffer(SQLModel, table=True):
    code: str = Field(primary_key=True)
    redeemed: int = 0
    capacity: int = 100

class LaunchRedemption(SQLModel, table=True):
    user_id: int = Field(primary_key=True, foreign_key='user.id')
    business_key: str = Field(unique=True)
    redeemed_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime

class BillingEvent(SQLModel, table=True):
    event_id: str = Field(primary_key=True)
    processed_at: datetime = Field(default_factory=datetime.utcnow)
