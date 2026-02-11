# auth/models.py

from typing import Optional
from sqlmodel import SQLModel, Field


class User(SQLModel, table=True):
    """Database model for users, used by FastAPI Users + SQLModelUserDatabase."""

    id: Optional[int] = Field(default=None, primary_key=True)

    email: str = Field(index=True, nullable=False)
    hashed_password: str

    is_active: bool = Field(default=True, nullable=False)
    is_superuser: bool = Field(default=False, nullable=False)
    is_verified: bool = Field(default=False, nullable=False)

    # Custom field for RBAC
    role: str = Field(default="engineer", nullable=False, index=True)

    # Profile fields (required)
    first_name: str = Field(nullable=False, default="")
    last_name: str = Field(nullable=False, default="")
    phone: str = Field(nullable=False, default="")

    address_line1: str = Field(nullable=False, default="")
    address_line2: str = Field(nullable=False, default="")
    city: str = Field(nullable=False, default="")
    postcode: str = Field(nullable=False, default="")
    country: str = Field(nullable=False, default="")

    # Optional fields
    company_name: Optional[str] = Field(default=None, nullable=True)
    avatar_url: Optional[str] = Field(default=None, nullable=True)