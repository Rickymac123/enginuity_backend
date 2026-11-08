"""External review quota, with real PostgreSQL concurrency coverage in CI."""
import os
import uuid
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from urllib.parse import urlparse,parse_qs
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel,Session,create_engine,select
from auth.models import User
from app.routers import reviews
from models.review import Review
from models.review_invite import ReviewInvite
from models.booking import Booking


def app_for(engine,monkeypatch):
    app=FastAPI();app.include_router(reviews.router)
    def db():
        with Session(engine) as s:yield s
    def who():
        return User(id=1,email='professional@example.test',hashed_password='unused',role='professional',is_active=True,is_verified=True)
    app.dependency_overrides[reviews.get_session]=db
    app.dependency_overrides[reviews.require_professional]=who
    monkeypatch.setattr(reviews,'send_review_verification_email',lambda **kw:None)
    return app

def seed(engine):
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(User(id=1,email='professional@example.test',hashed_password='unused',role='professional',is_active=True,is_verified=True));s.commit()

@pytest.fixture
def local(monkeypatch):
    e=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool);seed(e)
    yield TestClient(app_for(e,monkeypatch)),e
    e.dispose()

def token(c):
    r=c.post('/professional/review-invites');assert r.status_code==200,r.text
    return parse_qs(urlparse(r.json()['invite_url']).query)['token'][0]

def body(t):return dict(invite_token=t,reviewer_name='Test reviewer',reviewer_email='reviewer@example.com',rating=5,comment='Reliable professional with clear communication and a detailed project handover.')

def test_two_reservations_and_expired_unused_replacement(local):
    c,e=local;a=token(c);token(c)
    assert c.post('/professional/review-invites').status_code==409
    with Session(e) as s:
        x=s.exec(select(ReviewInvite).where(ReviewInvite.token_hash==reviews.hash_token(a))).one();x.expires_at=reviews.utcnow()-timedelta(seconds=1);s.add(x);s.commit()
    token(c)
    assert c.post('/professional/review-invites').status_code==409
    assert c.post('/public/reviews/submit',json=body(a)).json()['detail']=='INVITE_EXPIRED'

def test_pending_private_and_used_expired_consume_slots(local):
    c,e=local
    for _ in range(2):
        t=token(c);payload=body(t);payload['is_public']=False
        assert c.post('/public/reviews/submit',json=payload).status_code==200
    with Session(e) as s:
        for x in s.exec(select(ReviewInvite)).all():x.expires_at=reviews.utcnow()-timedelta(days=1);s.add(x)
        s.commit()
    assert c.post('/professional/review-invites').status_code==409

def test_legacy_links_cannot_exceed_two_and_platform_excluded(local):
    c,e=local
    with Session(e) as s:
        s.add(Review(professional_id=1,rating=5,reviewer_name='Client',reviewer_email='client@example.test',source='platform',status='verified'))
        for i in range(3):s.add(ReviewInvite(professional_id=1,token_hash=reviews.hash_token(f'legacy{i}'),expires_at=reviews.utcnow()+timedelta(days=1)))
        s.commit()
    assert [c.post('/public/reviews/submit',json=body(f'legacy{i}')).status_code for i in range(3)]==[200,200,409]
    with Session(e) as s:assert len(s.exec(select(Review).where(Review.source=='imported')).all())==2

@pytest.fixture
def pg(monkeypatch):
    if os.getenv('CONTRACTPROS_POSTGRES_TESTS')!='1':pytest.skip('Disposable PostgreSQL not configured')
    url=os.environ['TEST_POSTGRES_URL'];assert make_url(url).host in {'localhost','127.0.0.1','postgres'}
    schema='test_review_quota_'+uuid.uuid4().hex;admin=create_engine(url)
    with admin.begin() as c:c.execute(text(f'CREATE SCHEMA {schema}'))
    e=create_engine(url,connect_args={'options':f'-csearch_path={schema}'})
    try:
        seed(e);yield app_for(e,monkeypatch),e
    finally:
        e.dispose()
        with admin.begin() as c:c.execute(text(f'DROP SCHEMA {schema} CASCADE'))
        admin.dispose()

def race(app,calls):
    barrier=Barrier(len(calls))
    def run(call):
        with TestClient(app) as c:
            barrier.wait(timeout=10);return c.post(call[0],json=call[1]).status_code
    with ThreadPoolExecutor(max_workers=len(calls)) as pool:return sorted(pool.map(run,calls))

def test_parallel_link_creation_reserves_only_two(pg):
    app,e=pg
    assert race(app,[('/professional/review-invites',None)]*3)==[200,200,409]
    with Session(e) as s:assert len(s.exec(select(ReviewInvite)).all())==2

def test_parallel_legacy_submissions_stop_at_two(pg):
    app,e=pg
    with Session(e) as s:
        for i in range(3):s.add(ReviewInvite(professional_id=1,token_hash=reviews.hash_token(f'old{i}'),expires_at=reviews.utcnow()+timedelta(days=1)))
        s.commit()
    assert race(app,[('/public/reviews/submit',body(f'old{i}')) for i in range(3)])==[200,200,409]
    with Session(e) as s:assert len(s.exec(select(Review)).all())==2
