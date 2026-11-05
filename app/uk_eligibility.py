"""UK service eligibility. Address format is not independent business verification."""
import re
from fastapi import HTTPException
from sqlmodel import select
from models.company import Company

# UK postcode shape, excluding Crown Dependencies and overseas territories.
POSTCODE = re.compile(r'(?:GIR\s?0AA|[A-PR-UWYZ][A-HK-Y]?\d[\dA-HJKPSTUW]?\s?\d[ABD-HJLNP-UW-Z]{2})', re.I)

def uk_postcode(value):
    value=(value or '').strip().upper()
    if value.startswith(('GY','JE','IM')) or not POSTCODE.fullmatch(value):
        raise HTTPException(422,'ContractPros supports UK businesses and UK work only. Enter a valid UK postcode.')
    compact=value.replace(' ','')
    return compact[:-3]+' '+compact[-3:]

def uk_site_address(value):
    for match in re.finditer(r'(?<![A-Z0-9])(?:'+POSTCODE.pattern+r')(?![A-Z0-9])', value or '', re.I):
        try:return uk_postcode(match.group())
        except HTTPException:continue
    raise HTTPException(422,'Enter the UK work site address, including its UK postcode. Overseas bookings are not supported.')

def uk_business_profile(session,user):
    profile=session.exec(select(Company).where(Company.owner_id==user.id)).first()
    if not profile or not profile.name.strip():
        raise HTTPException(409,'Save your UK business profile before starting membership.')
    try:uk_postcode(profile.postcode)
    except HTTPException:
        raise HTTPException(422,'Save a valid UK postcode in your business profile before starting membership.')
    return profile
