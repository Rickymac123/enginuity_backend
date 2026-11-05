"""Real PostgreSQL concurrency coverage for the shared founders quota."""
import os,uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from fastapi import FastAPI,Request,Depends
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlmodel import SQLModel,Session,create_engine,select
from auth.models import User
from auth.deps import current_user
from app.db import get_session
from app.routers.billing import router
from models.company import Company
from models.billing import LaunchOffer,LaunchRedemption
from scripts.prepare_launch import migrate

@pytest.mark.skipif(os.getenv('CONTRACTPROS_POSTGRES_TESTS')!='1',reason='Disposable PostgreSQL not configured')
@pytest.mark.parametrize('same_business',[False,True])
def test_founders_concurrent_redemptions(monkeypatch,same_business):
 url=os.environ['TEST_POSTGRES_URL'];assert make_url(url).host in {'localhost','127.0.0.1','postgres'}
 monkeypatch.setenv('BILLING_ENABLED','true');schema='test_'+uuid.uuid4().hex;admin=create_engine(url)
 with admin.begin() as c:c.execute(text(f'CREATE SCHEMA {schema}'))
 engine=create_engine(url,connect_args={'options':f'-csearch_path={schema}'})
 try:
  SQLModel.metadata.create_all(engine);migrate(engine)
  with Session(engine) as s:
   for i in [1,2]:s.add(User(id=i,email=f'{i}@example.com',hashed_password='unused',role='agency',is_active=True,is_verified=True))
   s.commit()
   for i in [1,2]:s.add(Company(owner_id=i,name=f'Business {i}',registration_number='SAME' if same_business else str(i)))
   offer=s.get(LaunchOffer,'FOUNDERS100');offer.redeemed=0 if same_business else 99;s.add(offer);s.commit()
  app=FastAPI();app.include_router(router)
  def db():
   with Session(engine) as s:yield s
  def who(request:Request,s:Session=Depends(get_session)):return s.get(User,int(request.headers['x-test-user']))
  app.dependency_overrides[get_session]=db;app.dependency_overrides[current_user]=who;barrier=Barrier(2)
  def redeem(i):
   with TestClient(app) as client:
    barrier.wait(timeout=10)
    return client.post('/billing/redeem',json={'code':'FOUNDERS100'},headers={'x-test-user':str(i)}).status_code
  with ThreadPoolExecutor(max_workers=2) as pool:result=list(pool.map(redeem,[1,2]))
  assert sorted(result)==[200,409]
  with Session(engine) as s:
   assert len(s.exec(select(LaunchRedemption)).all())==1
   assert s.get(LaunchOffer,'FOUNDERS100').redeemed==(1 if same_business else 100)
 finally:
  engine.dispose()
  with admin.begin() as c:c.execute(text(f'DROP SCHEMA {schema} CASCADE'))
  admin.dispose()
