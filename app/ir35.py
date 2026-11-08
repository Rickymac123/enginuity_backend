"""Original guidance prompts, not a determination or a weighted status engine."""
VERSION = 'guidance-1'
NOTICE = ('Indicative IR35 guidance only. This assessment highlights employment-status factors based on the information supplied. '
          'It is not a formal Status Determination Statement, tax or legal advice, or a guarantee of HMRC’s position. '
          'Confirm the appropriate status before relying on it for an engagement. Actual working practices matter, not just contract wording.')
CEST = 'https://www.gov.uk/guidance/check-employment-status-for-tax'
SOURCE = 'https://www.gov.uk/government/publications/help-to-comply-with-the-reformed-off-payroll-working-rules-ir35-gfc4/making-status-determinations-part-8'
# yes_indicator is explanatory only; no weights, totals, pass marks or status decisions.
QUESTIONS = [
 ('intermediary','Engagement','Will the worker supply services through their own intermediary, such as a personal service company?', 'Confirm the contractual supply chain. If not, a different employment-status assessment may be needed.', 'scope'),
 ('office','Engagement','Does this engagement involve holding an office in the end client’s organisation?', 'Office-holder rules need specific consideration; seek advice rather than relying on this questionnaire.', 'review'),
 ('personal','Personal service','Does the client require this particular individual to perform the work personally?', 'A requirement for personal service is an employment indicator. Consider the real agreement and practices.', 'employment'),
 ('substitute','Personal service','Could the supplier genuinely arrange and pay a suitably qualified substitute in practice?', 'A genuine substitution arrangement may indicate independence. Restrictions, client rejection rights and practical feasibility matter.', 'independence'),
 ('control','Control','Can the client direct how the work is performed, beyond agreeing the outcome and necessary site or safety requirements?', 'A right to control how work is done can indicate employment, even if it is not regularly exercised.', 'employment'),
 ('schedule','Control','Does the client decide the worker’s schedule rather than agreeing necessary project or site access times?', 'Consider why time and location are fixed; site access or safety requirements alone do not settle status.', 'employment'),
 ('ongoing','Obligations','Is there an obligation to offer and accept further work beyond the agreed assignment?', 'Record the obligations for this engagement. Lack of future work alone does not establish self-employment.', 'employment'),
 ('benefits','Obligations','Does the client provide paid holiday or sick pay for this engagement?', 'Employment-type benefits are relevant, but their absence does not establish self-employment.', 'employment'),
 ('rectify','Financial risk','Must the supplier put defective work right at its own expense under the actual agreement?', 'Genuine exposure to loss may indicate business independence; consider whether this happens in practice.', 'independence'),
 ('equipment','Financial risk','Does the supplier make significant business investment in equipment needed for the work?', 'Consider the nature and value of investment. Owning a routine laptop or small tools alone does not settle status.', 'independence'),
 ('clients','Independent business','Does the supplier actively operate a business serving other clients?', 'Wider business activity can be relevant context; having several clients does not decide this engagement’s status.', 'independence'),
 ('integration','Integration','Is the worker treated as part of the client’s staff beyond what this project requires?', 'Consider staff management duties, benefits and organisational responsibilities rather than routine site access alone.', 'employment'),
]

def catalogue():
    return [dict(id=i,section=s,question=q,help=h) for i,s,q,h,_ in QUESTIONS]

def guidance(answers):
    missing=[q[0] for q in QUESTIONS if answers.get(q[0]) not in ('yes','no')]
    flags=[]
    for key,section,question,help_,kind in QUESTIONS:
        if answers.get(key)=='yes' and kind in ('employment','independence','review'):
            flags.append(dict(question_id=key,section=section,kind=kind,explanation=help_))
    conflicts=[]
    if answers.get('personal')=='yes' and answers.get('substitute')=='yes':
        conflicts.append('Clarify how a requirement for personal service fits with the proposed substitution arrangement.')
    if answers.get('intermediary')=='no':conflicts.append('Confirm the applicable employment-status route: this questionnaire is intended for engagements through an intermediary.')
    return dict(status='Further review required' if missing or conflicts or answers.get('office')=='yes' else 'Guidance recorded — confirm status separately',missing=missing,flags=flags,conflicts=conflicts)
