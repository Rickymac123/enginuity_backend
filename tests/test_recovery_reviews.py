import asyncio
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs
import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine, select
from sqlalchemy.pool import StaticPool
from auth.models import User
from auth.schemas import UserRead, UserCreate
from auth.users import fastapi_users, get_user_manager, UserManager, auth_backend
from auth.deps import current_user
from fastapi_users_db_sqlmodel import SQLModelUserDatabase
from app.routers import reviews
from models.review_verification import ReviewVerification
from tests.test_launch_boundaries import registration

@pytest.fixture
def ctx(monkeypatch):
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        manager=UserManager(SQLModelUserDatabase(s,User));tokens=[]
        async def capture(self,user,token,request=None):tokens.append(token)
        monkeypatch.setattr(UserManager,'on_after_request_verify',capture)
        monkeypatch.setattr(UserManager,'on_after_forgot_password',capture)
        app=FastAPI()
        app.include_router(fastapi_users.get_register_router(UserRead,UserCreate),prefix='/auth')
        app.include_router(fastapi_users.get_verify_router(UserRead),prefix='/auth')
        app.include_router(fastapi_users.get_auth_router(auth_backend,requires_verification=True),prefix='/auth/jwt')
        app.include_router(fastapi_users.get_reset_password_router(),prefix='/auth')
        app.include_router(reviews.router)
        @app.get('/protected')
        def protected(user=Depends(current_user)):return {'id':user.id}
        async def users():yield manager
        def db():yield s
        app.dependency_overrides[get_user_manager]=users;app.dependency_overrides[reviews.get_session]=db
        yield TestClient(app),s,tokens
    engine.dispose()

def test_verify_reset_and_disabled_session(ctx):
    c,s,tokens=ctx;p=registration('professional')
    assert c.post('/auth/register',json=p).status_code==201
    login={'username':p['email'],'password':p['password']}
    assert c.post('/auth/jwt/login',data=login).status_code==400
    assert c.post('/auth/verify',json={'token':tokens[-1]}).status_code==200
    assert c.post('/auth/jwt/login',data=login).status_code==204
    assert c.get('/protected').status_code==200
    assert c.post('/auth/forgot-password',json={'email':p['email']}).status_code==202
    token=tokens[-1]
    assert c.post('/auth/reset-password',json={'token':token,'password':'short'}).status_code==400
    new='new-long-test-password-123'
    assert c.post('/auth/reset-password',json={'token':token,'password':new}).status_code==200
    assert c.get('/protected').status_code==401
    assert c.post('/auth/reset-password',json={'token':token,'password':'another-long-password'}).status_code==400
    assert c.post('/auth/jwt/login',data=login).status_code==400
    assert c.post('/auth/jwt/login',data={**login,'password':new}).status_code==204
    u=s.exec(select(User)).one();u.is_active=False;s.add(u);s.commit()
    assert c.get('/protected').status_code==401

def test_review_single_use_and_failed_reminder_retry(ctx,monkeypatch):
    c,s,tokens=ctx;p=registration('professional');c.post('/auth/register',json=p)
    c.post('/auth/verify',json={'token':tokens[-1]});c.post('/auth/jwt/login',data={'username':p['email'],'password':p['password']})
    invite=c.post('/professional/review-invites').json()['invite_url'];token=parse_qs(urlparse(invite).query)['token'][0]
    delivered=[]
    monkeypatch.setattr(reviews,'send_review_verification_email',lambda **kw:delivered.append(kw))
    payload={'invite_token':token,'reviewer_name':'Reviewer','reviewer_email':'reviewer@example.com','rating':5,'comment':'A thorough and reliable professional who completed the project to a very high standard.'}
    assert c.post('/public/reviews/submit',json=payload).json()['email_sent'] is True
    assert c.post('/public/reviews/submit',json=payload).status_code==400
    v=s.exec(select(ReviewVerification)).one();v.created_at=datetime.utcnow()-timedelta(days=8);s.add(v);s.commit();original=v.token_hash
    monkeypatch.setattr(reviews,'REMINDER_JOB_SECRET','test-secret')
    def fail(**kw):raise RuntimeError('test mail failure')
    monkeypatch.setattr(reviews,'send_review_verification_email',fail)
    response=c.post('/internal/jobs/review-reminders',headers={'x-job-secret':'test-secret'})
    assert response.json()['failed']==1;s.refresh(v)
    assert v.reminded_at is None and v.token_hash==original
    verify=parse_qs(urlparse(delivered[0]['verify_url']).query)['token'][0]
    assert c.post('/public/reviews/verify',params={'token':verify}).status_code==200
    assert c.post('/public/reviews/verify',params={'token':verify}).status_code==400

def test_graph_mail_submission(monkeypatch):
    from auth.emailer import send_email
    import httpx
    for k,v in {'MAIL_PROVIDER':'microsoft_graph','MAIL_FROM':'sender@example.com','MS_TENANT_ID':'test-tenant','MS_CLIENT_ID':'test-client','MS_CLIENT_SECRET':'test-secret'}.items():monkeypatch.setenv(k,v)
    calls=[]
    class Client:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,url,**kwargs):
            calls.append((url,kwargs));return httpx.Response(200,json={'access_token':'test-only'}) if 'token' in url else httpx.Response(202)
    monkeypatch.setattr('auth.emailer.httpx.Client',Client)
    send_email('test@example.com','Test','<p>Test</p>')
    assert len(calls)==2
    assert calls[1][1]['json']['message']['toRecipients'][0]['emailAddress']['address']=='test@example.com'
