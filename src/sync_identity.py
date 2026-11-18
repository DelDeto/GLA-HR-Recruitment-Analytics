"""Pure stable identities; no phone/name records are logged or persisted here."""
import re
from datetime import date
from .attendance_presence import norm
from .sync_runtime import SyncBlocked, digest


def group(value, *, confirmed_default_ldpt=False):
    text=norm(value)
    if 'TTS' in text or ('IDL' in text and ('SV' in text or 'SINH VIEN' in text)):
        return 'IDL SV'
    if 'FRESHER' in text:
        return 'IDL Fresher'
    if 'IDL' in text:
        return 'IDL'
    if 'LDPT' in text or (not text and confirmed_default_ldpt):
        return 'LĐPT'
    raise SyncBlocked('RECRUITMENT_GROUP_UNVERIFIED')


def phone(value):
    text=re.sub(r'\D','',str(value or ''))
    if text.startswith('84') and len(text)==11:text='0'+text[2:]
    if not re.fullmatch(r'0\d{9}',text):
        raise SyncBlocked('LEAD_PHONE_IDENTITY_REVIEW')
    return text


def lead_key(day, recruitment_group, phone_number, factory=None):
    date.fromisoformat(day)
    if recruitment_group not in ('LĐPT','IDL','IDL SV','IDL Fresher'):
        raise SyncBlocked('LEAD_GROUP_UNKNOWN')
    if recruitment_group=='LĐPT' and not factory:
        raise SyncBlocked('LDPT_FACTORY_MISSING')
    return digest([day,recruitment_group,phone(phone_number),factory if recruitment_group=='LĐPT' else None])


def episode_key(factory, employee_id, join, *, candidate_id=None):
    date.fromisoformat(join)
    if not factory or not (employee_id or candidate_id):
        raise SyncBlocked('EMPLOYMENT_IDENTITY_REVIEW')
    return digest([factory,str(employee_id or candidate_id),join])


def event_key(kind, episode, actual_day):
    date.fromisoformat(actual_day)
    if kind not in ('PV','OB') or not episode:
        raise SyncBlocked('ACTUAL_EVENT_IDENTITY_MISSING')
    return digest([kind,episode,actual_day])


def meta_key(account, day, campaign):
    date.fromisoformat(day)
    if not str(account).isdigit() or not str(campaign).isdigit():
        raise SyncBlocked('META_ACCOUNT_CAMPAIGN_ID_MISSING')
    return digest([str(account),day,str(campaign)])
