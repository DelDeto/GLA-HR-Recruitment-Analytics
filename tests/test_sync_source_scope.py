import hashlib
from types import SimpleNamespace
import pytest
from src import sync_source_scope as scope
from src import sync_access_check as access
from src.sync_runtime import SyncBlocked


def test_only_exact_user_confirmed_source_is_excluded(monkeypatch):
    unused='synthetic-unused';sha=hashlib.sha256(unused.encode()).hexdigest()
    monkeypatch.setattr(scope,'UNUSED_SOURCE_HASHES',{'form_ctech':sha})
    roles={'form_ctech':unused,'crm':'required-crm','form_epu':'required-form'}
    assert scope.active_roles(roles)=={'crm':'required-crm','form_epu':'required-form'}
    assert roles['form_ctech']==unused
    with pytest.raises(SyncBlocked,match='IDENTITY_CHANGED'):
        scope.active_roles(dict(roles,form_ctech='different-file'))


def test_legacy_adapter_does_not_open_unused_cache_or_hide_other_errors():
    calls=[]
    def load(name):calls.append(name);raise FileNotFoundError(name)
    collector=SimpleNamespace(load=load)
    with pytest.raises(FileNotFoundError):
        with scope.exclude_legacy_forms(collector,{}):
            excluded=collector.load('opt-form-ctech.json')
            assert excluded=={'sheets':[],'source_scope':'USER_CONFIRMED_UNUSED'}
            collector.load('opt-form-epu.json')
    assert collector.load is load
    assert calls==['opt-form-epu.json']


def test_canary_retains_other_resource_requirements():
    assert 'form_ctech'not in access.RESOURCE_HASHES
    assert {'A','B','folder','crm','pv','ob','form_epu','form_uet'}<=set(access.RESOURCE_HASHES)
    assert not(set(access.RESOURCE_HASHES.values())&set(scope.UNUSED_SOURCE_HASHES.values()))


def test_retained_snapshot_exclusion_is_explicit_not_another_pipeline(monkeypatch):
    from src import sync_business as business
    unused='synthetic-unused';sha=hashlib.sha256(unused.encode()).hexdigest()
    monkeypatch.setattr(scope,'UNUSED_SOURCE_HASHES',{'form_ctech':sha})
    monkeypatch.setattr(business,'UNUSED_SOURCE_HASHES',{'form_ctech':sha})
    source={'file_id':unused,'fingerprint':'original-hash','tabs':[{'id':1,'rows':[]}]}
    claims=business.coverage({'sources':{'sources':[source]}},set(),{'source_roles':{'form_ctech':unused}})
    assert claims[unused]=={'fingerprint':'original-hash','tabs':{'1':{
        'state':'VERIFIED_OUT_OF_SCOPE','reason_code':'USER_CONFIRMED_UNUSED'}}}
    assert source['fingerprint']=='original-hash'


def test_quota_retry_waits_full_minute_and_repeats_exact_request():
    from src.sync_runtime import request
    calls=[];waits=[]
    class Response:
        headers={}
        def __init__(self,status):self.status_code=status
    class Session:
        def request(self,*args,**kwargs):
            calls.append((args,kwargs));return Response(429 if len(calls)==1 else 200)
    result=request(Session(),'GET','https://example.invalid',params={'range':'fixed'},sleep=waits.append)
    assert result.status_code==200
    assert waits==[60]
    assert calls[0]==calls[1]
