from datetime import datetime, timedelta
import hashlib
from urllib.parse import urlparse, parse_qs
from cryptography.fernet import Fernet
from tests.test_work_billing import context
from app.routers import quickbooks_connect as q
from models.work_billing import QuickBooksConnection, QuickBooksFlow


def setup(context,monkeypatch):
    c,s,a,u=context
    c.app.include_router(q.router)
    for key,value in {'QBO_CLIENT_ID':'test-client','QBO_CLIENT_SECRET':'test-secret','QBO_REDIRECT_URI':'http://localhost/callback','QBO_TOKEN_ENCRYPTION_KEY':Fernet.generate_key().decode(),'QBO_REALM_ID':'test-realm'}.items():monkeypatch.setenv(key,value)
    return c,s,a,u


def test_oauth_admin_state_expiry_and_realm(context,monkeypatch):
    c,s,a,u=setup(context,monkeypatch)
    def forbidden(*args,**kwargs):raise AssertionError('Invalid OAuth request reached provider')
    monkeypatch.setattr(q.httpx,'post',forbidden)
    assert c.get('/work-billing/quickbooks/connect').status_code==403
    a[0]=u[3]
    response=c.get('/work-billing/quickbooks/connect')
    state=parse_qs(urlparse(response.json()['url']).query)['state'][0]
    key=hashlib.sha256(state.encode()).hexdigest()
    assert s.get(QuickBooksFlow,key).admin_id==u[3].id
    assert c.get('/work-billing/quickbooks/callback',params={'state':'wrong','code':'unused','realmId':'test-realm'}).status_code==400
    assert c.get('/work-billing/quickbooks/callback',params={'state':state,'code':'unused','realmId':'wrong'}).status_code==400
    assert not s.get(QuickBooksFlow,key)
    assert not s.get(QuickBooksConnection,1)
    expired='expired'
    s.add(QuickBooksFlow(state_hash=hashlib.sha256(expired.encode()).hexdigest(),admin_id=u[3].id,expires_at=datetime.utcnow()-timedelta(seconds=1)));s.commit()
    assert c.get('/work-billing/quickbooks/callback',params={'state':expired,'code':'unused','realmId':'test-realm'}).status_code==400


def test_oauth_tokens_encrypted_and_state_single_use(context,monkeypatch):
    c,s,a,u=setup(context,monkeypatch);a[0]=u[3]
    state=parse_qs(urlparse(c.get('/work-billing/quickbooks/connect').json()['url']).query)['state'][0]
    class Response:
        is_success=True
        def json(self):return {'access_token':'synthetic-access','refresh_token':'synthetic-refresh','expires_in':3600}
    calls=[]
    def exchange(*args,**kwargs):calls.append(1);return Response()
    monkeypatch.setattr(q.httpx,'post',exchange)
    params={'state':state,'code':'synthetic-code','realmId':'test-realm'}
    assert c.get('/work-billing/quickbooks/callback',params=params,follow_redirects=False).status_code==303
    row=s.get(QuickBooksConnection,1)
    assert row.encrypted_access_token!='synthetic-access'
    assert q.cipher().decrypt(row.encrypted_refresh_token.encode()).decode()=='synthetic-refresh'
    assert c.get('/work-billing/quickbooks/callback',params=params).status_code==400
    assert len(calls)==1
