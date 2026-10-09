"""Short-lived login attempts and stable provider identities; never provider tokens."""
from typing import Optional
from sqlmodel import SQLModel, Field
from sqlalchemy import UniqueConstraint


class SocialIdentity(SQLModel, table=True):
    __table_args__ = (UniqueConstraint('provider', 'subject', name='uq_social_identity'),)
    id: Optional[int] = Field(default=None, primary_key=True)
    provider: str
    subject: str
    user_id: int = Field(foreign_key='user.id', index=True)


class SocialFlow(SQLModel, table=True):
    token_hash: str = Field(primary_key=True)
    browser_hash: str
    provider: str
    nonce: str
    verifier: str
    expires_at: int = Field(index=True)
    stage: str = 'authorize'
    subject: Optional[str] = None
    email: Optional[str] = None


class RegistrationEmail(SQLModel, table=True):
    # Transient unique-key lock for new registrations, including social signup.
    # Existing users are also checked before insertion. No backfill is required.
    email: str = Field(primary_key=True)
