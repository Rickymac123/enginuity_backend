import os, json, time, hmac, hashlib
from datetime import datetime, timedelta
import pytest
from sqlmodel import select
from tests.test_agency_assurance import agency_context
from models.billing import BillingAccount, LaunchOffer, LaunchRedemption, BillingEvent
from models.company import Company
from app.routers import billing
from app.billing import access

@pytest.fixture
def ctx(agency_context,monkeypatch):
 c,s,active,users=agency_context;c.app.include_router(billing.router)
 monkeypatch.setenv('BILLING_ENABLED','true')
 s.add(LaunchOffer(code='FOUNDERS100'));s.add(Company(postcode='CF48 3PN',owner_id=1,name='Agency One',registration_number='12345678'));s.add(Company(postcode='CF48 3PN',owner_id=2,name='Company Two'));s.commit()
 return c,s,active,users

def configured(monkeypatch):
 for k in ['STRIPE_SECRET_KEY','STRIPE_WEBHOOK_SECRET','STRIPE_PORTAL_COMPANY','STRIPE_PORTAL_AGENCY','STRIPE_UK_VAT_RATE']:
  monkeypatch.setenv(k,'test-only')
 for role in ['company','agency']:
  for interval in ['month','year']:monkeypatch.setenv(f'STRIPE_PRICE_{role.upper()}_{interval.upper()}',f'price_{role}_{interval}')
 monkeypatch.setenv('STRIPE_MODE','test')
 monkeypatch.setenv('STRIPE_SECRET_KEY','sk_test_local_fake')

def test_offer_once_shared_cap_and_expiry(ctx):
 c,s,a,u=ctx
 assert c.post('/billing/redeem',json={'uk_business':True,'code':'bad'}).status_code==400
 assert c.post('/billing/redeem',json={'uk_business':True,'code':' founders100 '}).json()['access']=='founder'
 assert c.post('/billing/redeem',json={'uk_business':True,'code':'FOUNDERS100'}).status_code==409
 grant=s.get(LaunchRedemption,1);assert 89<(grant.expires_at-datetime.utcnow()).days<93
 grant.expires_at=datetime.utcnow()-timedelta(seconds=1);s.add(grant);s.commit()
 assert access(s,u[0])=='subscription_required'
 assert c.get('/agency/booking-requests').status_code==200
 assert c.post('/talent/',json={}).status_code==402
 offer=s.get(LaunchOffer,'FOUNDERS100');offer.redeemed=100;s.add(offer);s.commit();a[0]=u[1]
 assert c.post('/billing/redeem',json={'uk_business':True,'code':'FOUNDERS100'}).status_code==409
 assert s.get(LaunchOffer,'FOUNDERS100').redeemed==100

def test_duplicate_business_not_double_counted(ctx):
 c,s,a,u=ctx
 assert c.post('/billing/redeem',json={'uk_business':True,'code':'FOUNDERS100'}).status_code==200
 a[0]=u[2];s.add(Company(postcode='CF48 3PN',owner_id=3,name='Different trading name',registration_number='12345678'));s.commit()
 assert c.post('/billing/redeem',json={'uk_business':True,'code':'FOUNDERS100'}).status_code==409
 assert s.get(LaunchOffer,'FOUNDERS100').redeemed==1

def test_disabled_rollout_and_free_professional(ctx,monkeypatch):
 c,s,a,u=ctx;monkeypatch.setenv('BILLING_ENABLED','false')
 assert c.get('/billing/status').json()['access']=='setup'
 assert c.post('/billing/redeem',json={'uk_business':True,'code':'FOUNDERS100'}).status_code==503
 assert c.post('/billing/checkout',json={'uk_business':True,'terms_accepted':True,'interval':'month'}).status_code==503
 a[0].role='professional';s.add(a[0]);s.commit()
 assert c.get('/billing/status').json()['access']=='free'
 assert c.post('/billing/redeem',json={'uk_business':True,'code':'FOUNDERS100'}).status_code==403

def test_paid_access_expiry_failure_and_cancellation(ctx):
 c,s,a,u=ctx
 account=BillingAccount(user_id=1,status='active',paid_until=datetime.utcnow()+timedelta(days=3),cancel_at_period_end=True)
 s.add(account);s.commit();assert access(s,u[0])=='paid'
 for status in ['past_due','unpaid','incomplete','canceled']:
  account.status=status;s.add(account);s.commit();assert access(s,u[0])=='subscription_required'
 account.status='active';account.paid_until=datetime.utcnow()-timedelta(seconds=1);s.add(account);s.commit();assert access(s,u[0])=='subscription_required'

def test_checkout_server_prices_customer_binding_and_duplicate(ctx,monkeypatch):
 c,s,a,u=ctx;configured(monkeypatch);calls=[]
 def fake(method,path,data=None,key=None):
  calls.append((method,path,data,key))
  if path.startswith('prices/'):return {'id':'price_agency_year','currency':'gbp','unit_amount':59000,'active':True,'tax_behavior':'exclusive','recurring':{'interval':'year','interval_count':1}}
  if path.startswith('tax_rates/'):return {'id':'txr_uk','percentage':20,'inclusive':False,'country':'GB','active':True}
  if path=='customers':
   assert data['metadata[contractpros]']=='true'
   return {'id':'cus_one'}
  if path=='customers/cus_one':
   assert data=={'metadata[contractpros]':'true'}
   return {'id':'cus_one'}
  if path.startswith('subscriptions?'):return {'data':[]}
  if method=='GET' and path.startswith('checkout/sessions/'):return {'status':'open','url':'https://checkout.stripe.com/test','metadata':{'interval':'year'}}
  if path=='checkout/sessions':return {'id':'cs_one','url':'https://checkout.stripe.com/test','expires_at':int(time.time())+1800}
  raise AssertionError(path)
 monkeypatch.setattr(billing,'stripe',fake)
 assert c.post('/billing/checkout',json={'uk_business':True,'terms_accepted':True,'interval':'week','price':'fake'}).status_code==422
 assert c.post('/billing/checkout',json={'uk_business':True,'terms_accepted':True,'interval':'year','customer':'cus_someone_else','price':'fake'}).status_code==200
 payload=next(x[2] for x in calls if x[1]=='checkout/sessions')
 assert payload['customer']=='cus_one' and payload['line_items[0][price]']=='price_agency_year'
 assert payload['line_items[0][tax_rates][0]']=='txr_uk'
 assert c.post('/billing/checkout',json={'uk_business':True,'terms_accepted':True,'interval':'year'}).status_code==200
 assert sum(x[0]=='POST' and x[1]=='checkout/sessions' for x in calls)==1
 assert c.post('/billing/checkout',json={'uk_business':True,'terms_accepted':True,'interval':'month'}).status_code==409

def test_founder_cannot_be_charged_during_free_access(ctx,monkeypatch):
 c,s,a,u=ctx;configured(monkeypatch)
 assert c.post('/billing/redeem',json={'uk_business':True,'code':'FOUNDERS100'}).status_code==200
 monkeypatch.setattr(billing,'stripe',lambda *a,**k:pytest.fail('No Stripe call during free access'))
 assert c.post('/billing/checkout',json={'uk_business':True,'terms_accepted':True,'interval':'month'}).status_code==409

def signed(c,event,stamp=None):
 raw=json.dumps(event).encode();t=str(stamp or int(time.time()));sig=hmac.new(b'test-only',t.encode()+b'.'+raw,hashlib.sha256).hexdigest()
 return c.post('/billing/webhook',content=raw,headers={'stripe-signature':f't={t},v1={sig}','content-type':'application/json'})

def test_webhook_signature_idempotence_and_latest_state(ctx,monkeypatch):
 c,s,a,u=ctx;configured(monkeypatch)
 s.add(BillingAccount(user_id=1,customer_id='cus_one'));s.commit()
 sub={'id':'sub_one','customer':'cus_one','status':'active','created':1,'items':{'data':[{'price':{'id':'price_agency_month'},'current_period_end':int(time.time())+86400}]}}
 calls=[]
 def fake(*args,**kwargs):calls.append(args);return {'data':[sub]}
 monkeypatch.setattr(billing,'stripe',fake)
 event={'id':'evt_one','livemode':False,'type':'customer.subscription.updated','data':{'object':{'customer':'cus_one','status':'canceled'}}}
 assert c.post('/billing/webhook',json=event).status_code==400
 assert signed(c,event,int(time.time())-600).status_code==400
 assert signed(c,event).status_code==200
 assert access(s,u[0])=='paid'
 assert signed(c,event).status_code==200 and len(calls)==1
 sub['status']='canceled';event['id']='evt_older';event['data']['object']['status']='active'
 assert signed(c,event).status_code==200 and access(s,u[0])=='subscription_required'
 assert len(s.exec(select(BillingEvent)).all())==2
 event['livemode']=True;assert signed(c,event).status_code==400

def test_portal_never_uses_customer_from_browser(ctx,monkeypatch):
 c,s,a,u=ctx;configured(monkeypatch);s.add(BillingAccount(user_id=1,customer_id='cus_one'));s.commit()
 def fake(method,path,data,key=None):
  assert data['customer']=='cus_one';return {'url':'https://billing.stripe.com/test'}
 monkeypatch.setattr(billing,'stripe',fake)
 assert c.post('/billing/portal',json={'customer':'cus_someone_else'}).status_code==200
 a[0]=u[1];assert c.post('/billing/portal',json={}).status_code==409

def test_checkout_timeout_reuses_persisted_attempt(ctx,monkeypatch):
 from fastapi import HTTPException
 c,s,a,u=ctx;configured(monkeypatch);attempts=[]
 def fake(method,path,data=None,key=None):
  if path.startswith('prices/'):return {'id':'price_agency_month','currency':'gbp','unit_amount':5900,'active':True,'tax_behavior':'exclusive','recurring':{'interval':'month','interval_count':1}}
  if path.startswith('tax_rates/'):return {'id':'txr_uk','percentage':20,'inclusive':False,'country':'GB','active':True}
  if path=='customers':
   assert data['metadata[contractpros]']=='true'
   return {'id':'cus_one'}
  if path=='customers/cus_one':
   assert data=={'metadata[contractpros]':'true'}
   return {'id':'cus_one'}
  if path.startswith('subscriptions?'):return {'data':[]}
  if path=='checkout/sessions':
   attempts.append((key,data.copy()))
   if len(attempts)==1:raise HTTPException(502,'simulated timeout')
   return {'id':'cs_one','url':'https://checkout.stripe.com/test','expires_at':int(data['expires_at'])}
  raise AssertionError(path)
 monkeypatch.setattr(billing,'stripe',fake)
 body={'interval':'month','uk_business':True,'terms_accepted':True}
 assert c.post('/billing/checkout',json=body).status_code==502;s.rollback()
 assert c.post('/billing/checkout',json=body).status_code==200
 assert attempts[0]==attempts[1]

def test_reminders_are_once_and_never_charge(ctx,monkeypatch):
 from app import notifications
 c,s,a,u=ctx
 s.add(LaunchRedemption(user_id=1,business_key='sample',expires_at=datetime.utcnow()+timedelta(days=6)));s.commit()
 monkeypatch.setattr(notifications,'send_email',lambda *a:None)
 assert notifications.deliver_pending(s)['sent']==1
 assert notifications.deliver_pending(s)['sent']==0
 grant=s.get(LaunchRedemption,1);grant.expires_at=datetime.utcnow()-timedelta(seconds=1);s.add(grant);s.commit()
 assert notifications.deliver_pending(s)['sent']==1
 assert s.get(BillingAccount,1) is None


def test_live_checkout_accepts_any_card_country_with_rollout_gate(ctx,monkeypatch):
 from app.billing import ready
 configured(monkeypatch)
 monkeypatch.setenv('STRIPE_MODE','live')
 monkeypatch.setenv('STRIPE_SECRET_KEY','sk_live_fake_local_only')
 monkeypatch.delenv('STRIPE_UK_RESTRICTIONS_VERIFIED',raising=False)
 assert ready()
 monkeypatch.setenv('BILLING_ENABLED','false')
 assert not ready()

def test_pending_checkout_cannot_claim_free_offer(ctx):
 c,s,a,u=ctx
 s.add(BillingAccount(user_id=1,checkout_attempt='pending'));s.commit()
 assert c.post('/billing/redeem',json={'uk_business':True,'code':'FOUNDERS100'}).status_code==409
 assert s.get(LaunchOffer,'FOUNDERS100').redeemed==0
