"""Authorization-code login with browser-bound, one-use state and signup tickets."""
import base64
import hashlib
import hmac
import os
import secrets
from auth.settings import signing_secret
import time
from typing import Any, Literal
from urllib.parse import urlencode, urlparse

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException
from fastapi_users import exceptions
from pydantic import BaseModel, Field, ValidationError, TypeAdapter, EmailStr
from sqlalchemy import delete, func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from auth.database import get_session
from auth.models import User
from auth.registration import create_account
from auth.schemas import UserCreate
from auth.users import UserManager, get_jwt_strategy, get_user_db
from models.social_auth import SocialFlow, SocialIdentity

router = APIRouter(prefix='/auth/social', tags=['social authentication'])
Provider = Literal['google', 'apple', 'facebook']


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def config(provider):
    origin = os.getenv('FRONTEND_BASE_URL', '').rstrip('/')
    parsed = urlparse(origin)
    if parsed.scheme != 'https' or not parsed.netloc or parsed.path or parsed.query or parsed.fragment:
        raise HTTPException(503, 'SOCIAL_NOT_CONFIGURED')
    if len(signing_secret()) < 32:
        raise HTTPException(503, 'SOCIAL_NOT_CONFIGURED')
    client_id = os.getenv(f'{provider.upper()}_CLIENT_ID', '')
    required = ['APPLE_TEAM_ID', 'APPLE_KEY_ID', 'APPLE_PRIVATE_KEY'] if provider == 'apple' else [f'{provider.upper()}_CLIENT_SECRET']
    if provider == 'facebook':
        required.append('FACEBOOK_API_VERSION')
    if not client_id or any(not os.getenv(key) for key in required):
        raise HTTPException(503, 'SOCIAL_NOT_CONFIGURED')
    return client_id, f'{origin}/api/social/{provider}/callback'


@router.get('/providers')
def providers():
    enabled = []
    for name in ('google', 'apple', 'facebook'):
        try:
            config(name)
            enabled.append(name)
        except HTTPException:
            pass
    return {'providers': enabled}


@router.post('/{provider}/start')
def start(provider: Provider, session: Session = Depends(get_session)):
    client_id, redirect_uri = config(provider)
    state, browser, nonce, verifier = [secrets.token_urlsafe(32) for _ in range(4)]
    now = int(time.time())
    session.exec(delete(SocialFlow).where(SocialFlow.expires_at < now))
    session.add(SocialFlow(token_hash=digest(state), browser_hash=digest(browser),
        provider=provider, nonce=nonce, verifier=verifier, expires_at=now + 600))
    session.commit()
    params = dict(client_id=client_id, redirect_uri=redirect_uri, response_type='code', state=state)
    if provider == 'google':
        endpoint = 'https://accounts.google.com/o/oauth2/v2/auth'
        params.update(scope='openid email profile', nonce=nonce,
            code_challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('='), code_challenge_method='S256')
    elif provider == 'apple':
        endpoint = 'https://appleid.apple.com/auth/authorize'
        params.update(scope='email', nonce=nonce, response_mode='form_post')
    else:
        endpoint = f"https://www.facebook.com/{os.environ['FACEBOOK_API_VERSION']}/dialog/oauth"
        params.update(scope='email,public_profile')
    return {'authorization_url': endpoint + '?' + urlencode(params), 'browser_token': browser}


class Exchange(BaseModel):
    state: str = Field(min_length=20, max_length=200)
    code: str = Field(min_length=1, max_length=4096)
    browser_token: str = Field(min_length=20, max_length=200)


class Ticket(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    browser_token: str = Field(min_length=20, max_length=200)


class Complete(Ticket):
    profile: dict[str, Any]


def read_flow(session, token, browser, stage):
    flow = session.get(SocialFlow, digest(token))
    if (not flow or flow.expires_at <= int(time.time()) or flow.stage != stage
            or not hmac.compare_digest(flow.browser_hash, digest(browser))):
        raise HTTPException(400, 'SOCIAL_INVALID_STATE' if stage == 'authorize' else 'SOCIAL_EXPIRED')
    return flow


def consume_flow(session, flow):
    result = session.exec(delete(SocialFlow).where(SocialFlow.token_hash == flow.token_hash,
        SocialFlow.expires_at > int(time.time()), SocialFlow.stage == flow.stage))
    if result.rowcount != 1:
        session.rollback()
        raise HTTPException(400, 'SOCIAL_EXPIRED')


async def provider_identity(provider, code, flow):
    client_id, redirect_uri = config(provider)
    async with httpx.AsyncClient(timeout=15) as client:
        if provider == 'facebook':
            secret = os.environ['FACEBOOK_CLIENT_SECRET']
            root = f"https://graph.facebook.com/{os.environ['FACEBOOK_API_VERSION']}"
            response = await client.post(root + '/oauth/access_token', data=dict(
                client_id=client_id, client_secret=secret, redirect_uri=redirect_uri, code=code))
            response.raise_for_status()
            token = response.json()['access_token']
            # Bind the returned access token to this app before using its identity.
            check = await client.get(root + '/debug_token', params={'input_token': token},
                headers={'Authorization': f'Bearer {client_id}|{secret}'})
            check.raise_for_status()
            checked = check.json()['data']
            if not checked.get('is_valid') or str(checked.get('app_id')) != client_id:
                raise ValueError('Invalid app token')
            response = await client.get(root + '/me', headers={'Authorization': f'Bearer {token}'},
                params={'fields': 'id,email', 'appsecret_proof': hmac.new(secret.encode(), token.encode(), hashlib.sha256).hexdigest()})
            response.raise_for_status()
            identity = response.json()
            if str(identity['id']) != str(checked.get('user_id')):
                raise ValueError('Identity mismatch')
            # Facebook does not return an OIDC email_verified claim. Verify locally.
            return str(identity['id']), identity.get('email'), False
        if provider == 'apple':
            secret = jwt.encode({'iss': os.environ['APPLE_TEAM_ID'], 'iat': int(time.time()),
                'exp': int(time.time()) + 300, 'aud': 'https://appleid.apple.com', 'sub': client_id},
                os.environ['APPLE_PRIVATE_KEY'].replace('\\n', '\n'), algorithm='ES256',
                headers={'kid': os.environ['APPLE_KEY_ID']})
            token_url, keys_url, issuer = 'https://appleid.apple.com/auth/token', 'https://appleid.apple.com/auth/keys', 'https://appleid.apple.com'
        else:
            secret = os.environ['GOOGLE_CLIENT_SECRET']
            token_url, keys_url, issuer = 'https://oauth2.googleapis.com/token', 'https://www.googleapis.com/oauth2/v3/certs', ['https://accounts.google.com', 'accounts.google.com']
        body = dict(grant_type='authorization_code', code=code, client_id=client_id,
            client_secret=secret, redirect_uri=redirect_uri)
        if provider == 'google':
            body['code_verifier'] = flow.verifier
        response = await client.post(token_url, data=body)
        response.raise_for_status()
        token = response.json()['id_token']
        header = jwt.get_unverified_header(token)
        response = await client.get(keys_url)
        response.raise_for_status()
        key = next(k for k in response.json()['keys'] if k['kid'] == header.get('kid'))
        claims = jwt.decode(token, jwt.PyJWK.from_dict(key, algorithm='RS256').key,
            algorithms=['RS256'], audience=client_id, issuer=issuer,
            options={'require': ['exp', 'iat', 'sub', 'iss', 'aud', 'nonce']})
        if claims['nonce'] != flow.nonce or claims.get('email_verified') not in (True, 'true'):
            raise ValueError('Unverified identity')
        if isinstance(claims['aud'], list) and len(claims['aud']) > 1 and claims.get('azp') != client_id:
            raise ValueError('Invalid authorized party')
        return claims['sub'], claims.get('email'), True


async def login_result(user):
    if not user or not user.is_active:
        raise HTTPException(403, 'SOCIAL_ACCOUNT_DISABLED')
    if not user.is_verified:
        raise HTTPException(403, 'EMAIL_NOT_VERIFIED')
    token = await get_jwt_strategy().write_token(user)
    return {'status': 'signed_in', 'cookie': f'enginuity_auth={token}', 'role': user.role}


@router.post('/{provider}/exchange')
async def exchange(provider: Provider, body: Exchange, session: Session = Depends(get_session)):
    flow = read_flow(session, body.state, body.browser_token, 'authorize')
    if flow.provider != provider:
        raise HTTPException(400, 'SOCIAL_INVALID_STATE')
    # Consume before calling the provider so a state cannot be replayed or raced.
    consume_flow(session, flow)
    session.commit()
    try:
        subject, email, verified = await provider_identity(provider, body.code, flow)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(400, 'SOCIAL_FAILED')
    identity = session.exec(select(SocialIdentity).where(SocialIdentity.provider == provider, SocialIdentity.subject == subject)).first()
    if identity:
        return await login_result(session.get(User, identity.user_id))
    try:
        email = str(TypeAdapter(EmailStr).validate_python(email)).lower()
    except ValidationError:
        raise HTTPException(400, 'SOCIAL_EMAIL_REQUIRED')
    if session.exec(select(User).where(func.lower(User.email) == email)).first():
        raise HTTPException(409, 'SOCIAL_EXISTING_EMAIL')
    ticket = secrets.token_urlsafe(32)
    session.add(SocialFlow(token_hash=digest(ticket), browser_hash=digest(body.browser_token),
        provider=provider, nonce='', verifier='', stage='signup', subject=subject,
        email=email, expires_at=int(time.time()) + 600))
    session.commit()
    return {'status': 'signup_required', 'ticket': ticket}


@router.post('/pending')
def pending(body: Ticket, session: Session = Depends(get_session)):
    flow = read_flow(session, body.token, body.browser_token, 'signup')
    return {'email': flow.email, 'provider': flow.provider}


@router.post('/complete')
async def complete(body: Complete, session: Session = Depends(get_session)):
    flow = read_flow(session, body.token, body.browser_token, 'signup')
    try:
        payload = UserCreate.model_validate({**body.profile, 'email': flow.email, 'password': secrets.token_urlsafe(48)})
    except ValidationError:
        raise HTTPException(422, 'INVALID_PROFILE')
    manager = UserManager(next(get_user_db(session)))
    try:
        consume_flow(session, flow)
        user = create_account(session, payload, manager.password_helper.hash(payload.password), verified=flow.provider != 'facebook')
        session.add(SocialIdentity(provider=flow.provider, subject=flow.subject, user_id=user.id))
        session.commit()
        session.refresh(user)
    except (exceptions.UserAlreadyExists, IntegrityError):
        session.rollback()
        raise HTTPException(409, 'SOCIAL_EXISTING_EMAIL')
    except Exception:
        session.rollback()
        raise
    if not user.is_verified:
        await manager.request_verify(user)
        return {'status': 'verification_required'}
    return await login_result(user)
