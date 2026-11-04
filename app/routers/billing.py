"""Hosted Stripe Checkout/Portal. No card data passes through ContractPros."""
import os, time, json, hmac, hashlib, re
from uuid import uuid4
from datetime import datetime
from urllib.parse import quote
import httpx
from dateutil.relativedelta import relativedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, StrictBool
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select
from app.db import get_session
from auth.deps import current_user, require_role
from auth.models import User
from models.company import Company
from models.billing import BillingAccount, LaunchOffer, LaunchRedemption, BillingEvent
from app.billing import AMOUNTS, enabled, ready, price_id, access
from app.notifications import enqueue

router=APIRouter(prefix='/billing',tags=['billing'])
BASE='https://www.contractpros.co.uk'

class CheckoutInput(BaseModel):
    interval: str
    uk_business: StrictBool = False
    terms_accepted: StrictBool = False
class CodeInput(BaseModel):
    code: str

def stripe(method,path,data=None,key=None):
    secret=os.getenv('STRIPE_SECRET_KEY','')
    if not secret: raise HTTPException(503,'Billing is not connected yet.')
    headers={'Authorization':f'Bearer {secret}','Stripe-Version':'2025-04-30.basil'}
    if key:headers['Idempotency-Key']=key
    try:
        r=httpx.request(method,'https://api.stripe.com/v1/'+path,headers=headers,data=data,timeout=20)
        if not r.is_success:raise HTTPException(502,'Stripe could not complete this request. Please try again or contact support.')
        return r.json()
    except httpx.HTTPError:raise HTTPException(502,'Stripe is temporarily unavailable. Please retry.')

def throttle(session,user,action):
    from app.rate_limits import consume
    if not consume(session,f'billing:{action}:{user.id}',20):raise HTTPException(429,'Please wait a few minutes before trying billing again.')

def locked_account(session,user):
    # Lock an existing row before creating the one-to-one billing record.
    session.exec(select(User).where(User.id==user.id).with_for_update()).one()
    account=session.exec(select(BillingAccount).where(BillingAccount.user_id==user.id).with_for_update()).first()
    if not account:account=BillingAccount(user_id=user.id);session.add(account);session.flush()
    return account

def sync_subscription(session,account,sub):
    if sub.get('customer')!=account.customer_id:raise HTTPException(400,'Subscription customer mismatch')
    owner=session.get(User,account.user_id)
    items=sub.get('items',{}).get('data',[])
    item=items[0] if len(items)==1 else {}
    pid=item.get('price',{}).get('id')
    interval=next((i for i in ('month','year') if pid and pid==price_id(owner.role,i)),None)
    if not interval:raise HTTPException(409,'Subscription price is not configured for this account')
    account.subscription_id=sub['id'];account.status=sub['status'];account.interval=interval
    end=item.get('current_period_end') or sub.get('current_period_end')
    account.paid_until=datetime.utcfromtimestamp(end) if end else None
    account.cancel_at_period_end=bool(sub.get('cancel_at_period_end'))
    session.add(account)

def reconcile(session,account):
    if not account.customer_id:return
    # Latest Stripe state, not event payload order; prevents stale events restoring access.
    result=stripe('GET',f'subscriptions?customer={quote(account.customer_id)}&status=all&limit=100')
    if result.get('has_more'):raise HTTPException(503,'Billing reconciliation needs support review')
    subs=sorted(result.get('data',[]),key=lambda s:s.get('created',0),reverse=True)
    sub=next((s for s in subs if s.get('status') in ('active','trialing','past_due','unpaid','incomplete','paused')),None)
    if not sub:sub=next((s for s in subs if s['id']==account.subscription_id),None)
    if sub:sync_subscription(session,account,sub)

def public_status(session,user):
    a=session.get(BillingAccount,user.id);g=session.get(LaunchRedemption,user.id)
    return {'role':user.role,'access':access(session,user),'enabled':enabled(),'checkout_ready':ready(),
      'status':a.status if a else 'none','interval':a.interval if a else None,
      'paid_until':a.paid_until if a else None,'cancel_at_period_end':a.cancel_at_period_end if a else False,
      'founder_expires':g.expires_at if g else None,'founder_redeemed':bool(g),
      'can_manage':bool(a and a.customer_id and ready()),'prices':AMOUNTS.get(user.role,{}),'vat_percent':20}

@router.get('/status')
def status(user:User=Depends(current_user),session:Session=Depends(get_session)):
    return public_status(session,user)

@router.post('/refresh')
def refresh(user:User=Depends(require_role('company','agency')),session:Session=Depends(get_session)):
    throttle(session,user,'refresh')
    if ready():
        a=locked_account(session,user);reconcile(session,a);session.commit()
    return public_status(session,user)

@router.post('/redeem')
def redeem(body:CodeInput,user:User=Depends(require_role('company','agency')),session:Session=Depends(get_session)):
    throttle(session,user,'redeem')
    if not enabled():raise HTTPException(503,'The launch offer is not open yet.')
    if body.code.strip().upper()!='FOUNDERS100':raise HTTPException(400,'That launch code is not valid.')
    account=locked_account(session,user)
    if session.get(LaunchRedemption,user.id):raise HTTPException(409,'This account has already used the launch offer.')
    if account.subscription_id or account.checkout_id or account.checkout_attempt:raise HTTPException(409,'Contact support before redeeming an offer after starting checkout.')
    profile=session.exec(select(Company).where(Company.owner_id==user.id)).first()
    if not profile or not profile.name.strip():raise HTTPException(409,'Save your business profile before redeeming the launch code.')
    business='number:'+re.sub(r'\W','',profile.registration_number or '').upper() if profile.registration_number else 'name:'+re.sub(r'\W','',profile.name).casefold()
    key=hashlib.sha256(business.encode()).hexdigest()
    if session.exec(select(LaunchRedemption).where(LaunchRedemption.business_key==key)).first():raise HTTPException(409,'This business has already used the launch offer.')
    result=session.execute(update(LaunchOffer).where(LaunchOffer.code=='FOUNDERS100',LaunchOffer.redeemed<LaunchOffer.capacity).values(redeemed=LaunchOffer.redeemed+1))
    if result.rowcount!=1:raise HTTPException(409,'All 100 launch places have been claimed.')
    end=datetime.utcnow()+relativedelta(months=3)
    session.add(LaunchRedemption(user_id=user.id,business_key=key,expires_at=end))
    enqueue(session,f'founder-start:{user.id}',user.id,'Your ContractPros launch access is active',f'Your free launch access ends on {end:%d %B %Y}. No card was collected and you will not be charged automatically.','/dashboard/billing')
    try:session.commit()
    except IntegrityError:session.rollback();raise HTTPException(409,'This business has already used the launch offer.')
    return public_status(session,user)

@router.post('/checkout')
def checkout(body:CheckoutInput,user:User=Depends(require_role('company','agency')),session:Session=Depends(get_session)):
    throttle(session,user,'checkout')
    if not ready():raise HTTPException(503,'Payments are being connected. Please check back shortly.')
    if not body.uk_business or not body.terms_accepted:raise HTTPException(422,'Confirm that you represent a UK business and accept the subscription terms.')
    if body.interval not in ('month','year'):raise HTTPException(422,'Choose monthly or annual billing.')
    a=locked_account(session,user)
    grant=session.get(LaunchRedemption,user.id)
    if grant and grant.expires_at>datetime.utcnow():raise HTTPException(409,'Enjoy your free access first. Choose a paid plan when it ends.')
    if a.customer_id:reconcile(session,a)
    if a.status in ('active','trialing','past_due','unpaid','incomplete','paused'):raise HTTPException(409,'Manage your existing subscription instead of creating another one.')
    if a.checkout_id:
        old=stripe('GET','checkout/sessions/'+quote(a.checkout_id))
        if old.get('status')=='open':
            if old.get('metadata',{}).get('interval')!=body.interval:raise HTTPException(409,'A checkout is already open. Finish it or wait one hour before choosing another interval.')
            return {'url':old['url']}
        if old.get('status')=='complete' and a.status not in ('canceled','incomplete_expired'):
            reconcile(session,a);session.commit()
            raise HTTPException(409,'Checkout completed. Refresh your billing status.')
        a.checkout_attempt=None;a.checkout_id=None;a.checkout_expires=None
    price=stripe('GET','prices/'+quote(price_id(user.role,body.interval)))
    if price.get('currency')!='gbp' or price.get('unit_amount')!=AMOUNTS[user.role][body.interval] or price.get('recurring',{}).get('interval')!=body.interval or price.get('recurring',{}).get('interval_count')!=1 or not price.get('active') or price.get('tax_behavior')!='exclusive':raise HTTPException(503,'Billing price configuration needs attention.')
    tax=stripe('GET','tax_rates/'+quote(os.environ['STRIPE_UK_VAT_RATE']))
    if tax.get('percentage')!=20 or tax.get('inclusive') or not tax.get('active') or tax.get('country')!='GB':raise HTTPException(503,'VAT configuration needs attention.')
    if not a.customer_id:
        customer=stripe('POST','customers',{'email':user.email,'metadata[user_id]':str(user.id)},f'contractpros-customer-{user.id}')
        a.customer_id=customer['id'];session.add(a);session.flush()
    if a.checkout_attempt and a.checkout_expires and a.checkout_expires>datetime.utcnow():
        if a.checkout_interval!=body.interval:raise HTTPException(409,'An earlier checkout is still being prepared. Retry the same plan or wait for it to expire.')
    else:
        from datetime import timedelta
        a.checkout_attempt=uuid4().hex;a.checkout_interval=body.interval
        a.checkout_expires=datetime.utcnow()+timedelta(hours=1)
    # Persist the attempt before the external side effect: timeout/retry uses the same key.
    session.add(a);session.commit();a=locked_account(session,user)
    payload={'mode':'subscription','customer':a.customer_id,'client_reference_id':str(user.id),
      'line_items[0][price]':price['id'],'line_items[0][quantity]':'1','line_items[0][tax_rates][0]':tax['id'],
      'metadata[interval]':body.interval,'subscription_data[metadata][user_id]':str(user.id),'subscription_data[metadata][terms_version]':'2026-11-03','subscription_data[metadata][uk_business]':'true',
      'billing_address_collection':'required','payment_method_types[0]':'card',
      'success_url':BASE+'/dashboard/billing?checkout=success','cancel_url':BASE+'/dashboard/billing?checkout=cancelled',
      'expires_at':str(int(time.time())+1800)}
    payload['expires_at']=str(int(a.checkout_expires.replace(tzinfo=__import__('datetime').timezone.utc).timestamp()))
    out=stripe('POST','checkout/sessions',payload,f'contractpros-checkout-{user.id}-{a.checkout_attempt}')
    a.checkout_id=out['id'];a.checkout_url=out['url'];a.checkout_expires=datetime.utcfromtimestamp(out['expires_at'])
    session.add(a);session.commit();return {'url':out['url']}

@router.post('/portal')
def portal(user:User=Depends(require_role('company','agency')),session:Session=Depends(get_session)):
    throttle(session,user,'portal')
    a=session.get(BillingAccount,user.id)
    if not ready() or not a or not a.customer_id:raise HTTPException(409,'There is no connected billing account to manage yet.')
    return {'url':stripe('POST','billing_portal/sessions',{'customer':a.customer_id,'configuration':os.environ[f'STRIPE_PORTAL_{user.role.upper()}'],'return_url':BASE+'/dashboard/billing'})['url']}

@router.post('/webhook')
async def webhook(request:Request,session:Session=Depends(get_session)):
    secret=os.getenv('STRIPE_WEBHOOK_SECRET','')
    if not secret:raise HTTPException(503,'Webhook is not configured')
    raw=await request.body()
    if len(raw)>1048576:raise HTTPException(413,'Payload too large')
    try:
        parts=[p.split('=',1) for p in request.headers.get('stripe-signature','').split(',')]
        stamp=next(v for k,v in parts if k=='t')
        expected=hmac.new(secret.encode(),stamp.encode()+b'.'+raw,hashlib.sha256).hexdigest()
        if abs(time.time()-int(stamp))>300 or not any(k=='v1' and hmac.compare_digest(v,expected) for k,v in parts):raise ValueError()
        event=json.loads(raw)
    except (ValueError,StopIteration,TypeError):raise HTTPException(400,'Invalid webhook signature')
    if event.get('livemode')!=(os.getenv('STRIPE_MODE','test')=='live'):raise HTTPException(400,'Webhook mode mismatch')
    if not event.get('id'):raise HTTPException(400,'Missing event identifier')
    from starlette.concurrency import run_in_threadpool
    return await run_in_threadpool(process_event,session,event)

def process_event(session,event):
    obj=event.get('data',{}).get('object',{})
    customer=obj.get('customer')
    if event.get('type','').startswith(('customer.subscription.','checkout.session.','invoice.')) and customer:
        account=session.exec(select(BillingAccount).where(BillingAccount.customer_id==customer).with_for_update()).first()
        if not account:return {'received':True} # Unrelated customers in a shared Stripe account.
        if session.get(BillingEvent,event['id']):return {'received':True}
        reconcile(session,account)
        session.add(BillingEvent(event_id=event['id']));session.commit()
    return {'received':True}
