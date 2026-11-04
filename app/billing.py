"""Server-owned subscription catalogue and access rules. Disabled until Stripe is verified."""
import os
from datetime import datetime
from fastapi import Depends, HTTPException
from sqlmodel import Session
from app.db import get_session
from auth.deps import current_user
from auth.models import User
from models.billing import BillingAccount, LaunchRedemption

AMOUNTS = {'company': {'month':2900,'year':29000}, 'agency':{'month':5900,'year':59000}}

def enabled(): return os.getenv('BILLING_ENABLED','false').lower() == 'true'
def price_id(role, interval): return os.getenv(f'STRIPE_PRICE_{role.upper()}_{interval.upper()}', '')
def ready():
    if os.getenv('STRIPE_MODE','test') == 'live' and os.getenv('STRIPE_UK_RESTRICTIONS_VERIFIED','false').lower() != 'true':
        return False
    return enabled() and os.getenv('STRIPE_MODE','test') in ('test','live') and os.getenv('STRIPE_SECRET_KEY','').startswith('sk_'+os.getenv('STRIPE_MODE','test')+'_') and bool(os.getenv('STRIPE_SECRET_KEY') and os.getenv('STRIPE_WEBHOOK_SECRET') and os.getenv('STRIPE_PORTAL_COMPANY') and os.getenv('STRIPE_PORTAL_AGENCY') and os.getenv('STRIPE_UK_VAT_RATE')) and all(price_id(r,i) for r in AMOUNTS for i in ('month','year'))

def access(session, user):
    now=datetime.utcnow()
    if user.role not in AMOUNTS: return 'free'
    if not enabled(): return 'setup'
    grant=session.get(LaunchRedemption,user.id)
    if grant and grant.expires_at > now:return 'founder'
    account=session.get(BillingAccount,user.id)
    if account and account.status=='active' and account.paid_until and account.paid_until>now:return 'paid'
    return 'subscription_required'

def require_subscription(user:User=Depends(current_user), session:Session=Depends(get_session)):
    if access(session,user)=='subscription_required':
        raise HTTPException(402, detail='Choose a plan or redeem FOUNDERS100 at Billing. Existing booking management and history remain available.')
    return user
