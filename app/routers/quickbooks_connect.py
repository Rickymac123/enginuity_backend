import hashlib, secrets, os
from datetime import datetime,timedelta
from urllib.parse import urlencode
import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select
from app.db import get_session
from auth.deps import require_admin
from auth.models import User
from models.work_billing import QuickBooksFlow,QuickBooksConnection
from app.quickbooks_work import cipher
router=APIRouter(prefix='/work-billing/quickbooks',tags=['admin'])
@router.get('/connect')
def connect(admin:User=Depends(require_admin),session:Session=Depends(get_session)):
    if not all(os.getenv(k) for k in ('QBO_CLIENT_ID','QBO_CLIENT_SECRET','QBO_REDIRECT_URI','QBO_TOKEN_ENCRYPTION_KEY','QBO_REALM_ID')):raise HTTPException(503,'Intuit app configuration is required before connecting')
    state=secrets.token_urlsafe(32)
    session.add(QuickBooksFlow(state_hash=hashlib.sha256(state.encode()).hexdigest(),admin_id=admin.id,expires_at=datetime.utcnow()+timedelta(minutes=10)));session.commit()
    return {'url':'https://appcenter.intuit.com/connect/oauth2?'+urlencode({'client_id':os.environ['QBO_CLIENT_ID'],'redirect_uri':os.environ['QBO_REDIRECT_URI'],'scope':'com.intuit.quickbooks.accounting','response_type':'code','state':state})}
@router.get('/callback')
def callback(state:str,code:str='',realmId:str='',error:str='',admin:User=Depends(require_admin),session:Session=Depends(get_session)):
    flow=session.exec(select(QuickBooksFlow).where(QuickBooksFlow.state_hash==hashlib.sha256(state.encode()).hexdigest()).with_for_update()).first()
    if not flow or flow.admin_id!=admin.id or flow.expires_at<datetime.utcnow():raise HTTPException(400,'Connection request expired; start again')
    session.delete(flow);session.commit()
    if error or not code:raise HTTPException(400,'QuickBooks connection was not authorised')
    if realmId!=os.environ['QBO_REALM_ID']:raise HTTPException(400,'Select the configured RMC QuickBooks company')
    r=httpx.post('https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer',auth=(os.environ['QBO_CLIENT_ID'],os.environ['QBO_CLIENT_SECRET']),data={'grant_type':'authorization_code','code':code,'redirect_uri':os.environ['QBO_REDIRECT_URI']},timeout=20)
    if not r.is_success:raise HTTPException(502,'QuickBooks connection failed; start again')
    d=r.json();row=session.get(QuickBooksConnection,1) or QuickBooksConnection(realm_id=realmId,encrypted_refresh_token='',encrypted_access_token='',expires_at=datetime.utcnow())
    row.realm_id=realmId;row.encrypted_refresh_token=cipher().encrypt(d['refresh_token'].encode()).decode();row.encrypted_access_token=cipher().encrypt(d['access_token'].encode()).decode();row.expires_at=datetime.utcnow()+timedelta(seconds=d['expires_in']);session.add(row);session.commit()
    return RedirectResponse(os.getenv('FRONTEND_BASE_URL','https://www.contractpros.co.uk')+'/dashboard/timesheets?connected=1',status_code=303)
