import json
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from sqlmodel import select
from models.booking import Booking
from models.talent import Talent
from models.work_billing import WorkAudit, WorkTimesheet

LONDON = ZoneInfo('Europe/London')
def pence(value):
    return int(Decimal(value).quantize(Decimal('1'), rounding=ROUND_HALF_UP))

def charge(minutes, rate, markup_bps, unit='hour', day_minutes=480):
    client_rate = pence(Decimal(rate)*(10000+markup_bps)/10000)
    return client_rate, pence(Decimal(client_rate)*minutes/(60 if unit=='hour' else day_minutes))

def audit(session,user,entity,eid,action,detail):
    session.add(WorkAudit(actor_id=user.id,entity=entity,entity_id=eid,action=action,detail=json.dumps(detail,default=str)))

def owner(user,booking,talent):
    if user.role=='admin': return 'admin'
    if user.role=='company' and booking.company_id==user.id: return 'company'
    if talent and user.role=='professional' and talent.user_id==user.id and talent.agency_id is None: return 'supplier'
    if talent and user.role=='agency' and talent.agency_id==user.id and talent.user_id is None: return 'supplier'
    return None

def authorised_booking(session,user,bid):
    # All mutations acquire talent then booking; matches booking acceptance/cancellation.
    booking=session.get(Booking,bid)
    talent=session.exec(select(Talent).where(Talent.id==booking.talent_id).with_for_update()).first() if booking else None
    booking=session.exec(select(Booking).where(Booking.id==bid).with_for_update()).first()
    role=owner(user,booking,talent) if booking else None
    if not role: raise HTTPException(404,'Booking not found')
    return booking,role

def validate_entries(session,booking,week_start,entries,exclude_id=None):
    if week_start.weekday()!=0: raise HTTPException(422,'Week must start on Monday')
    now=datetime.now(LONDON)
    intervals=[];total=0
    for e in entries:
        start=e.start;end=e.end
        def uk_time(value):
            if value.tzinfo is not None:return value.astimezone(LONDON)
            candidate=value.replace(tzinfo=LONDON)
            roundtrip=datetime.fromtimestamp(candidate.timestamp(),LONDON).replace(tzinfo=None)
            if roundtrip!=value:raise HTTPException(422,'This UK clock time does not exist due to the spring clock change')
            if candidate.utcoffset()!=value.replace(tzinfo=LONDON,fold=1).utcoffset():raise HTTPException(422,'This shift is during the autumn clock change. Contact RMC to confirm the exact hours before submission.')
            return candidate
        start=uk_time(start);end=uk_time(end)
        e.start=start;e.end=end
        start=start.astimezone(LONDON);end=end.astimezone(LONDON)
        minutes=(end.timestamp()-start.timestamp())/60
        if start.second or end.second or start.microsecond or end.microsecond or minutes!=int(minutes): raise HTTPException(422,'Use whole minutes')
        if not 0<minutes<=1440 or not 0<=e.break_minutes<minutes: raise HTTPException(422,'Check shift times and unpaid break')
        if start.date()<booking.start_date or start.date()>booking.end_date or end.date()>booking.end_date+timedelta(days=1): raise HTTPException(422,'Work must be within the booking dates')
        if start.date()<week_start or start.date()>week_start+timedelta(days=6): raise HTTPException(422,'Shift must start in this week')
        if end>now: raise HTTPException(422,'Future work cannot be submitted')
        if booking.status=='cancelled' and end.astimezone(ZoneInfo('UTC')).replace(tzinfo=None)>booking.updated_at: raise HTTPException(422,'Work after cancellation cannot be submitted')
        intervals.append((start.timestamp(),end.timestamp()));total+=int(minutes)-e.break_minutes
    others=session.exec(select(WorkTimesheet).join(Booking,Booking.id==WorkTimesheet.booking_id).where(Booking.talent_id==booking.talent_id)).all()
    for other in others:
        if other.id==exclude_id or other.status=='returned': continue
        for old in json.loads(other.entries_json):
            a=datetime.fromisoformat(old['start']).timestamp();b=datetime.fromisoformat(old['end']).timestamp()
            if any(x<b and y>a for x,y in intervals): raise HTTPException(409,'Work overlaps another submitted or approved timesheet')
    ordered=sorted(intervals)
    if any(b>c for (_,b),(c,_) in zip(ordered,ordered[1:])): raise HTTPException(422,'Shifts overlap')
    return total
