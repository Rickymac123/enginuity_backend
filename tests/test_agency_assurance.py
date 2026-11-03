from datetime import date, datetime, timedelta
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select
import pytest
from auth.models import User
from auth.deps import current_user
from app.db import get_session
from app.routers import talent, applications, booking_requests, jobs, bookings
from models.talent import Talent
from models.booking import Booking
from models.application import TalentApplication
from tests.test_launch_repairs import payload

@pytest.fixture
def agency_context():
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        users=[User(id=i,email=f'{i}@example.com',hashed_password='unused',role=role,is_active=True,is_verified=True) for i,role in [(1,'agency'),(2,'company'),(3,'agency')]]
        s.add_all(users);s.commit();active=[users[0]];app=FastAPI()
        for mod in [talent,applications,booking_requests,jobs,bookings]:app.include_router(mod.router)
        def db():yield s
        app.dependency_overrides[get_session]=db;app.dependency_overrides[current_user]=lambda:active[0]
        yield TestClient(app),s,active,users
    engine.dispose()

def evidence():return dict(authority_confirmed=True,privacy_notice_confirmed=True,notice_provided_on='2026-01-01',notice_delivery_method='email')
def person():return dict(first_name='Synthetic',last_name='Professional',profession_category='engineering',profession='Engineer',location='London',rate_type='hour',hourly_rate=45,representation=evidence())

@pytest.mark.parametrize('change',[{'authority_confirmed':False},{'privacy_notice_confirmed':False},{'notice_provided_on':'2999-01-01'},{'notice_delivery_method':'unknown'},{'authority_confirmed':'true'}])
def test_invalid_attestation_does_not_create_profile(agency_context,change):
    c,s,*_=agency_context;p=person();p['representation'].update(change)
    assert c.post('/talent/',json=p).status_code==422
    assert not s.exec(select(Talent)).all()

@pytest.mark.parametrize("legacy_request", [False, True])
def test_agency_full_lifecycle_and_tenant_boundaries(agency_context, legacy_request):
    c,s,active,users=agency_context
    r=c.post('/talent/',json=person());assert r.status_code==200,r.text
    p=r.json();tid=p['id'];assert p['notice_version']=='2026-11-02' and p['representation_confirmed_at'];assert p['day_rate'] is None
    active[0]=users[2]
    assert c.get(f'/talent/{tid}').status_code==404
    assert c.post(f'/talent/{tid}/representation',json=evidence()).status_code==404
    assert c.patch(f'/talent/{tid}',json={'first_name':'Stolen'}).status_code==404
    assert c.delete(f'/talent/{tid}').status_code==404
    active[0]=users[1];j=c.post('/jobs/',json={'title':'Synthetic job','description':'Local acceptance only'}).json()
    active[0]=users[0];a=c.post(f'/jobs/{j["id"]}/apply',json={'talent_id':tid});assert a.status_code==200,a.text
    assert c.get('/agency/applications').json()[0]['talent_id']==tid
    active[0]=users[1];assert c.get(f'/jobs/{j["id"]}/applications').json()[0]['talent_id']==tid
    profile=c.get(f'/company/applications/{a.json()["id"]}/professional-profile')
    assert profile.status_code==200,profile.text
    assert profile.json()['profile']['id']==tid
    body=payload();body.update(talent_id=profile.json()['profile']['id'],application_id=a.json()['id'])
    req=c.post('/company/booking-requests',json=body);assert req.status_code==200,req.text
    assert req.json()['jobpost_id']==j['id']
    rid=req.json()['id']
    if legacy_request:
        from models.booking_request import BookingRequest
        old=s.get(BookingRequest,rid);old.jobpost_id=None;s.add(old);s.commit()
    active[0]=users[2]
    assert c.post(f'/agency/booking-requests/{rid}/accept').status_code==404
    active[0]=users[0];assert c.post(f'/agency/booking-requests/{rid}/accept').status_code==200
    saved=s.exec(select(Booking)).all()
    assert len(saved)==1 and saved[0].jobpost_id==j["id"]
    assert c.delete(f'/talent/{tid}').status_code==409
    assert s.get(Talent,tid) and s.exec(select(TalentApplication)).first()

def test_legacy_profile_requires_record_before_submission(agency_context):
    c,s,active,users=agency_context
    t=Talent(first_name='Legacy',last_name='Test',profession_category='engineering',profession='Engineer',location='London',agency_id=1);s.add(t);s.commit();s.refresh(t)
    active[0]=users[1];j=c.post('/jobs/',json={'title':'Test','description':'Test'}).json();active[0]=users[0]
    assert c.post(f'/jobs/{j["id"]}/apply',json={'talent_id':t.id}).status_code==409
    assert c.post(f'/talent/{t.id}/representation',json=evidence()).status_code==200
    assert c.post(f'/jobs/{j["id"]}/apply',json={'talent_id':t.id}).status_code==200

def test_additive_migration_is_repeatable():
    from scripts.prepare_launch import migrate
    from sqlalchemy import text, inspect
    engine=create_engine('sqlite://')
    with engine.begin() as c:c.execute(text('CREATE TABLE talent (id INTEGER PRIMARY KEY)'))
    migrate(engine);migrate(engine)
    assert {'representation_confirmed_at','notice_provided_on','notice_delivery_method','notice_version'}.issubset({c['name'] for c in inspect(engine).get_columns('talent')})
    engine.dispose()
