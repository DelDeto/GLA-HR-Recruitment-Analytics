import copy
import pytest
from src.sync_scoped_copy import copy_validated, attendance_with_native_parent
from src.sync_runtime import PrivateState, SyncBlocked
from src.sync_runner import protected_hash
from src.sync_plan import table_upserts
from test_sync_runner import Native, table


class Transport(Native):
    corrupt=False
    def read_cells(self,id,snapshot,keys):
        result={k:copy.deepcopy(self.s[id]['cells'].get(k,{})) for k in keys}
        if self.corrupt and self.calls:
            for c in result.values():c['userEnteredValue']={'stringValue':'wrong'}
        return result


def setup(monkeypatch,tmp_path):
    for k,v in {'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY_ID':'1453850214',
        'GLA_V24_SERIALIZED_WRITER':'gla-meta-ads-daily-sync'}.items():monkeypatch.setenv(k,v)
    n=Transport();targets={};plans={};proof={}
    for name,role in [('A','MASTER_V23'),('B','SEPTEMBER_V22')]:
        changes,guards=table_upserts(n.s[name],table([['key',2]]))
        plans[name]={'changes':changes,'guards':guards}
        targets[name]={'id':name,'role':role,'ownership':{'lead':[[7500,1,10,0,2]]}}
        proof[name]={'protected_hash_match':True,'authored_hash_match':True,'formula_errors':0}
    s={'config':{'targets':targets},'protected':{x:protected_hash(n.s[x],t['role'])for x,t in targets.items()},
       'branches':{'lead':{'normalization_state':'VALIDATED','plans':plans,
            'targets':{x:{'state':'PARTIAL','reason':'LEAD_SOURCE_ROWS_QUARANTINED',
            'held_reasons':['LEAD_SOURCE_ROWS_QUARANTINED']} for x in targets}},
            'pv_ob':{},'attendance':{}}}
    return n,s,{'mode':'DRY_RUN','run_id':'test','targets':proof},PrivateState(tmp_path/'private')


def test_copy_is_idempotent_and_never_promotes_full_checkpoints(monkeypatch,tmp_path):
    n,s,r,st=setup(monkeypatch,tmp_path)
    result=copy_validated(s,r,n,st)
    assert result['write_requests']==2
    assert result['watermarks_advanced']is False
    assert all(t['state']=='VERIFIED_VALID_SUBSETS_SOURCE_REVIEW_HELD'for t in result['targets'].values())
    assert copy_validated(s,r,n,st)['write_requests']==0
    assert not (st.root/'last-good.json').exists()


def test_changed_target_is_held_without_preventing_other_target(monkeypatch,tmp_path):
    n,s,r,st=setup(monkeypatch,tmp_path);r['targets']['A']['authored_hash_match']=False
    result=copy_validated(s,r,n,st)
    assert result['targets']['A']['state']=='HELD'
    assert [c[0]for c in n.calls]==['B']


@pytest.mark.parametrize('failure',['coordinator','proof','unvalidated','unknown_reason','preimage','protected'])
def test_no_write_when_proof_or_preimage_is_invalid(monkeypatch,tmp_path,failure):
    n,s,r,st=setup(monkeypatch,tmp_path)
    if failure=='coordinator':monkeypatch.delenv('GLA_V24_SERIALIZED_WRITER')
    if failure=='proof':r['mode']='SUCCESS'
    if failure=='unvalidated':s['branches']['lead']['normalization_state']='FAILED'
    if failure=='unknown_reason':
        for t in s['branches']['lead']['targets'].values():t['held_reasons']=['MISSING_SOURCE']
    if failure=='preimage':
        for sn in n.s.values():sn['cells']['7500:1:1']={'userEnteredValue':{'numberValue':999}}
    if failure=='protected':
        for sn in n.s.values():sn['cells']['7000:0:0']={'userEnteredValue':{'stringValue':'edited'}}
    try:result=copy_validated(s,r,n,st)
    except SyncBlocked:pass
    assert n.calls==[]


def test_readback_failure_cannot_report_success(monkeypatch,tmp_path):
    n,s,r,st=setup(monkeypatch,tmp_path);n.corrupt=True
    result=copy_validated(s,r,n,st)
    assert result['targets']['A']['state']=='PARTIAL'
    assert result['targets']['A']['reason']=='SCOPED_COPY_NATIVE_READBACK_MISMATCH'
    assert result['watermarks_advanced']is False


def parent_snapshot():
    values=['F','E1','Person',46266,None,None,None,'episode']
    return {'cells':{f'7305:3:{i}':{'userEnteredValue':{
        'numberValue'if isinstance(v,int)else'stringValue':v}}for i,v in enumerate(values)if v is not None}}


def test_attendance_requires_exact_unambiguous_native_parent():
    change=[{'key':'7851:3:12','after':{'stringValue':'episode'}}]
    person={'key':'episode','factory':'F','id':'E1','name':'Person','join':'2026-09-01','problem':''}
    sn=parent_snapshot()
    assert attendance_with_native_parent(change,{'cells':{}},[person])==([],1)
    assert attendance_with_native_parent(change,sn,[person])==(change,0)
    assert attendance_with_native_parent(change,sn,[person,person])==([],1)
    for field,new in [('id','OTHER'),('problem','REVIEW'),('join','2026-09-02')]:
        assert attendance_with_native_parent(change,sn,[dict(person,**{field:new})])==([],1)
