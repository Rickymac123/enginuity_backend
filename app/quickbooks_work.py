"""Server-side QuickBooks adapter; default-off, GBP only, no contractor payments."""
import json, os
from datetime import datetime, timedelta
from decimal import Decimal
from urllib.parse import quote
import httpx
from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlmodel import select
from models.work_billing import QuickBooksConnection, WorkInvoice
from app.work_billing import pence

def cipher():return Fernet(os.environ['QBO_TOKEN_ENCRYPTION_KEY'].encode())
def configured(session):
    return os.getenv('WORK_INVOICING_ENABLED')=='true' and os.getenv('QBO_ENVIRONMENT') in ('sandbox','production') and all(os.getenv(k) for k in ('QBO_CLIENT_ID','QBO_CLIENT_SECRET','QBO_TOKEN_ENCRYPTION_KEY','QBO_REALM_ID','QBO_SERVICE_ITEM_ID','QBO_SALES_TAX_CODE_ID')) and bool(session.get(QuickBooksConnection,1))

class QBO:
    def __init__(self,session):self.session=session
    def token(self):
        row=self.session.exec(select(QuickBooksConnection).where(QuickBooksConnection.id==1).with_for_update()).first()
        if not row or row.realm_id!=os.getenv('QBO_REALM_ID'):raise RuntimeError('QuickBooks authorisation is required')
        if row.expires_at<=datetime.utcnow()+timedelta(seconds=90):
            r=httpx.post('https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer',auth=(os.environ['QBO_CLIENT_ID'],os.environ['QBO_CLIENT_SECRET']),data={'grant_type':'refresh_token','refresh_token':cipher().decrypt(row.encrypted_refresh_token.encode()).decode()},timeout=20)
            if not r.is_success:raise RuntimeError('QuickBooks needs reconnecting')
            d=r.json();row.encrypted_refresh_token=cipher().encrypt(d['refresh_token'].encode()).decode();row.encrypted_access_token=cipher().encrypt(d['access_token'].encode()).decode();row.expires_at=datetime.utcnow()+timedelta(seconds=d['expires_in']);self.session.add(row)
            # Caller commits rotated token before invoice mutations.
        return row.realm_id,cipher().decrypt(row.encrypted_access_token.encode()).decode()
    def request(self,method,path,payload=None,params=None):
        realm,token=self.token()
        base='https://sandbox-quickbooks.api.intuit.com' if os.getenv('QBO_ENVIRONMENT')=='sandbox' else 'https://quickbooks.api.intuit.com'
        content_type='application/octet-stream' if method=='POST' and path.endswith('/send') else 'application/json'
        r=httpx.request(method,f'{base}/v3/company/{quote(realm,safe="")}/{path}',headers={'Authorization':'Bearer '+token,'Accept':'application/json','Content-Type':content_type},json=payload,params=params,timeout=20)
        if not r.is_success:raise RuntimeError(f'QuickBooks request failed ({r.status_code}); review integration logs in Intuit')
        data=r.json()
        if data.get('Fault'):raise RuntimeError('QuickBooks rejected the invoice; review account mappings')
        return data

def invoice_payload(sheet,mapping,issue,due):
    return {'DocNumber':f'CP-TS-{sheet.id}','CustomerRef':{'value':mapping.customer_id},'TxnDate':issue.isoformat(),'DueDate':due.isoformat(),'CurrencyRef':{'value':'GBP'},'GlobalTaxCalculation':'TaxExcluded','BillEmail':{'Address':mapping.invoice_email},'CustomerMemo':{'value':f'ContractPros — RMC Engineering & Automation Ltd. Booking {sheet.booking_id}, week commencing {sheet.week_start}. Approved timesheet {sheet.id}.'},'PrivateNote':f'ContractPros timesheet {sheet.id}', 'Line':[{'Amount':float(Decimal(sheet.net_pence)/100),'Description':f'ContractPros approved work — booking {sheet.booking_id}, week {sheet.week_start}; {sheet.total_minutes} minutes, {sheet.unit} rate GBP{Decimal(sheet.client_rate_pence)/100:.2f}.','DetailType':'SalesItemLineDetail','SalesItemLineDetail':{'ItemRef':{'value':os.environ['QBO_SERVICE_ITEM_ID']},'TaxCodeRef':{'value':os.environ['QBO_SALES_TAX_CODE_ID']},'Qty':1,'UnitPrice':float(Decimal(sheet.net_pence)/100)}}]}

def verify_invoice(inv,row):
    expected=json.loads(row.payload_json)
    if inv.get('DocNumber')!=expected['DocNumber'] or inv.get('CustomerRef',{}).get('value')!=expected['CustomerRef']['value'] or inv.get('CurrencyRef',{}).get('value')!='GBP' or pence(Decimal(str(inv.get('TotalAmt',-1)))*100)!=row.net_pence+row.vat_pence or inv.get('DueDate')!=row.due_date.isoformat():
        raise RuntimeError('QuickBooks invoice differs from approved charges; admin reconciliation required')
    return inv

def process_pending(session,only_timesheet=None):
    if not configured(session):return
    # Rotate credentials in their own committed transaction, never commit an invoice lock here.
    try:
        QBO(session).token();session.commit()
    except Exception:
        session.rollback()
        return
    query=select(WorkInvoice).where(WorkInvoice.status.in_(['pending','created']),WorkInvoice.next_attempt_at<=datetime.utcnow()).order_by(WorkInvoice.id).limit(1).with_for_update(skip_locked=True)
    if only_timesheet is not None:query=query.where(WorkInvoice.timesheet_id==only_timesheet)
    rows=session.exec(query).all()
    for row in rows:
        try:
            api=QBO(session)
            if not row.provider_id:
                # requestid and deterministic DocNumber aid recovery; uncertain writes are never blindly repeated.
                found=api.request('GET','query',params={'query':f"select * from Invoice where DocNumber = 'CP-TS-{row.timesheet_id}'"}).get('QueryResponse',{}).get('Invoice',[])
                if len(found)>1:raise RuntimeError('Duplicate invoice numbers found; manual reconciliation required')
                if found:inv=found[0]
                else:
                    row.status='creating';session.add(row);session.commit()
                    row=session.exec(select(WorkInvoice).where(WorkInvoice.id==row.id).with_for_update()).one()
                    inv=api.request('POST','invoice',json.loads(row.payload_json),{'requestid':f'cp-timesheet-{row.timesheet_id}'}).get('Invoice',{})
                if not inv.get('Id'):raise RuntimeError('QuickBooks did not return an invoice identifier')
                row.provider_id=inv['Id'];row.invoice_number=inv.get('DocNumber')
                verify_invoice(inv,row);row.status='created';session.add(row);session.commit()
                # Reacquire after committing the external ID; competing workers must not send twice.
                row=session.exec(select(WorkInvoice).where(WorkInvoice.id==row.id).with_for_update()).one()
                if row.status!='created':continue
            inv=verify_invoice(api.request('GET',f'invoice/{row.provider_id}').get('Invoice',{}),row)
            if inv.get('EmailStatus')!='EmailSent':
                row.status='sending';session.add(row);session.commit()
                row=session.exec(select(WorkInvoice).where(WorkInvoice.id==row.id).with_for_update()).one()
                inv=api.request('POST',f'invoice/{row.provider_id}/send',params={'sendTo':json.loads(row.payload_json)['BillEmail']['Address'],'requestid':f'cp-send-{row.timesheet_id}'}).get('Invoice',{})
            if inv.get('EmailStatus')!='EmailSent':raise RuntimeError('QuickBooks email submission not confirmed; check delivery before retrying')
            row.status='sent';row.sent_at=datetime.utcnow();row.last_error=None;row.balance_pence=pence(Decimal(str(inv.get('Balance',0)))*100)
        except Exception as exc:
            # Provider exceptions are sanitised, never expose token-bearing request payloads.
            row.status='reconciliation_required';row.last_error='Invoice processing needs administrator reconciliation. No automatic duplicate will be issued.'
        row.attempts+=1;session.add(row);session.commit()
