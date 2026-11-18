import copy
import pytest
from src import sync_daily as daily


def outcome(reason=None,writes=0):
    state='HELD'if reason else'VERIFIED_VALID_SUBSETS_SOURCE_REVIEW_HELD'
    return {'production_writes':writes,'scoped_copy':{'targets':{
        'A':{'state':state,'reason':reason,'rows_verified':writes},
        'B':{'state':'VERIFIED_VALID_SUBSETS_SOURCE_REVIEW_HELD','rows_verified':0}}}}


@pytest.mark.parametrize('reason',sorted(daily.RETRYABLE_TARGET_CHANGES))
def test_changed_target_retries_once_with_fresh_private_state(monkeypatch,reason):
    calls=[]
    results=[outcome(reason,2),outcome(None,3)]
    def run(state,*,scoped_apply):
        calls.append((state.root,scoped_apply))
        return copy.deepcopy(results[len(calls)-1])
    monkeypatch.setattr(daily,'source_run',run)
    result=daily.run_sources(dry_run=False)
    assert len(calls)==2 and calls[0][0]!=calls[1][0]
    assert all(c[1]is True for c in calls)
    assert result['production_writes']==5
    assert result['scoped_copy']['targets']['A']['state'].startswith('VERIFIED')
    assert [a['production_write_requests']for a in result['recovery_attempts']]==[2,3]


def test_repeated_changes_stop_after_two_attempts_and_remain_held(monkeypatch):
    calls=[]
    def run(*args,**kwargs):calls.append(1);return outcome('NATIVE_TARGET_CHANGED_DURING_DRY_RUN')
    monkeypatch.setattr(daily,'source_run',run)
    result=daily.run_sources(dry_run=False)
    assert len(calls)==2
    assert result['scoped_copy']['targets']['A']['state']=='HELD'


@pytest.mark.parametrize('reason',[None,'SCOPED_COPY_NATIVE_READBACK_MISMATCH',
    'SCOPED_COPY_FINAL_NATIVE_AUDIT_FAILED','SOURCE_INCOMPLETE'])
def test_other_outcomes_do_not_retry_or_hide_failures(monkeypatch,reason):
    calls=[]
    def run(*args,**kwargs):calls.append(1);return outcome(reason)
    monkeypatch.setattr(daily,'source_run',run)
    result=daily.run_sources(dry_run=False)
    assert len(calls)==1 and result['production_writes']==0
    assert result['scoped_copy']['targets']['A']['reason']==reason


def test_dry_run_never_requests_a_write_or_recovery(monkeypatch):
    calls=[]
    def run(state,*,scoped_apply):calls.append(scoped_apply);return outcome('NATIVE_TARGET_CHANGED_DURING_DRY_RUN')
    monkeypatch.setattr(daily,'source_run',run)
    result=daily.run_sources(dry_run=True)
    assert calls==[False] and len(result['recovery_attempts'])==1


def test_transport_exception_is_sanitized_and_not_retried(monkeypatch):
    calls=[]
    def run(*args,**kwargs):calls.append(1);raise RuntimeError('private source payload')
    monkeypatch.setattr(daily,'source_run',run)
    result=daily.run_sources(dry_run=False)
    assert len(calls)==1
    assert result['reason']=='GLA_SOURCE_SYNC_FAILED'
    assert 'private source payload'not in str(result)
