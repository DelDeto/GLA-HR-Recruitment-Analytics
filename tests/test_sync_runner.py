import copy
import json
import hashlib
import os
import time
import pytest
from src.sync_runtime import PrivateState, SyncBlocked, request, digest
from src.sync_sources import collect_once, GoogleTransport
from src.sync_plan import table_upserts, validate_owned, expand_forecast
from src.sync_runner import BRANCHES, execute_stage, protected_hash, stage_run, pinned_adapter, validate_envelope,adapter_diagnostics
from src.sync_safety import validate_plan_writes, UnsafeSyncPlan
from src.sync_identity import group, lead_key, episode_key, meta_key
from src.sync_audit import reconcile


def snap(id='A'):
    s={'id':id,'sheets':[{'sheetId':7500,'title':'QL_LEADS','gridProperties':{'rowCount':10,'columnCount':5}}], 'cells':{}}
    def add(sid,r,c,v):s['cells'][f'{sid}:{r}:{c}']={'userEnteredValue':{'stringValue':v},'effectiveValue':{'stringValue':v}}
    add(7500,0,0,'ID');add(7500,0,1,'Amount')
    for r,c,v in [(5,1,46023),(5,4,46343),(4,4,'LĐPT'),(4,7,'Tất cả')]:
        s['cells'][f'7000:{r}:{c}']={'effectiveValue':{'numberValue'if isinstance(v,int)else'stringValue':v}}
    for c,v in enumerate([46266,'F',10,None]):
        if v is not None:s['cells'][f'7950:20:{48+c}']={'effectiveValue':{'numberValue'if isinstance(v,int)else'stringValue':v}}
    return s


def recon_spec():
    layout={'sheet_id':7950,'row_start':20,'row_end':21,'month_col':48,'factory_col':49,'metrics':{'forecast':50,'actual':51}}
    return {'scope':{'from':'2026-09-01','to':'2026-11-17','group':'LĐPT','factory':'Tất cả'},'A':layout,'B':layout}


def table(rows):
    return {'sheet_id':7500,'start_row':1,'end_row':10,'columns':[0,1],'key_columns':[0],
            'identity_basis':'lead_day_group_phone','expected_headers':{'0':'ID','1':'Amount'},'rows':rows}


class Native:
    def __init__(self):self.s={'A':snap('A'),'B':snap('B')};self.calls=[];self.fail_b=False
    def snapshot(self,id):return copy.deepcopy(self.s[id])
    def write(self,id,requests):
        if id=='B' and self.fail_b:raise SyncBlocked('REMOTE_HTTP_503')
        self.calls.append((id,requests))
        for req in requests:
            u=req['updateCells'];p=u['start']
            for i,row in enumerate(u['rows']):
                for j,c in enumerate(row['values']):
                    k=f"{p['sheetId']}:{p['rowIndex']+i}:{p['columnIndex']+j}"
                    self.s[id]['cells'][k]={'userEnteredValue':c['userEnteredValue']}


def stage(native):
    before=copy.deepcopy(native.s);branches={}
    for b in BRANCHES:
        plans={}
        for n in ('A','B'):
            changes,guards=table_upserts(before[n],table([['key',2]])) if b=='lead' else ([],{})
            plans[n]={'changes':changes,'guards':guards}
        branches[b]={'state':'READY','plans':plans}
    return {'created_at':time.time(),'config':{'deployment_approved':True,'single_writer_private_volume':True,
        'targets':{'A':{'id':'A','role':'MASTER_V23'},'B':{'id':'B','role':'SEPTEMBER_V22'}},'reconciliation':recon_spec()},
        'before':before,'branches':branches,'protected':{n:protected_hash(s,'MASTER_V23'if n=='A'else'SEPTEMBER_V22')for n,s in before.items()}}


def state(tmp_path):return PrivateState(tmp_path/'private')


def test_private_state_lock_and_immutable_snapshot(tmp_path):
    st=state(tmp_path);st.save('stage.json',{'x':1},immutable=True)
    assert (st.root/'stage.json').stat().st_mode & 0o077 == 0
    with pytest.raises(SyncBlocked):st.save('stage.json',{'x':2},immutable=True)
    with st.lock():
        with pytest.raises(SyncBlocked):
            with st.lock():pass


def test_insecure_state_directory_is_refused(tmp_path):
    os.chmod(tmp_path,0o755)
    with pytest.raises(SyncBlocked):PrivateState(tmp_path)


def test_keyed_upsert_reimport_does_not_duplicate_and_unknown_preserves():
    s=snap();s['cells']['7500:1:0']={'userEnteredValue':{'stringValue':'key'}};s['cells']['7500:1:1']={'userEnteredValue':{'numberValue':7}}
    changes,_=table_upserts(s,table([['key',None],['key',None]]));assert not changes
    changes,_=table_upserts(s,table([['key','']]));assert not changes
    with pytest.raises(SyncBlocked):table_upserts(s,table([['key',2],['key',3]]))
    t=table([['key',3]]);t['immutable_existing']=True
    with pytest.raises(SyncBlocked):table_upserts(s,t)


def test_schema_or_row_identity_conflict_blocks():
    s=snap();s['cells']['7500:0:0']['userEnteredValue']={'stringValue':'changed'}
    with pytest.raises(SyncBlocked):table_upserts(s,table([['key',2]]))
    with pytest.raises(SyncBlocked):episode_key('F',None,'2026-09-01')


def test_apply_a_success_b_failure_retry_and_readback(tmp_path):
    n=Native();st=state(tmp_path);s=stage(n);n.fail_b=True
    report=execute_stage('run',s,n,st,apply=True)
    assert report['targets']['A']['state']=='SUCCESS' and report['targets']['B']['state']=='PARTIAL'
    assert len(n.calls)==1
    n.fail_b=False;report=execute_stage('run',s,n,st,apply=True)
    assert all(t['state']=='SUCCESS'for t in report['targets'].values())
    assert [c[0]for c in n.calls]==['A','B']
    execute_stage('run',s,n,st,apply=True);assert len(n.calls)==2


def test_dry_run_never_writes_or_advances_last_good(tmp_path):
    n=Native();st=state(tmp_path);s=stage(n);before=copy.deepcopy(n.s)
    r=execute_stage('run',s,n,st)
    assert all(t['state']=='DRY_RUN_READY'for t in r['targets'].values())
    assert n.s==before and not n.calls
    assert not list(st.root.glob('last-good-*'))


def test_partial_source_and_newer_checkpoint_keep_last_good(tmp_path):
    n=Native();st=state(tmp_path);s=stage(n);st.save('last-good-A-lead.json',{'created_at':s['created_at']+1})
    r=execute_stage('old',s,n,st,apply=True);assert r['targets']['A']['state']=='PARTIAL'
    assert st.read('last-good-A-lead.json')['created_at']>s['created_at']


def test_changed_user_policy_and_formula_errors_block(tmp_path):
    n=Native();st=state(tmp_path);s=stage(n)
    n.s['A']['cells']['7903:15:11']={'userEnteredValue':{'stringValue':'ĐÃ CHỐT'}}
    n.s['B']['cells']['7950:0:0']={'effectiveValue':{'errorValue':{'type':'REF'}}}
    r=execute_stage('r',s,n,st,apply=True)
    assert all(v['state']=='PARTIAL'for v in r['targets'].values())and not n.calls


def test_readback_mismatch_does_not_checkpoint(tmp_path):
    n=Native();n.write=lambda *args:None;st=state(tmp_path)
    r=execute_stage('r',stage(n),n,st,apply=True)
    assert all(v['state']=='PARTIAL'for v in r['targets'].values())
    assert not list(st.root.glob('last-good-*'))


def test_retry_429_503_respects_backoff_and_limit():
    class Response:
        def __init__(self,code):self.status_code=code;self.headers={'Retry-After':'3'}
    class Session:
        def __init__(self,codes):self.codes=iter(codes)
        def request(self,*a,**k):return Response(next(self.codes))
    waits=[];assert request(Session([429,503,200]),'GET','https://example.test',sleep=waits.append).status_code==200
    assert len(waits)==2 and min(waits)>=3
    with pytest.raises(SyncBlocked):request(Session([503]*6),'GET','https://example.test',sleep=lambda _:None)


def test_one_source_scan_and_hidden_zero_hour_rows():
    class Sources:
        calls=[]
        def list_folder(self,f):return [{'id':'one','mimeType':'xlsx'}]
        def source(self,id):
            self.calls.append(id);return {'file_id':id,'tabs':[{'id':'hidden','hidden':True,'rows':[[0,[[0,'E123'],[1,0]]]]}]}
    t=Sources();b=collect_once(t,['folder'],['one','one']);assert b['transport_scan_complete'] and t.calls==['one']
    assert b['sources'][0]['tabs'][0]['rows'][0][1][1][1]==0


def test_missing_source_never_counts_as_empty_complete():
    class Sources:
        def source(self,id):raise SyncBlocked('REMOTE_HTTP_404')
    b=collect_once(Sources(),[],['missing']);assert not b['transport_scan_complete'] and b['errors']


def test_xlsx_reader_reads_every_hidden_tab_including_zero_hours():
    import io,openpyxl
    w=openpyxl.Workbook();w.active.append(['id','hours']);w.active.append(['E123',0]);w.create_sheet('hidden').sheet_state='hidden'
    out=io.BytesIO();w.save(out)
    class Response:status_code=200;content=out.getvalue()
    class Session:
        def request(self,*a,**k):return Response()
    t=GoogleTransport(Session());t.file_info=lambda _: {'id':'file','mimeType':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','version':'1'}
    s=t.source('file');assert len(s['tabs'])==2 and s['tabs'][1]['hidden']
    assert s['tabs'][0]['rows'][1][1][1][1]==0


def test_wrong_sha_refuses_to_execute_private_code(tmp_path):
    path=tmp_path/'adapter.py';path.write_text('raise Exception("MUST NOT RUN")')
    with pytest.raises(SyncBlocked,match='ADAPTER_SHA_MISMATCH'):
        pinned_adapter({'entrypoint':str(path),'version':'v','sha256':'a'*64}, {}, state(tmp_path))


def test_classification_and_factory_scope_do_not_invent_campaign_ids():
    assert group('TTS')=='IDL SV' and group('IDL Fresher')=='IDL Fresher'
    assert group('',confirmed_default_ldpt=True)=='LĐPT'
    with pytest.raises(SyncBlocked):group('')
    assert lead_key('2026-09-01','IDL','0912345678','A')==lead_key('2026-09-01','IDL','0912345678','B')
    assert lead_key('2026-09-01','LĐPT','0912345678','A')!=lead_key('2026-09-01','LĐPT','0912345678','B')
    assert meta_key('123','2026-09-01','456')!=meta_key('124','2026-09-01','456')


@pytest.mark.parametrize('req',[
 {'updateCells':{'range':{'sheetId':7002,'startRowIndex':14,'endRowIndex':13000,'startColumnIndex':13,'endColumnIndex':25},'rows':[],'fields':'*'}},
 {'autoFill':{'sourceAndDestination':{'source':{'sheetId':7950,'startRowIndex':1198,'endRowIndex':1199,'startColumnIndex':48,'endColumnIndex':49},'dimension':'ROWS','fillLength':2}}},
 {'repeatCell':{'range':{'sheetId':7903,'startRowIndex':15,'endRowIndex':16,'startColumnIndex':0,'endColumnIndex':1},'fields':'userEnteredValue'}},
 {'copyPaste':{'destination':{'sheetId':7002}}}, {'deleteSheet':{'sheetId':7002}},
])
def test_protection_cannot_be_bypassed_by_request_shape(req):
    with pytest.raises(UnsafeSyncPlan):validate_plan_writes([req],{'installed':True,'workbook_role':'MASTER_V23'})


def test_compare_unknown_is_not_zero_and_requires_same_filters():
    a,b=snap('A'),snap('B');assert reconcile({'A':a,'B':b},recon_spec())['rows']==1
    b['cells']['7950:20:51']={'effectiveValue':{'numberValue':0}}
    with pytest.raises(SyncBlocked):reconcile({'A':a,'B':b},recon_spec())


def test_closed_month_compare_can_use_different_full_report_scopes():
    a,b=snap('A'),snap('B');b['cells']['7000:5:4']={'effectiveValue':{'numberValue':46295}}
    spec=recon_spec();spec['scope']['to']='2026-09-30'
    assert reconcile({'A':a,'B':b},spec)['state']=='PASS'
    with pytest.raises(SyncBlocked):reconcile({'A':a,'B':b},recon_spec())


def test_forecast_fill_expected_values_and_bounds():
    req=[{'updateCells':{'start':{'sheetId':7950,'rowIndex':3,'columnIndex':0},'rows':[{'values':[{'userEnteredValue':{'formulaValue':'=QL_DU_KIEN!R4'}}]}],'fields':'userEnteredValue'}},
         {'autoFill':{'sourceAndDestination':{'source':{'sheetId':7950,'startRowIndex':3,'endRowIndex':4,'startColumnIndex':0,'endColumnIndex':1},'dimension':'ROWS','fillLength':2}}}]
    x=expand_forecast(req,snap());assert len(x)==3 and x[-1]['after']['formulaValue']=='=QL_DU_KIEN!R6'


def test_staging_with_missing_adapter_is_partial_and_keeps_targets(tmp_path):
    n=Native()
    n.source=lambda _: {'file_id':'source','fingerprint':'a'*64,'tabs':[{'id':'tab'}]}
    cfg={'targets':{'A':{'id':'A','role':'MASTER_V23'},'B':{'id':'B','role':'SEPTEMBER_V22'}},'source_files':['source'],'as_of':'2026-11-17'}
    run,s=stage_run(cfg,n,state(tmp_path));assert len(run)==64
    assert all(p['state']=='PARTIAL'for p in s['branches'].values())and not n.calls


def test_validated_normalization_can_be_audited_after_plan_failure_without_execution(tmp_path):
    n=Native();n.source=lambda _:{'file_id':'source','fingerprint':'hash','tabs':[{'id':1}]}
    cfg={'targets':{'A':{'id':'A','role':'MASTER_V23'},'B':{'id':'B','role':'SEPTEMBER_V22'}},
         'source_files':['source'],'as_of':'2026-11-17'}
    seen=[]
    def adapter(payload):
        branch=payload['branch'];seen.append((branch,set(payload['normalized'])))
        return {'complete':True,'validation':'PASS','coverage':{'source':{'fingerprint':'hash','tabs':{'1':{'state':'PARSED'}}}},
                'normalized':{'whitelist_loaded':True},'tables':{'A':[table([])],'B':[table([])]},
                'plan_blockers':{'A':'AUDIT_REVIEW_REQUIRED','B':'AUDIT_REVIEW_REQUIRED'}}
    _,result=stage_run(cfg,n,state(tmp_path),adapters={b:adapter for b in BRANCHES})
    assert 'pv_ob'in dict(seen)['attendance']
    assert result['branches']['attendance']['state']=='PARTIAL'
    assert set(result['branches']['attendance']['targets'])=={'A','B'}
    assert not n.calls and not list((tmp_path/'private').glob('last-good-*'))


def test_staging_reports_target_plan_results_separately(tmp_path):
    n=Native();n.source=lambda _:{'file_id':'source','fingerprint':'hash','tabs':[{'id':1}]}
    cfg={'targets':{'A':{'id':'A','role':'MASTER_V23'},'B':{'id':'B','role':'SEPTEMBER_V22'}},
         'source_files':['source'],'as_of':'2026-11-17'}
    def adapter(payload):
        return {'complete':True,'validation':'PASS','coverage':{'source':{'fingerprint':'hash','tabs':{'1':{'state':'PARSED'}}}},
                'normalized':{},'tables':{'A':[table([])],'B':[table([])]},'plan_blockers':{'A':'REVIEW_REQUIRED'}}
    _,s=stage_run(cfg,n,state(tmp_path),adapters={'lead':adapter})
    assert s['branches']['lead']['state']=='PARTIAL'
    assert s['branches']['lead']['targets']['A']['state']=='PARTIAL'
    assert s['branches']['lead']['targets']['B']['state']=='READY'
    assert not n.calls


def test_adapter_diagnostics_do_not_expose_worker_records_or_urls():
    out={'coverage':{'private-source':{'tabs':{'private-tab':{'state':'UNVERIFIED','critical_errors':2,'excluded_errors':285}}}},
         'normalized':{'leads':[{'name':'SENSITIVE','phone':'SENSITIVE'}],
          'legacy_sales_audit':{'counts':{'unknown_date':5,'name':'SENSITIVE'},'quarantine':[{'source':'SENSITIVE'}]},
          'event_alias_review':{'A':[{'person':'SENSITIVE'}]}}}
    d=adapter_diagnostics(out)
    assert d['critical_formula_errors']==2 and d['event_alias_groups']=={'A':1}
    assert 'SENSITIVE'not in json.dumps(d)and 'private-source'not in json.dumps(d)


def test_every_tab_needs_semantic_coverage_not_just_matching_counts():
    bundle={'sources':[{'file_id':'one','fingerprint':'x','tabs':[{'id':'visible'},{'id':'new_hidden'}]}]}
    output={'complete':True,'coverage':{'one':{'fingerprint':'x','tabs':{'visible':{'state':'PARSED'}}}}}
    with pytest.raises(SyncBlocked,match='TAB_COVERAGE'):validate_envelope(output,bundle)
    output['coverage']['one']['tabs']['new_hidden']={'state':'VERIFIED_OUT_OF_SCOPE','reason_code':'PRIOR_YEAR'}
    validate_envelope(output,bundle)
    output['coverage']['one']['fingerprint']='old'
    with pytest.raises(SyncBlocked,match='FINGERPRINT_CHANGED'):validate_envelope(output,bundle)


def test_protected_source_period_override_and_meta_filter():
    for sid,col in [(7304,12),(7502,8)]:
        req={'updateCells':{'start':{'sheetId':sid,'rowIndex':3,'columnIndex':col},'fields':'userEnteredValue','rows':[{'values':[{}]}]}}
        with pytest.raises(UnsafeSyncPlan):validate_plan_writes([req],{'installed':True,'workbook_role':'MASTER_V23'})


def test_audit_failure_cannot_advance_last_good(tmp_path):
    n=Native();st=state(tmp_path);s=stage(n)
    original=n.snapshot;count=[0]
    def snapshot(id):
        count[0]+=1;r=original(id)
        # A late formula failure, outside the rows just read back.
        if count[0]>14:r['cells']['7950:100:1']={'effectiveValue':{'errorValue':{'type':'REF'}}}
        return r
    n.snapshot=snapshot
    r=execute_stage('r',s,n,st,apply=True)
    assert all(v['state']=='PARTIAL'for v in r['targets'].values())
    assert not list(st.root.glob('last-good-*'))


def test_bonus_master_and_legacy_copy_have_separate_ownership():
    s=snap();s['sheets'] += [{'sheetId':7401,'title':'TH_THUONG','gridProperties':{'rowCount':3000,'columnCount':22}}]
    req={'updateCells':{'start':{'sheetId':7401,'rowIndex':10,'columnIndex':0},'rows':[{'values':[{}]}],'fields':'userEnteredValue'}}
    validate_owned([req],s,'SEPTEMBER_V22','bonus',[[7401,3,3000,0,14]])
    with pytest.raises((SyncBlocked,UnsafeSyncPlan)):validate_owned([req],s,'MASTER_V23','bonus',[[7401,3,3000,0,14]])
    req['updateCells']['start']['columnIndex']=14
    with pytest.raises(UnsafeSyncPlan):validate_owned([req],s,'SEPTEMBER_V22','bonus',[[7401,3,3000,0,22]])


def test_partial_target_does_not_block_other_target_or_unrelated_branch(tmp_path):
    native=Native();st=state(tmp_path);staged=stage(native)
    plan=staged['branches']['pv_ob']
    plan['state']='PARTIAL';plan['targets']={'A':{'state':'PARTIAL'},'B':{'state':'READY'}}
    plan['plans']['A']['changes']=[{'key':'7500:3:5','before':{},'after':{'stringValue':'verified-event'}}]
    before=copy.deepcopy(native.s)
    report=execute_stage('branch-target',staged,native,st)
    assert report['targets']['A']['branches']['pv_ob']=='PARTIAL_DRY_RUN_READY'
    assert report['targets']['A']['branches']['attendance']=='PARTIAL'
    assert report['targets']['A']['branches']['meta']=='DRY_RUN_READY'
    assert report['targets']['B']['branches']['attendance']=='DRY_RUN_READY'
    assert report['validated_subsets']['A']['pv_ob']['checkpoint_can_advance']is False
    assert native.s==before and not native.calls and not list(st.root.glob('last-good-*'))


def test_partial_write_requires_exact_approved_hash_and_retains_last_good(tmp_path):
    native=Native();st=state(tmp_path);staged=stage(native)
    plan=staged['branches']['lead'];plan['state']='PARTIAL'
    plan['targets']={'A':{'state':'PARTIAL'},'B':{'state':'READY'}}
    st.save('last-good-A-lead.json',{'run_id':'previous'})
    staged['config']['approved_partial_plan_hashes']={'A':{'lead':digest(plan['plans']['A'])}}
    report=execute_stage('approved-subset',staged,native,st,apply=True)
    assert report['targets']['A']['branches']['lead']=='PARTIAL_VERIFIED'
    assert report['targets']['B']['branches']['lead']=='VERIFIED'
    assert st.read('last-good-A-lead.json')=={'run_id':'previous'}
    assert st.read('last-good-B-lead.json')['run_id']=='approved-subset'


def test_missing_sales_transport_only_blocks_its_consumers():
    from src.sync_runner import branch_bundle
    options={'source_roles':{'sale_le':'sales','pv':'pv','ob':'ob'}}
    cfg={'adapters':{name:{'options':options}for name in BRANCHES}}
    bundle={'transport_scan_complete':False,'sources':[{'file_id':'pv'},{'file_id':'ob'}]}
    assert branch_bundle(cfg,'pv_ob',bundle)['transport_scan_complete'] is True
    assert branch_bundle(cfg,'lead',bundle)['transport_scan_complete'] is False
    assert branch_bundle(cfg,'attendance',bundle)['transport_scan_complete'] is False
    assert branch_bundle(cfg,'meta',bundle)['transport_scan_complete'] is True


def test_conflicting_fee_row_stays_unchanged_while_new_row_plans():
    s=snap();s['sheets'][0]['sheetId']=7851
    s['cells']={'7851:0:0':{'userEnteredValue':{'stringValue':'ID'}},
                '7851:0:1':{'userEnteredValue':{'stringValue':'Amount'}},
                '7851:1:0':{'userEnteredValue':{'stringValue':'old'}},
                '7851:1:1':{'userEnteredValue':{'numberValue':12}}}
    tbl=table([['old',99],['new',42]]);tbl.update(sheet_id=7851,immutable_existing=True,identity_basis='attendance_episode_period')
    held=[];changes,guards=table_upserts(s,tbl,quarantined=held)
    assert {c['key']for c in changes}=={'7851:2:0','7851:2:1'}
    assert held[0]['reason']=='HISTORICAL_FACT_CONFLICT'
    assert '7851:1:0'not in guards
