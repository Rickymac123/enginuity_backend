# auth/users.py

print("🔥 users.py is being loaded")

import os
from typing import Optional
from urllib.parse import quote

from fastapi import Depends, Request
from sqlmodel import Session, select

from fastapi_users import FastAPIUsers, IntegerIDMixin
from fastapi_users.authentication import (
    AuthenticationBackend,
    CookieTransport,
    JWTStrategy,
)
from fastapi_users.manager import BaseUserManager
from fastapi_users_db_sqlmodel import SQLModelUserDatabase

from auth.database import get_session
from auth.emailer import send_email
from auth.models import User

from models.talent import Talent  # NEW


# IMPORTANT: set these in env (Codespaces secrets / .env)
SECRET = os.getenv("SECRET", "SUPER_SECRET_JWT")
VERIFY_SECRET = os.getenv("VERIFY_SECRET", SECRET)
RESET_SECRET = os.getenv("RESET_SECRET", SECRET)

FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://localhost:3000").rstrip("/")

# Cookie-based auth: login returns 204 + Set-Cookie
cookie_transport = CookieTransport(
    cookie_name="enginuity_auth",
    cookie_max_age=int(os.getenv("COOKIE_MAX_AGE", "3600")),
    cookie_secure=os.getenv("COOKIE_SECURE", "false").lower() == "true",
    cookie_samesite=os.getenv("COOKIE_SAMESITE", "lax"),
)


def get_jwt_strategy() -> JWTStrategy:
    return JWTStrategy(
        secret=SECRET,
        lifetime_seconds=int(os.getenv("JWT_LIFETIME", "3600")),
    )


auth_backend = AuthenticationBackend(
    name="jwt",
    transport=cookie_transport,
    get_strategy=get_jwt_strategy,
)


def get_user_db(session: Session = Depends(get_session)):
    yield SQLModelUserDatabase(user_model=User, session=session)


class UserManager(IntegerIDMixin, BaseUserManager[User, int]):
    verification_token_secret = VERIFY_SECRET
    reset_password_token_secret = RESET_SECRET

    async def on_after_register(
        self,
        user: User,
        request: Optional[Request] = None,
    ) -> None:
        print(f"✅ User registered: id={user.id} email={user.email}")

        # --- NEW: auto-create Talent profile when role == professional ---
        try:
            if getattr(user, "role", None) == "professional":
                session: Session = self.user_db.session  # SQLModelUserDatabase session

                # Prevent duplicate Talent rows for same user
                existing = session.exec(
                    select(Talent).where(
                        Talent.user_id == user.id,
                        Talent.agency_id == None,  # noqa: E711
                    )
                ).first()

                if not existing:
                    payload = {}
                    if request is not None:
                        try:
                            payload = await request.json()
                        except Exception:
                            payload = {}

                    # Prefer payload (signup form) then fall back to user fields
                    first_name = (payload.get("first_name") or getattr(user, "first_name", "") or "").strip()
                    last_name = (payload.get("last_name") or getattr(user, "last_name", "") or "").strip()
                    profession = (payload.get("profession") or "").strip()
                    location = (payload.get("location") or "").strip()

                    # If your frontend doesn’t send profession/location yet, this will still create
                    # a minimally-valid record only if you relax DB constraints.
                    # With your schema validator, profession/location should be present for professionals.
                    talent = Talent(
                        user_id=user.id,
                        agency_id=None,
                        first_name=first_name,
                        last_name=last_name,
                        profession=profession,
                        location=location,
                        postcode=payload.get("postcode"),
                        work_radius_miles=payload.get("work_radius_miles"),
                        ir35_preference=payload.get("ir35_preference"),
                        engineering_discipline=payload.get("engineering_discipline"),
                        industry=payload.get("industry"),
                        rate_type=payload.get("rate_type"),
                        day_rate=payload.get("day_rate"),
                        hourly_rate=payload.get("hourly_rate"),
                        bio=payload.get("bio"),
                        avatar_url=payload.get("avatar_url") or getattr(user, "avatar_url", None),
                    )

                    session.add(talent)
                    session.commit()
                    session.refresh(talent)
                    print(f"✅ Talent profile created: talent_id={talent.id} for user_id={user.id}")
        except Exception as e:
            # Don't block registration if Talent creation fails
            print(f"❌ Failed to auto-create Talent profile for user_id={user.id}: {e}")

        # Trigger verify email on signup
        await self.request_verify(user, request)

    async def on_after_request_verify(
        self,
        user: User,
        token: str,
        request: Optional[Request] = None,
    ) -> None:
        # Frontend page should POST token to backend: POST /auth/verify { "token": "..." }
        verify_link = f"{FRONTEND_BASE_URL}/verify?token={quote(token)}"

        subject = "Verify your email for Conotract Pro's UK"
        html = f"""
        <div style="font-family:Arial,sans-serif;line-height:1.5">
          <h2>Verify your email</h2>
          <p>Click the button below to verify your account:</p>
          <p style="margin:18px 0">
            <a href="{verify_link}" style="display:inline-block;padding:10px 14px;background:#6d28d9;color:#fff;text-decoration:none;border-radius:8px">
              Verify email
            </a>
          </p>
          <p style="color:#666;font-size:12px">
            If you didn’t create an account, ignore this email.
          </p>
          <p style="color:#666;font-size:12px">
            Link: <a href="{verify_link}">{verify_link}</a>
          </p>
        </div>
        """

        try:
            send_email(
                to_email=user.email,
                subject=subject,
                html=html,
            )
            print(f"📧 Verification email sent: to={user.email}")
        except Exception as e:
            # Don’t crash registration flow; log so you can fix SMTP/env issues.
            print(f"❌ Failed to send verification email to {user.email}: {e}")

    async def on_after_verify(
        self,
        user: User,
        request: Optional[Request] = None,
    ) -> None:
        print(f"✅ User verified: id={user.id} email={user.email}")


async def get_user_manager(user_db=Depends(get_user_db)):
    yield UserManager(user_db)


fastapi_users = FastAPIUsers[User, int](
    get_user_manager,
    [auth_backend],
)