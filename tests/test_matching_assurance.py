"""Recruitment scoring must be consistent and ignore irrelevant identity data."""
import pytest
from tests.test_search_matching import job, talent
from app.routers.company_matches import _score_match, _discipline_matches
from app.routers.applications import _job_talent_match

@pytest.mark.parametrize('criteria', [{}, {'ir35_type':'outside'}, {'required_skills':'PLC, welding'}, {'profession':'Engineer','experience_level':'senior'}])
def test_application_and_search_share_score(criteria):
    j,p=job(**criteria),talent(skills='PLC')
    assert _job_talent_match(j,p,[])['match_percentage']==_score_match(j,p)[0]

@pytest.mark.parametrize('spelling',['multiskilled','multi-skilled','Multi Skilled'])
def test_multi_skilled_equivalent_for_electrical_and_mechanical(spelling):
    for discipline in ['electrical','mechanical']:
        assert _discipline_matches(job(engineering_discipline=discipline),talent(engineering_discipline=spelling))

def test_identity_fields_do_not_change_score():
    j=job(profession='Engineer',required_skills='PLC',industry='pharma')
    p=talent(skills='PLC',industry='pharma')
    baseline=_score_match(j,p)
    p.first_name='Different';p.last_name='Identity';p.avatar_url='https://example.com/photo';p.bio='Unrelated demographic information'
    assert _score_match(j,p)==baseline
    p.agency_id=99;p.user_id=None
    assert _job_talent_match(j,p,[])['match_percentage']==baseline[0]
