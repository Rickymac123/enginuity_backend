import asyncio
import secrets
from urllib.parse import urlparse, parse_qs

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from auth.models import User
from auth.schemas import UserRead, UserCreate
from auth.users import fastapi_users, get_user_manager, UserManager, auth_backend
from fastapi_users_db_sqlmodel import SQLModelUserDatabase
from models.talent import Talent
from models.social_auth import SocialFlow, SocialIdentity
from app.routers import social_auth as social
from tests.test_launch_boundaries import registration


@pytest.fixture
def app_context(monkeypatch):
    monkeypatch.setenv('FRONTEND_BASE_URL', 'https://www.contractpros.co.uk')
    monkeypatch.setenv('SECRET', 'test-only-' + 'x' * 40)
    for provider in ['GOOGLE', 'FACEBOOK', 'APPLE']:
        monkeypatch.setenv(provider + '_CLIENT_ID', provider.lower() + '-client')
    monkeypatch.setenv('GOOGLE_CLIENT_SECRET', 'test-secret')
    monkeypatch.setenv('FACEBOOK_CLIENT_SECRET', 'test-secret')
    monkeypatch.setenv('FACEBOOK_API_VERSION', 'v23.0')
    monkeypatch.setenv('APPLE_TEAM_ID', 'test-team')
    monkeypatch.setenv('APPLE_KEY_ID', 'test-key')
    monkeypatch.setenv('APPLE_PRIVATE_KEY', 'test-key')
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        manager = UserManager(SQLModelUserDatabase(session, User))
        tokens = []
        async def capture(self, user, token, request=None):
            tokens.append((user.email, token))
        monkeypatch.setattr(UserManager, 'on_after_request_verify', capture)
        app = FastAPI()
        app.include_router(fastapi_users.get_register_router(UserRead, UserCreate), prefix='/auth')
        app.include_router(fastapi_users.get_verify_router(UserRead), prefix='/auth')
        app.include_router(fastapi_users.get_auth_router(auth_backend), prefix='/auth/jwt')
        app.include_router(social.router)
        def db(): yield session
        async def users(): yield manager
        app.dependency_overrides[social.get_session] = db
        app.dependency_overrides[get_user_manager] = users
        yield TestClient(app), session, tokens
    engine.dispose()


@pytest.mark.parametrize('role', ['company','agency','professional'])
def test_register_verify_login(app_context, role):
    client, session, tokens = app_context
    payload = registration(role)
    payload['profession_category'] = 'engineering'
    response = client.post('/auth/register', json=payload)
    assert response.status_code == 201, response.text
    user = session.exec(select(User)).one()
    assert not user.is_verified and not user.is_superuser
    if role == 'professional':
        talent = session.exec(select(Talent)).one()
        assert talent.user_id == user.id and talent.profession_category == 'engineering'
    assert len(tokens) == 1
    assert client.post('/auth/verify', json={'token': tokens[0][1]}).status_code == 200
    response = client.post('/auth/jwt/login', data={'username': payload['email'], 'password': payload['password']})
    assert response.status_code == 204
    assert 'enginuity_auth=' in response.headers['set-cookie']
    assert client.post('/auth/register', json=payload).status_code == 400
    assert len(session.exec(select(User)).all()) == 1


@pytest.mark.parametrize('extra', [{'role':'admin'}, {'is_superuser':True}, {'is_verified':True}, {'password':'short'}, {'first_name':' '}])
def test_invalid_signup_does_not_write(app_context, extra):
    client, session, _ = app_context
    assert client.post('/auth/register', json={**registration('professional'), **extra}).status_code == 422
    assert not session.exec(select(User)).all()
    assert not session.exec(select(Talent)).all()


def begin(client, provider):
    response = client.post(f'/auth/social/{provider}/start', json={})
    assert response.status_code == 200
    result = response.json()
    state = parse_qs(urlparse(result['authorization_url']).query)['state'][0]
    return dict(state=state, browser_token=result['browser_token'], code='test-provider-code')


@pytest.mark.parametrize('provider', ['google', 'apple', 'facebook'])
def test_social_new_then_existing_account(app_context, monkeypatch, provider):
    client, session, tokens = app_context
    async def identity(*args): return 'provider-subject', 'social@example.com', provider != 'facebook'
    monkeypatch.setattr(social, 'provider_identity', identity)
    body = begin(client, provider)
    response = client.post(f'/auth/social/{provider}/exchange', json=body)
    assert response.status_code == 200, response.text
    ticket = response.json()['ticket']
    assert client.post(f'/auth/social/{provider}/exchange', json=body).status_code == 400
    credentials = {'token': ticket, 'browser_token': body['browser_token']}
    assert client.post('/auth/social/pending', json=credentials).json()['email'] == 'social@example.com'
    response = client.post('/auth/social/complete', json={**credentials, 'profile': registration('professional')})
    assert response.status_code == 200, response.text
    assert session.exec(select(User)).one().email == 'social@example.com'
    assert session.exec(select(Talent)).one().profession_category == 'other'
    assert len(session.exec(select(SocialIdentity)).all()) == 1
    assert client.post('/auth/social/complete', json={**credentials, 'profile': registration('professional')}).status_code == 400
    if provider == 'facebook':
        assert response.json()['status'] == 'verification_required'
        assert 'cookie' not in response.json()
        assert client.post('/auth/verify', json={'token': tokens[0][1]}).status_code == 200
    else:
        assert response.json()['status'] == 'signed_in'
    response = client.post(f'/auth/social/{provider}/exchange', json=begin(client, provider))
    assert response.json()['status'] == 'signed_in'
    assert response.json()['cookie'].startswith('enginuity_auth=')
    assert len(session.exec(select(User)).all()) == 1


def test_email_collision_not_automatically_linked(app_context, monkeypatch):
    client, session, _ = app_context
    client.post('/auth/register', json=registration('company'))
    async def identity(*args): return 'other-subject', 'PERSON@example.com', True
    monkeypatch.setattr(social, 'provider_identity', identity)
    response = client.post('/auth/social/google/exchange', json=begin(client,'google'))
    assert response.status_code == 409
    assert not session.exec(select(SocialIdentity)).all()


@pytest.mark.parametrize('failure', ['wrong_browser','wrong_provider','expired'])
def test_state_attacks_rejected_before_provider(app_context, monkeypatch, failure):
    client, session, _ = app_context
    async def identity(*args): pytest.fail('Provider must not be contacted')
    monkeypatch.setattr(social, 'provider_identity', identity)
    body = begin(client, 'google')
    provider = 'google'
    if failure == 'wrong_browser': body['browser_token'] = secrets.token_urlsafe(32)
    if failure == 'wrong_provider': provider = 'apple'
    if failure == 'expired':
        flow = session.get(SocialFlow, social.digest(body['state']))
        flow.expires_at = 1; session.add(flow); session.commit()
    assert client.post(f'/auth/social/{provider}/exchange', json=body).status_code == 400


def test_unconfigured_provider_fails_closed(app_context, monkeypatch):
    client, _, _ = app_context
    monkeypatch.delenv('GOOGLE_CLIENT_SECRET')
    assert 'google' not in client.get('/auth/social/providers').json()['providers']
    assert client.post('/auth/social/google/start', json={}).status_code == 503


def test_atomic_profile_failure_rolls_back_user(app_context, monkeypatch):
    _, session, _ = app_context
    manager = UserManager(SQLModelUserDatabase(session, User))
    original = session.flush
    count = [0]
    def broken(*args, **kwargs):
        count[0] += 1
        if any(isinstance(item, Talent) for item in session.new): raise RuntimeError('Simulated profile write failure')
        return original(*args, **kwargs)
    monkeypatch.setattr(session, 'flush', broken)
    with pytest.raises(RuntimeError): asyncio.run(manager.create(UserCreate(**registration('professional'))))
    monkeypatch.setattr(session, 'flush', original)
    assert not session.exec(select(User)).all()

@pytest.mark.parametrize('failure', ['valid', 'nonce', 'audience', 'expired', 'signature', 'unverified'])
def test_google_verifies_signed_identity_claims(app_context, monkeypatch, failure):
    import time
    import jwt
    import httpx
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    from types import SimpleNamespace
    client, _, _ = app_context
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    public_jwk = __import__('json').loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()))
    public_jwk.update(kid='test-kid', alg='RS256', use='sig')
    claims = dict(iss='https://accounts.google.com', aud='google-client', sub='stable-subject',
        exp=int(time.time())+300, iat=int(time.time()), nonce='expected-nonce', email='person@example.com', email_verified=True)
    if failure == 'nonce': claims['nonce'] = 'other'
    if failure == 'audience': claims['aud'] = 'another-app'
    if failure == 'expired': claims['exp'] = 1
    if failure == 'unverified': claims['email_verified'] = False
    if failure == 'signature':
        pem = rsa.generate_private_key(public_exponent=65537,key_size=2048).private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
    encoded = jwt.encode(claims,pem,algorithm='RS256',headers={'kid':'test-kid'})
    original = httpx.AsyncClient
    def transport(request):
        if request.url.path == '/token':
            assert b'code_verifier=expected-verifier' in request.content
            return httpx.Response(200,json={'id_token':encoded})
        return httpx.Response(200,json={'keys':[public_jwk]})
    monkeypatch.setattr(social.httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(transport), **kwargs))
    coroutine = social.provider_identity('google','test-code',SimpleNamespace(nonce='expected-nonce',verifier='expected-verifier'))
    if failure == 'valid':
        assert asyncio.run(coroutine) == ('stable-subject','person@example.com',True)
    else:
        with pytest.raises(Exception): asyncio.run(coroutine)


def test_disabled_social_account_cannot_sign_in(app_context, monkeypatch):
    client, session, _ = app_context
    user = User(email='disabled@example.com',hashed_password='unused',role='company',is_active=False,is_verified=True)
    session.add(user); session.commit(); session.refresh(user)
    session.add(SocialIdentity(provider='google',subject='disabled-subject',user_id=user.id)); session.commit()
    async def identity(*args): return 'disabled-subject','disabled@example.com',True
    monkeypatch.setattr(social,'provider_identity',identity)
    response = client.post('/auth/social/google/exchange',json=begin(client,'google'))
    assert response.status_code == 403
    assert 'cookie' not in response.json()


@pytest.mark.parametrize('provider', ['apple', 'facebook'])
def test_provider_exchange_parameters(app_context, monkeypatch, provider):
    import time
    import jwt
    import httpx
    import json
    from cryptography.hazmat.primitives.asymmetric import rsa, ec
    from cryptography.hazmat.primitives import serialization
    from types import SimpleNamespace
    _, _, _ = app_context
    calls=[]
    private = rsa.generate_private_key(public_exponent=65537,key_size=2048)
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key())); public['kid']='provider-key'
    pem = private.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
    apple_private=ec.generate_private_key(ec.SECP256R1())
    monkeypatch.setenv('APPLE_PRIVATE_KEY',apple_private.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode())
    token=jwt.encode({'iss':'https://appleid.apple.com','sub':'apple-subject','aud':'apple-client','nonce':'expected-nonce','email':'person@example.com','email_verified':'true','iat':int(time.time()),'exp':int(time.time())+300},pem,algorithm='RS256',headers={'kid':'provider-key'})
    original=httpx.AsyncClient
    def transport(request):
        calls.append(request)
        if request.url.path.endswith('/auth/token'):
            form=parse_qs(request.content.decode())
            claims=jwt.decode(form['client_secret'][0],apple_private.public_key(),algorithms=['ES256'],audience='https://appleid.apple.com')
            assert claims['sub']=='apple-client' and claims['iss']=='test-team'
            return httpx.Response(200,json={'id_token':token})
        if request.url.path.endswith('/auth/keys'): return httpx.Response(200,json={'keys':[public]})
        if request.url.path.endswith('/oauth/access_token'): return httpx.Response(200,json={'access_token':'fake-access'})
        if request.url.path.endswith('/debug_token'): return httpx.Response(200,json={'data':{'is_valid':True,'app_id':'facebook-client','user_id':'facebook-subject'}})
        assert request.headers['authorization']=='Bearer fake-access'
        assert 'appsecret_proof' in request.url.params
        return httpx.Response(200,json={'id':'facebook-subject','email':'person@example.com'})
    monkeypatch.setattr(social.httpx,'AsyncClient',lambda **kwargs: original(transport=httpx.MockTransport(transport),**kwargs))
    assert asyncio.run(social.provider_identity(provider,'fake-code',SimpleNamespace(nonce='expected-nonce',verifier='v'))) == (provider+'-subject','person@example.com',provider=='apple')


def test_deleted_account_email_can_register_again(app_context):
    from models.social_auth import RegistrationEmail
    client, session, _ = app_context
    assert client.post('/auth/register',json=registration('company')).status_code==201
    assert session.exec(select(RegistrationEmail)).all()==[]
    user=session.exec(select(User)).one()
    session.delete(user);session.commit()
    assert client.post('/auth/register',json=registration('company')).status_code==201


def test_concurrent_registration_creates_one_user(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from fastapi_users import exceptions
    from models.social_auth import RegistrationEmail
    engine=create_engine('sqlite:///'+str(tmp_path/'race.db'),connect_args={'check_same_thread':False})
    SQLModel.metadata.create_all(engine)
    async def no_email(*args,**kwargs): pass
    monkeypatch.setattr(UserManager,'on_after_register',no_email)
    def attempt():
        with Session(engine) as session:
            manager=UserManager(SQLModelUserDatabase(session,User))
            try:
                asyncio.run(manager.create(UserCreate(**registration('professional'))))
                return 'created'
            except exceptions.UserAlreadyExists:
                return 'duplicate'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _:attempt(),range(2)))==['created','duplicate']
    with Session(engine) as session:
        assert len(session.exec(select(User)).all())==1
        assert len(session.exec(select(Talent)).all())==1
        assert not session.exec(select(RegistrationEmail)).all()
    engine.dispose()
