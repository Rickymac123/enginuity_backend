import json, os
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, EmailStr
from sqlmodel import Session, select
from app.db import get_session
from auth.deps import current_user, require_admin
from auth.models import User
from models.booking import Booking
from models.talent import Talent
from models.work_billing import WorkBillingSettings, BookingRate, WorkTimesheet, WorkInvoice, QuickBooksClient, QuickBooksConnection
from app.work_billing import authorised_booking, owner, charge, pence, audit, validate_entries, LONDON
from app.notifications import enqueue

router=APIRouter(prefix='/work-billing',tags=['timesheets'])
class Revision(BaseModel):
    expected_revision: int = Field(ge=0,strict=True)
class Markup(Revision):
    markup_bps: int = Field(ge=0,le=100000,strict=True)
class Rate(Revision):
    contractor_pence: int = Field(gt=0,le=10000000,strict=True)
    markup_bps: int = Field(ge=0,le=100000,strict=True)
    unit: Literal['hour','day']
    day_minutes: int = Field(default=480,ge=1,le=1440,strict=True)
class Entry(BaseModel):
    start: datetime
    end: datetime
    break_minutes: int = Field(default=0,ge=0,le=1439,strict=True)
class Sheet(Revision):
    week_start: date
    entries: list[Entry] = Field(min_length=1,max_length=28)
class Return(Revision):
    reason: str = Field(min_length=1,max_length=2000)
class Mapping(Revision):
    customer_id: str = Field(pattern=r'^\d+$')
    invoice_email: EmailStr

def view(session,user,sheet):
    booking=session.get(Booking,sheet.booking_id);role=owner(user,booking,session.get(Talent,booking.talent_id))
    data={k:getattr(sheet,k) for k in ('id','booking_id','week_start','status','revision','total_minutes','correction_reason','approved_at','unit')}
    data['entries']=json.loads(sheet.entries_json)
    if role in ('admin','company'): data.update(net_pence=sheet.net_pence,client_rate_pence=sheet.client_rate_pence)
    if role in ('admin','supplier'): data['contractor_pence']=sheet.contractor_pence
    if role=='admin':data['markup_bps']=sheet.markup_bps
    inv=session.exec(select(WorkInvoice).where(WorkInvoice.timesheet_id==sheet.id)).first()
    if inv and role in ('company','admin'):
        data['invoice']={k:getattr(inv,k) for k in ('id','status','invoice_number','issue_date','due_date','net_pence','vat_pence','balance_pence')}
        if role=='admin':data['invoice']['last_error']=inv.last_error
    return data

@router.get('')
def dashboard(user:User=Depends(current_user),session:Session=Depends(get_session)):
    bookings=session.exec(select(Booking).order_by(Booking.id.desc())).all()
    items=[]
    for b in bookings:
        t=session.get(Talent,b.talent_id);role=owner(user,b,t)
        if not role:continue
        rate=session.get(BookingRate,b.id)
        r=None
        if rate:
            r={'revision':rate.revision,'unit':rate.unit,'day_minutes':rate.day_minutes}
            if role in ('admin','supplier'):r['contractor_pence']=rate.contractor_pence
            if role in ('admin','company'):r['client_rate_pence']=charge(60,rate.contractor_pence,rate.markup_bps)[0]
            if role=='admin':r['markup_bps']=rate.markup_bps
        sheets=session.exec(select(WorkTimesheet).where(WorkTimesheet.booking_id==b.id).order_by(WorkTimesheet.week_start.desc())).all()
        items.append({'id':b.id,'booking_request_id':b.booking_request_id,'company_id':b.company_id,'site_name':b.site_name,'start_date':b.start_date,'end_date':b.end_date,'status':b.status,'professional':f'{t.first_name} {t.last_name}' if t else 'Professional','rate':r,'timesheets':[view(session,user,s) for s in sheets]})
    settings=session.get(WorkBillingSettings,1)
    result={'role':user.role,'bookings':items,'issuing_enabled':os.getenv('WORK_INVOICING_ENABLED')=='true'}
    if user.role=='admin':
        result['settings']={'markup_bps':settings.markup_bps if settings else 2000,'revision':settings.revision if settings else 0}
        result['quickbooks']={'connected':bool(session.get(QuickBooksConnection,1)),'sending_enabled':os.getenv('WORK_INVOICING_ENABLED')=='true'}
        result['clients']=[{'id':u.id,'email':u.email,'mapping':session.get(QuickBooksClient,u.id)} for u in session.exec(select(User).where(User.role=='company')).all()]
    return result

@router.patch('/settings')
def settings(body:Markup,admin:User=Depends(require_admin),session:Session=Depends(get_session)):
    # Lock stable user table row as settings may not yet exist.
    session.exec(select(User).where(User.id==admin.id).with_for_update()).one()
    row=session.exec(select(WorkBillingSettings).where(WorkBillingSettings.id==1).with_for_update()).first()
    if not row:raise HTTPException(503,'Run the work billing migration first')
    if row.revision!=body.expected_revision:raise HTTPException(409,'Reload settings before saving')
    row.markup_bps=body.markup_bps;row.revision+=1;session.add(row)
    audit(session,admin,'settings',1,'markup_changed',body.model_dump());session.commit()
    return {'markup_bps':row.markup_bps,'revision':row.revision}

@router.put('/bookings/{bid}/rate')
def save_rate(bid:int,body:Rate,admin:User=Depends(require_admin),session:Session=Depends(get_session)):
    booking,_=authorised_booking(session,admin,bid)
    if session.exec(select(WorkTimesheet.id).where(WorkTimesheet.booking_id==bid)).first():raise HTTPException(409,'This booking already has timesheets. Its agreed rate is locked; use a new booking for rate changes.')
    row=session.get(BookingRate,bid)
    if (row.revision if row else 0)!=body.expected_revision:raise HTTPException(409,'Reload booking before saving')
    row=row or BookingRate(booking_id=bid,recorded_by=admin.id,contractor_pence=body.contractor_pence,markup_bps=body.markup_bps,revision=0)
    for key in ('contractor_pence','markup_bps','unit','day_minutes'):setattr(row,key,getattr(body,key))
    row.revision+=1;row.recorded_by=admin.id;row.recorded_at=datetime.utcnow();session.add(row)
    if booking.client_payment_due_days is None:
        from app.routers.client_terms import terms_for
        terms=terms_for(session,booking.company_id)
        booking.client_payment_due_days=terms['payment_due_days'];booking.client_terms_revision=terms['revision'];session.add(booking)
        audit(session,admin,'booking',bid,'historic_terms_agreed_with_rate',terms)
    audit(session,admin,'booking',bid,'rate_agreed',body.model_dump());session.commit()
    return {'saved':True}

@router.put('/clients/{cid}')
def map_client(cid:int,body:Mapping,admin:User=Depends(require_admin),session:Session=Depends(get_session)):
    from app.quickbooks_work import QBO
    u=session.exec(select(User).where(User.id==cid).with_for_update()).first()
    if not u or u.role!='company':raise HTTPException(404,'Client not found')
    customer=QBO(session).request('GET',f'customer/{body.customer_id}').get('Customer',{})
    if not customer.get('Active') or customer.get('CurrencyRef',{}).get('value','GBP')!='GBP':raise HTTPException(422,'Choose an active GBP customer')
    if customer.get('PrimaryEmailAddr',{}).get('Address','').lower()!=str(body.invoice_email).lower():raise HTTPException(422,'Invoice email must match the verified QuickBooks customer email')
    row=session.get(QuickBooksClient,cid)
    if (row.revision if row else 0)!=body.expected_revision:raise HTTPException(409,'Reload client mapping')
    row=row or QuickBooksClient(company_id=cid,customer_id=body.customer_id,invoice_email=str(body.invoice_email),revision=0)
    row.customer_id=body.customer_id;row.invoice_email=str(body.invoice_email);row.revision+=1;session.add(row)
    audit(session,admin,'client',cid,'accounting_mapping',body.model_dump());session.commit();return {'saved':True}

@router.post('/bookings/{bid}/timesheets')
def submit(bid:int,body:Sheet,user:User=Depends(current_user),session:Session=Depends(get_session)):
    booking,role=authorised_booking(session,user,bid)
    if role!='supplier':raise HTTPException(403,'Only the booked professional or agency can submit work')
    rate=session.get(BookingRate,bid)
    if not rate:raise HTTPException(409,'Admin must record the agreed booking rate first')
    old=session.exec(select(WorkTimesheet).where(WorkTimesheet.booking_id==bid,WorkTimesheet.week_start==body.week_start).with_for_update()).first()
    if (old.revision if old else 0)!=body.expected_revision:raise HTTPException(409,'Reload this timesheet before submitting')
    if old and old.status!='returned':raise HTTPException(409,'This week has already been submitted')
    minutes=validate_entries(session,booking,body.week_start,body.entries,old.id if old else None)
    client_rate,net=charge(minutes,rate.contractor_pence,rate.markup_bps,rate.unit,rate.day_minutes)
    if old:audit(session,user,'timesheet',old.id,'previous_revision',old.model_dump())
    values=dict(booking_id=bid,week_start=body.week_start,submitted_by=user.id,entries_json=json.dumps([e.model_dump(mode='json') for e in body.entries]),total_minutes=minutes,rate_revision=rate.revision,contractor_pence=rate.contractor_pence,markup_bps=rate.markup_bps,client_rate_pence=client_rate,unit=rate.unit,day_minutes=rate.day_minutes,net_pence=net,status='submitted',correction_reason=None)
    row=old or WorkTimesheet(**values)
    if old:
        for k,v in values.items():setattr(row,k,v)
        row.revision+=1
    if net<1:raise HTTPException(422,'Billable work must total at least one penny')
    session.add(row);session.flush();audit(session,user,'timesheet',row.id,'submitted',{'revision':row.revision})
    enqueue(session,f'timesheet-submitted:{row.id}:{row.revision}',booking.company_id,'ContractPros timesheet awaiting approval','Review the submitted work and charges. The timesheet page shows whether invoicing is enabled or on hold.','/dashboard/timesheets')
    session.commit();return view(session,user,row)

@router.post('/timesheets/{sid}/return')
def return_sheet(sid:int,body:Return,user:User=Depends(current_user),session:Session=Depends(get_session)):
    row=session.get(WorkTimesheet,sid)
    if not row:raise HTTPException(404,'Timesheet not found')
    _,role=authorised_booking(session,user,row.booking_id)
    session.refresh(row)
    if role!='company':raise HTTPException(403,'Only the client can return a timesheet')
    if row.status!='submitted' or row.revision!=body.expected_revision:raise HTTPException(409,'Timesheet has changed; reload')
    if not body.reason.strip():raise HTTPException(422,'Explain the correction required')
    row.status='returned';row.correction_reason=body.reason.strip();row.revision+=1;session.add(row)
    audit(session,user,'timesheet',sid,'returned',body.model_dump())
    enqueue(session,f'timesheet-returned:{sid}:{row.revision}',row.submitted_by,'ContractPros timesheet needs a correction','Your client requested a correction. Open the timesheet to review their comments.','/dashboard/timesheets')
    session.commit();return view(session,user,row)

@router.post('/timesheets/{sid}/approve')
def approve(sid:int,body:Revision,user:User=Depends(current_user),session:Session=Depends(get_session)):
    row=session.get(WorkTimesheet,sid)
    if not row:raise HTTPException(404,'Timesheet not found')
    booking,role=authorised_booking(session,user,row.booking_id);session.refresh(row)
    if role!='company':raise HTTPException(403,'Only the booking client can approve work')
    if row.status=='approved':return view(session,user,row)
    if row.status!='submitted' or row.revision!=body.expected_revision:raise HTTPException(409,'Timesheet has changed; reload')
    from app.quickbooks_work import configured, invoice_payload
    mapping=session.get(QuickBooksClient,booking.company_id)
    issuing = os.getenv('WORK_INVOICING_ENABLED') == 'true'
    if issuing and (not configured(session) or not mapping):raise HTTPException(409,'RMC must finish the QuickBooks connection and client mapping before approval')
    if booking.client_payment_due_days is None:raise HTTPException(409,'This historic booking has no recorded payment terms. Contact RMC to agree terms first.')
    issue=datetime.now(LONDON).date();due=issue+timedelta(days=booking.client_payment_due_days)
    row.status='approved';row.approved_by=user.id;row.approved_at=datetime.utcnow();row.revision+=1;session.add(row)
    vat=pence(Decimal(row.net_pence)*Decimal('0.20'))
    if issuing:
        payload=invoice_payload(row,mapping,issue,due)
        session.add(WorkInvoice(timesheet_id=sid,company_id=booking.company_id,issue_date=issue,due_date=due,net_pence=row.net_pence,vat_pence=vat,payload_json=json.dumps(payload)))
    else:
        audit(session,user,'timesheet',sid,'invoice_held',{'reason':'Automatic invoicing disabled; requires separate manual review before issuing'})
    audit(session,user,'timesheet',sid,'approved',{'revision':row.revision,'net_pence':row.net_pence,'vat_pence':vat,'due_date':due})
    enqueue(session,f'timesheet-approved:{sid}',row.submitted_by,'ContractPros timesheet approved','Your client approved the timesheet. Invoice RMC for your agreed cost; this notification is not a contractor invoice or payment.','/dashboard/timesheets')
    session.commit()
    # Durable record is committed first. Provider failures remain visible and retryable.
    from app.quickbooks_work import process_pending
    if issuing:process_pending(session,only_timesheet=sid)
    return view(session,user,row)

@router.post('/invoices/{iid}/reconcile')
def reconcile_invoice(iid:int,admin:User=Depends(require_admin),session:Session=Depends(get_session)):
    from app.quickbooks_work import QBO,verify_invoice
    row=session.exec(select(WorkInvoice).where(WorkInvoice.id==iid).with_for_update()).first()
    if not row:raise HTTPException(404,'Invoice not found')
    found=QBO(session).request('GET','query',params={'query':f"select * from Invoice where DocNumber = 'CP-TS-{row.timesheet_id}'"}).get('QueryResponse',{}).get('Invoice',[])
    if len(found)!=1:raise HTTPException(409,'No unique invoice found. Review QuickBooks before any manual creation; no replacement has been issued.')
    try:inv=verify_invoice(found[0],row)
    except RuntimeError:raise HTTPException(409,'Invoice differs from approved charges. Reconcile it in QuickBooks first.')
    row.provider_id=inv['Id'];row.invoice_number=inv['DocNumber'];row.balance_pence=pence(Decimal(str(inv.get('Balance',0)))*100)
    if inv.get('EmailStatus')=='EmailSent':row.status='sent';row.sent_at=row.sent_at or datetime.utcnow();row.last_error=None
    elif row.status in ('sending','reconciliation_required'):
        raise HTTPException(409,'Invoice exists but sending is not confirmed. Check QuickBooks email history and send there if needed, then reconcile again.')
    else:row.status='created'
    session.add(row);audit(session,admin,'invoice',iid,'reconciled',{'provider_id':row.provider_id,'status':row.status});session.commit()
    return {'status':row.status}
