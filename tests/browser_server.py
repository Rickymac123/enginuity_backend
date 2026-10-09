"""Isolated browser-test API. Never mount this module in the real application.

CONTRACTPROS_LOCAL_TESTS=1 TEST_MAIL_FILE=/tmp/contractpros-signup-mail.json \
  python -m uvicorn tests.browser_server:app --host 127.0.0.1 --port 8001
"""
import os
import json
import tempfile
from pathlib import Path

if os.environ.get('CONTRACTPROS_LOCAL_TESTS') != '1':
    raise RuntimeError('This fixture requires CONTRACTPROS_LOCAL_TESTS=1')
_test_directory = tempfile.TemporaryDirectory(prefix='contractpros-browser-')
os.environ['DATABASE_URL'] = 'sqlite:///' + str(Path(_test_directory.name) / 'test.db')
os.environ['SECRET'] = 'isolated-test-only-' + 'x' * 48
os.environ['FRONTEND_BASE_URL'] = 'http://127.0.0.1:3100'
from fastapi import FastAPI
from auth.users import fastapi_users, auth_backend, UserManager
from auth.schemas import UserRead, UserCreate, UserUpdate
from auth.database import init_db
from app.routers.social_auth import router


async def capture(self, user, token, request=None):
    destination = Path(os.environ.get('TEST_MAIL_FILE', '/tmp/contractpros-signup-mail.json'))
    destination.write_text(json.dumps({'email': user.email, 'token': token}))


UserManager.on_after_request_verify = capture
init_db()
app = FastAPI()
app.include_router(fastapi_users.get_register_router(UserRead, UserCreate), prefix='/auth')
app.include_router(fastapi_users.get_verify_router(UserRead), prefix='/auth')
app.include_router(fastapi_users.get_auth_router(auth_backend), prefix='/auth/jwt')
app.include_router(fastapi_users.get_users_router(UserRead, UserUpdate), prefix='/users')
app.include_router(router)
