# auth/deps.py

from fastapi import Depends, HTTPException
from .models import User
from .users import fastapi_users

# Base dependency: "give me the currently authenticated user or 401"
current_user = fastapi_users.current_user()

# Central place for role names (prevents typos across the app)
ROLE_COMPANY = "company"
ROLE_AGENCY = "agency"
ROLE_ADMIN = "admin"
ROLE_PROFESSIONAL = "professional"

ALLOWED_ROLES = {ROLE_COMPANY, ROLE_AGENCY, ROLE_ADMIN, ROLE_PROFESSIONAL}


def require_role(*allowed_roles: str):
    """
    Dependency factory to enforce one or more roles.

    Example:
        user: User = Depends(require_role("agency"))
        user: User = Depends(require_role("company", "agency"))
    """

    allowed = tuple(allowed_roles)

    def dependency(user: User = Depends(current_user)):
        # Validate stored role (catch typos / unexpected values)
        role = getattr(user, "role", None)
        if role not in ALLOWED_ROLES:
            raise HTTPException(
                status_code=403,
                detail=f"Unauthorized: unknown role '{role}'",
            )

        # If no roles passed in, just behave like current_user
        if not allowed:
            return user

        if role not in allowed:
            raise HTTPException(
                status_code=403,
                detail=f"Unauthorized: requires {list(allowed)}, got '{role}'",
            )

        return user

    return dependency


def require_admin(user: User = Depends(current_user)):
    """
    Admin-only dependency.
    Treat either role=="admin" OR is_superuser=True as admin.
    """
    role = getattr(user, "role", None)

    if role not in ALLOWED_ROLES:
        raise HTTPException(status_code=403, detail=f"Unauthorized: unknown role '{role}'")

    if getattr(user, "is_superuser", False):
        return user

    if role == ROLE_ADMIN:
        return user

    raise HTTPException(status_code=403, detail="Unauthorized: admin only")