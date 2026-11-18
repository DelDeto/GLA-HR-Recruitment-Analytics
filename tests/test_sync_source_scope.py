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
