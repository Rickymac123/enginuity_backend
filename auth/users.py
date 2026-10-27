# auth/users.py

print("🔥 users.py is being loaded")

import os
from typing import Optional
from urllib.parse import quote

from fastapi import Depends, Request
from sqlmodel import Session, select
from sqlalchemy import func
from starlette.concurrency import run_in_threadpool

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
from auth.registration import create_account

from models.talent import Talent  # NEW


# IMPORTANT: set these in env (Codespaces secrets / .env)
from auth.settings import signing_secret

SECRET = signing_secret()
VERIFY_SECRET = os.getenv("VERIFY_SECRET", SECRET)
RESET_SECRET = os.getenv("RESET_SECRET", SECRET)

FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://localhost:3000").rstrip("/")

# Cookie-based auth: login returns 204 + Set-Cookie
cookie_transport = CookieTransport(
    cookie_name="enginuity_auth",
    cookie_max_age=int(os.getenv("COOKIE_MAX_AGE", "3600")),
    cookie_secure=os.getenv("COOKIE_SECURE", "true" if FRONTEND_BASE_URL.startswith("https://") else "false").lower() == "true",
    cookie_samesite=os.getenv("COOKIE_SAMESITE", "lax"),
)


class PasswordBoundJWTStrategy(JWTStrategy):
    """Changing a password invalidates previously issued sessions."""
    def fingerprint(self, user):
        import hmac, hashlib
        return hmac.new(SECRET.encode(), user.hashed_password.encode(), hashlib.sha256).hexdigest()

    async def write_token(self, user):
        from fastapi_users.jwt import generate_jwt
        return generate_jwt({"sub":str(user.id), "aud":self.token_audience, "password_version":self.fingerprint(user)},
            self.encode_key, self.lifetime_seconds, algorithm=self.algorithm)

    async def read_token(self, token, user_manager):
        import hmac
        from fastapi_users.jwt import decode_jwt
        user = await super().read_token(token, user_manager)
        if not user:
            return None
        data = decode_jwt(token, self.decode_key, self.token_audience, algorithms=[self.algorithm])
        version = data.get("password_version")
        return user if isinstance(version, str) and hmac.compare_digest(version, self.fingerprint(user)) else None


def get_jwt_strategy() -> JWTStrategy:
    return PasswordBoundJWTStrategy(
        secret=SECRET,
        lifetime_seconds=int(os.getenv("JWT_LIFETIME", "3600")),
    )


auth_backend = AuthenticationBackend(
    name="jwt",
    transport=cookie_transport,
    get_strategy=get_jwt_strategy,
)


class ThreadedUserDatabase(SQLModelUserDatabase):
    """Keep synchronous database waits off the request event loop."""
    async def get(self, id):
        return await run_in_threadpool(self.session.get, self.user_model, id)

    async def get_by_email(self, email):
        def lookup():
            return self.session.exec(select(self.user_model).where(
                func.lower(self.user_model.email) == func.lower(email))).first()
        return await run_in_threadpool(lookup)

    async def update(self, user, update_dict):
        def save():
            for key, value in update_dict.items():
                setattr(user, key, value)
            self.session.add(user)
            self.session.commit()
            self.session.refresh(user)
            return user
        return await run_in_threadpool(save)

    async def delete(self, user):
        def remove():
            self.session.delete(user)
            self.session.commit()
        await run_in_threadpool(remove)


def get_user_db(session: Session = Depends(get_session)):
    yield ThreadedUserDatabase(user_model=User, session=session)


class UserManager(IntegerIDMixin, BaseUserManager[User, int]):
    verification_token_secret = VERIFY_SECRET
    reset_password_token_secret = RESET_SECRET

    async def validate_password(self, password, user):
        from fastapi_users.exceptions import InvalidPasswordException
        if len(password) < 12 or len(password) > 128:
            raise InvalidPasswordException(reason="Use between 12 and 128 characters")

    async def create(self, user_create, safe=False, request=None):
        await self.validate_password(user_create.password, user_create)
        session = self.user_db.session
        def register():
            try:
                user = create_account(session, user_create,
                                      self.password_helper.hash(user_create.password))
                session.commit()
                session.refresh(user)
                return user
            except Exception:
                session.rollback()
                raise
        user = await run_in_threadpool(register)
        await self.on_after_register(user, request)
        return user

    async def on_after_register(self, user, request=None):
        await self.request_verify(user, request)

    async def on_after_request_verify(
        self,
        user: User,
        token: str,
        request: Optional[Request] = None,
    ) -> None:
        # Frontend page should POST token to backend: POST /auth/verify { "token": "..." }
        verify_link = f"{FRONTEND_BASE_URL}/verify?token={quote(token)}"

        subject = "Verify your email for ContractPros"
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
            from starlette.concurrency import run_in_threadpool
            await run_in_threadpool(send_email,
                to_email=user.email,
                subject=subject,
                html=html,
            )
            print(f"📧 Verification email sent: to={user.email}")
        except Exception as e:
            # Don’t crash registration flow; log so you can fix SMTP/env issues.
            print(f"❌ Failed to send verification email to {user.email}: {e}")

    async def on_after_forgot_password(self, user: User, token: str, request=None):
        from starlette.concurrency import run_in_threadpool
        reset_link = f"{FRONTEND_BASE_URL}/reset-password?token={quote(token)}"
        await run_in_threadpool(send_email, user.email, "Reset your ContractPros password",
            f'<p>A password reset was requested for your account.</p><p><a href="{reset_link}">Reset password</a></p><p>If you did not request this, ignore this email.</p>')

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