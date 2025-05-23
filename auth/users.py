print("🔥 users.py is being loaded")

from fastapi_users import FastAPIUsers
from fastapi_users.authentication import AuthenticationBackend, CookieTransport, JWTStrategy
from fastapi_users.db import SQLAlchemyUserDatabase
from fastapi_users.manager import BaseUserManager

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from auth.models import User
from auth.schemas import UserCreate, UserRead, UserUpdate
from auth.database import async_session_maker

SECRET = "SUPER_SECRET_JWT"

cookie_transport = CookieTransport(cookie_name="enginuity_auth", cookie_max_age=3600)

def get_jwt_strategy() -> JWTStrategy:
    return JWTStrategy(secret=SECRET, lifetime_seconds=3600)

auth_backend = AuthenticationBackend(
    name="jwt",
    transport=cookie_transport,
    get_strategy=get_jwt_strategy,
)

async def get_user_db(session: AsyncSession = Depends(async_session_maker)):
    yield SQLAlchemyUserDatabase(session, User)

class UserManager(BaseUserManager[User, int]):
    user_db_model = User
    verification_token_secret = SECRET

    async def on_after_register(self, user: User, request=None):
        print(f"✅ User registered: {user.id}")
        await self.request_verify(user, request)

    async def send_verification_token(self, user: User, token: str):
        print(f"🔗 Verification token for {user.email}: http://localhost:8000/auth/verify?token={token}")

async def get_user_manager(user_db=Depends(get_user_db)):
    yield UserManager(user_db)

fastapi_users = FastAPIUsers[User, int](
    get_user_manager,
    [auth_backend],
)
