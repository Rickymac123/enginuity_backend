import io
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import SQLModel,Session,create_engine,select
from sqlalchemy.pool import StaticPool
from datetime import date,time
from auth.models import User
from auth.deps import current_user
from app.db import get_session
from app.routers import ir35
from app.ir35 import guidance,QUESTIONS
from models.booking import Booking
from models.talent import Talent
from models.ir35 import IR35History,IR35Attachment

@pytest.fixture
def ctx(monkeypatch):
 engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
 SQLModel.metadata.create_all(engine)
 with Session(engine) as s:
  users=[User(id=i,email=f'{i}@example.test',hashed_password='unused',role=role,is_active=True,is_verified=True) for i,role in [(1,'professional'),(2,'company'),(3,'company'),(4,'admin'),(5,'agency')]]
  s.add_all(users)
  s.add_all([Talent(id=1,user_id=1,first_name='Demo',last_name='Engineer',profession='Engineer',profession_category='engineering',location='UK'),Talent(id=2,agency_id=5,first_name='Agency',last_name='Engineer',profession='Engineer',profession_category='engineering',location='UK')])
  for i in (1,2):s.add(Booking(id=i,booking_request_id=i,company_id=2,talent_id=i,start_date=date(2026,11,1),end_date=date(2026,11,30),start_time=time(8),end_time=time(17),site_name='Demo site',site_address='UK',contact_name='Demo',contact_phone='0'))
  s.commit();active=[users[1]];app=FastAPI();app.include_router(ir35.router)
  app.dependency_overrides[get_session]=lambda:s;app.dependency_overrides[current_user]=lambda:active[0]
  objects={}
  class Storage:
   def put_object(self,**k):objects[k['Key']]=k['Body']
   def get_object(self,**k):return {'Body':io.BytesIO(objects[k['Key']])}
   def delete_object(self,**k):objects.pop(k['Key'],None)
  monkeypatch.setattr(ir35,'r2_client',lambda:Storage());monkeypatch.setattr(ir35,'private_bucket_name',lambda:'private-test')
  yield TestClient(app),s,active,users,objects

def test_access_and_history(ctx):
 c,s,a,u,_=ctx
 assert c.get('/ir35/by-request/1').json()['revision']==0
 body=dict(expected_revision=0,answers={'personal':'yes'},notes='Confirm actual substitution practice')
 assert c.put('/ir35/by-request/1',json=body).status_code==200
 a[0]=u[0];d=c.get('/ir35/by-request/1').json();assert d['answers']['personal']=='yes' and d['history'][0]['actor_role']=='company'
 assert c.put('/ir35/by-request/1',json=body).status_code==409
 body['expected_revision']=1;body['answers']['substitute']='unknown';assert c.put('/ir35/by-request/1',json=body).json()['revision']==2
 assert len(s.exec(select(IR35History)).all())==2
 a[0]=u[2]
 assert c.get('/ir35/by-request/1').status_code==404
 assert c.put('/ir35/by-request/1',json=body).status_code==404
 a[0]=u[4];assert c.get('/ir35/by-request/1').status_code==404;assert c.get('/ir35/by-request/2').status_code==200
 a[0]=u[3];assert c.get('/ir35/by-request/1').status_code==200
 assert c.put('/ir35/by-request/1',json=dict(expected_revision=2,answers={'fake':'yes'})).status_code==422
 assert c.put('/ir35/by-request/1',json=dict(expected_revision=2,answers={'personal':'outside'})).status_code==422

def test_private_attachment_access_and_validation(ctx):
 c,s,a,u,objects=ctx
 pdf=b'%PDF-1.4\nTest only\n%%EOF'
 assert c.post('/ir35/by-request/1/cest',files={'file':('result.pdf',b'not a pdf','application/pdf')}).status_code==422
 assert c.post('/ir35/by-request/1/cest',files={'file':('result.pdf',b'%PDF-'+b'x'*(5*1024*1024),'application/pdf')}).status_code==422
 r=c.post('/ir35/by-request/1/cest',files={'file':('result.pdf',pdf,'application/pdf')});assert r.status_code==200,r.text
 assert 'key' not in r.text and len(objects)==1
 aid=r.json()['attachments'][0]['id'];path=f'/ir35/by-request/1/cest/{aid}'
 d=c.get(path);assert d.content==pdf and d.headers['content-disposition'].startswith('attachment') and d.headers['cache-control']=='private, no-store'
 assert c.get(f'/ir35/by-request/2/cest/{aid}').status_code==404
 a[0]=u[2];assert c.get(path).status_code==404
 assert c.post('/ir35/by-request/1/cest',files={'file':('x.pdf',pdf,'application/pdf')}).status_code==404
 a[0]=u[0];assert c.get(path).status_code==200

def test_storage_failure_does_not_record_attachment(ctx,monkeypatch):
 c,s,a,u,_=ctx
 def fail():raise RuntimeError('Unavailable')
 monkeypatch.setattr(ir35,'r2_client',fail)
 assert c.post('/ir35/by-request/1/cest',files={'file':('result.pdf',b'%PDF-1.4\n%%EOF','application/pdf')}).status_code==503
 assert not s.exec(select(IR35Attachment)).all()

def test_guidance_is_not_a_status_decision():
 a={q[0]:'no' for q in QUESTIONS};a['intermediary']='yes'
 g=guidance(a);assert 'confirm status separately' in g['status']
 a.update(personal='yes',substitute='yes');assert guidance(a)['conflicts']
 assert guidance({})['status']=='Further review required'
 assert 'score' not in g and 'determination' not in g
