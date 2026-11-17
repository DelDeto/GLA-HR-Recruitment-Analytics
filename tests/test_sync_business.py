import copy
from datetime import datetime,timezone,timedelta
import hashlib
import json
import os
from pathlib import Path
import pytest
from src.sync_business import load_verified,coverage,envelope,native_source,table,prior_roster,attendance_files
from src.sync_runtime import SyncBlocked,PrivateState
from src.sync_runner import preflight_access,validate_envelope
from src.sync_plan import validate_owned
from src.sync_safety import UnsafeSyncPlan
from src.sync_meta_snapshot import validate,capture
from src.sync_scope import project,check_common,compare_facts
from src.sync_sources import GoogleTransport


def cell(s,sid,row,col,value):
    kind='boolValue'if isinstance(value,bool)else'numberValue'if isinstance(value,(int,float))else'stringValue'
    s['cells'][f'{sid}:{row}:{col}']={'userEnteredValue':{kind:value},'effectiveValue':{kind:value}}


def empty():return {'cells':{},'sheets':[],'id':'synthetic'}


def test_program_requires_both_local_sha_and_live_anchor(tmp_path):
    p=tmp_path/'program.py';p.write_text('VERSION = 7\n')
    sha=hashlib.sha256(p.read_bytes()).hexdigest();s=empty()
    cell(s,1,0,0,p.read_text());cell(s,1,1,0,sha)
    spec={'path':str(p),'sha256':sha,'anchor':{'sheet_id':1,'row':0,'column':0,'hash_row':1}}
    assert load_verified(spec,s,'synthetic_private_module').VERSION==7
    cell(s,1,0,0,'VERSION = 8\n')
    with pytest.raises(SyncBlocked,match='LIVE_BUSINESS_ANCHOR_CHANGED'):load_verified(spec,s,'synthetic_private_module')
    cell(s,1,0,0,p.read_text());cell(s,1,1,0,'wrong')
    with pytest.raises(SyncBlocked,match='DECLARED_SHA'):load_verified(spec,s,'synthetic_private_module')
    p.write_text('VERSION = 9\n')
    with pytest.raises(SyncBlocked,match='BUSINESS_PROGRAM_SHA_MISMATCH'):load_verified(spec,s,'synthetic_private_module')


def test_source_headers_and_new_tabs_are_not_silently_certified():
    bundle={'transport_scan_complete':True,'sources':[{'file_id':'source','fingerprint':'hash',
        'tabs':[{'id':1,'name':'data','rows':[[0,[[0,'Day'],[1,'Hours']]], [1,[[0,1],[1,0]]]]}]}]}
    payload={'sources':bundle};options={'version':'test','tab_contracts':{'source':{'1':{
        'header_row':0,'headers':{'0':'Day','1':'Hours'},'parser':'daily','state':'PARSED'}}}}
    out=envelope(payload,options,{}, {'source'});validate_envelope(out,bundle)
    bundle['sources'][0]['tabs'].append({'id':2,'name':'new','rows':[[0,[[0,'Unknown']]]]})
    out=envelope(payload,options,{}, {'source'})
    assert out['complete']is False
    with pytest.raises(SyncBlocked):validate_envelope(out,bundle)
    bundle['sources'][0]['tabs'].pop();bundle['transport_scan_complete']=False
    assert envelope(payload,options,{}, {'source'})['validation']=='PARTIAL'


def test_native_recruitment_bridge_retains_hidden_zero_and_sparse_columns():
    source={'file_id':'source','tabs':[{'id':10,'name':'data','hidden':True,'rows':[[3,[[0,0],[5,False]]]]}]}
    out=native_source(source)
    row=out['sheets'][0]['data'][0]['rowData'][0]['values']
    assert row[0]['effectiveValue']=={'numberValue':0}
    assert row[5]['effectiveValue']=={'boolValue':False}
    assert row[1]=={}


def test_identical_roster_alias_dedups_in_memory_without_deleting_rows():
    s=empty()
    for r in [3,5]:
        for c,x in enumerate(['Factory','E123','Test Candidate',46266,'','','source','EP','']):cell(s,7305,r,c,x)
    before=copy.deepcopy(s)
    assert len(prior_roster(s))==1 and s==before
    cell(s,7305,5,4,46280)
    with pytest.raises(SyncBlocked,match='CONFLICTING_PRIOR'):prior_roster(s)


def test_bonus_cache_owned_but_live_array_and_program_archive_protected():
    s=empty();s['sheets']=[{'sheetId':i,'gridProperties':{'rowCount':6500,'columnCount':24}}for i in [7907,7908]]
    def request(sid,r):return {'updateCells':{'start':{'sheetId':sid,'rowIndex':r,'columnIndex':0},
        'rows':[{'values':[{'userEnteredValue':{'stringValue':'award'}}]}],'fields':'userEnteredValue'}}
    validate_owned([request(7908,2000)],s,'MASTER_V23','bonus',[[7908,2000,5000,0,22]])
    for sid,r in [(7908,99),(7908,1999),(7908,5000),(7907,3)]:
        with pytest.raises((SyncBlocked,UnsafeSyncPlan)):
            validate_owned([request(sid,r)],s,'MASTER_V23','bonus',[[sid,0,6500,0,24]])


def test_original_xlsx_blob_is_private_immutable_and_idempotent(tmp_path):
    state=PrivateState(tmp_path/'private');path=state.save_blob('source.xlsx',b'original')
    assert path.stat().st_mode&0o077==0
    assert state.save_blob('source.xlsx',b'original')==path
    with pytest.raises(SyncBlocked):state.save_blob('source.xlsx',b'changed')
    with pytest.raises(SyncBlocked):state.save_blob('../source.xlsx',b'data')


def test_new_native_attendance_file_is_discovered_and_materialized_deterministically(tmp_path):
    from src.sync_runtime import digest
    import openpyxl
    source={'file_id':'new-file','metadata':{'name':'FEVC','mimeType':'application/vnd.google-apps.spreadsheet'},
        'tabs':[{'id':1,'name':'T10 2026','rows':[[0,[[0,'Hours'],[1,'=1+2']]], [1,[[0,0]]]]}]}
    source['fingerprint']=digest(source['tabs'])
    payload={'sources':{'sources':[source]}}
    options={'source_roles':{'ob':'other'},'attendance_files':[]}
    files=attendance_files(payload,options,tmp_path);path=Path(files[0]['path']);raw=path.read_bytes()
    assert len(files)==1 and files[0]['id']=='new-file'
    attendance_files(payload,options,tmp_path);assert raw==path.read_bytes()
    book=openpyxl.load_workbook(path,data_only=False)
    assert book.active['B1'].value=='=1+2' and book.active['B1'].data_type=='s'
    assert book.active['A2'].value==0
    source['tabs'][0]['name']='invalid/name'
    source['fingerprint']=digest(source['tabs'])
    with pytest.raises(SyncBlocked,match='TITLE_MAPPING_REQUIRED'):attendance_files(payload,options,tmp_path)


def test_preflight_checks_both_targets_and_source_without_write_probe(tmp_path):
    class Transport:
        def __init__(self):self.calls=[]
        def file_info(self,id):
            self.calls.append(id);return {'capabilities':{'canEdit':id!='B'}}
    t=Transport();state=PrivateState(tmp_path/'private')
    config={'targets':{'A':{'id':'A'},'B':{'id':'B'}},'source_files':['source'],'source_folders':['folder']}
    with pytest.raises(SyncBlocked,match='ACCESS_BLOCKED'):preflight_access(config,t,state)
    assert set(t.calls)=={'A','B','source','folder'}
    assert state.read('access-preflight.json')['B']['state']=='BLOCKED'


def test_application_credentials_file_is_supported_without_exposing_contents(monkeypatch,tmp_path):
    from google.oauth2.service_account import Credentials
    import google.auth.transport.requests
    monkeypatch.delenv('GOOGLE_SERVICE_ACCOUNT_JSON',raising=False)
    path=tmp_path/'credential.json';path.write_text('{}')
    monkeypatch.setenv('GOOGLE_APPLICATION_CREDENTIALS',str(path))
    calls=[];credential=object()
    monkeypatch.setattr(Credentials,'from_service_account_file',lambda path,scopes:(calls.append((path,scopes))or credential))
    monkeypatch.setattr(google.auth.transport.requests,'AuthorizedSession',lambda c:c)
    assert GoogleTransport.from_env().session is credential
    assert calls[0][0]==str(path)and 'https://www.googleapis.com/auth/drive.readonly'in calls[0][1]


def test_missing_runtime_credentials_do_not_fall_back_to_connected_user(monkeypatch):
    monkeypatch.delenv('GOOGLE_SERVICE_ACCOUNT_JSON',raising=False)
    monkeypatch.delenv('GOOGLE_APPLICATION_CREDENTIALS',raising=False)
    with pytest.raises(SyncBlocked,match='GOOGLE_SERVICE_ACCOUNT_JSON_MISSING'):GoogleTransport.from_env()


def meta_fixture():
    now=datetime(2026,11,17,tzinfo=timezone.utc)
    snapshot={'source':'META_MARKETING_API_DIRECT','validation':'PASS','currency':'VND',
        'captured_at':now.isoformat(),'accounts':['account'],'from':'2026-01-01','to':'2026-11-17',
        'rows':[['2026-01-02','campaign','Campaign',10,100,2,0,'VND','account']],
        'scopes':[['account','Account','2026-01-01','2026-11-17',1,10,'VND','Asia/Ho_Chi_Minh',now.isoformat(),'META_MARKETING_API_DIRECT','COMPLETE']]}
    return snapshot,{'accounts':['account'],'from':'2026-01-01'},now


def test_meta_snapshot_rejects_stale_duplicate_or_missing_account():
    s,o,now=meta_fixture();assert validate(s,o,'2026-11-17',now=now)
    with pytest.raises(SyncBlocked,match='STALE'):validate(s,o,'2026-11-17',now=now+timedelta(days=2))
    s['rows']*=2;s['scopes'][0][4]=2;s['scopes'][0][5]=20
    with pytest.raises(SyncBlocked,match='DUPLICATE'):validate(s,o,'2026-11-17',now=now)
    s,o,now=meta_fixture();o['accounts'].append('missing')
    with pytest.raises(SyncBlocked,match='SCOPE_MISMATCH'):validate(s,o,'2026-11-17',now=now)


def test_empty_meta_response_remains_review_required():
    class Meta:
        def _request(self,path,params):return {'id':'123','name':'Account','currency':'VND','timezone_name':'Asia/Ho_Chi_Minh'}
        def insights(self,*args):return []
    from datetime import date
    s=capture(['123'],date(2026,11,1),date(2026,11,17),Meta())
    assert s['validation']=='EMPTY_REQUIRES_REVIEW'
    with pytest.raises(SyncBlocked):validate(s,{'accounts':['account'],'from':'2026-11-01'},'2026-11-17')


def calendar_fixture():
    s=empty()
    for c,x in enumerate(['Factory',46266,46630,100,90,True,'policy','','','','NGÀY LỊCH','']):cell(s,6240,150,c,x)
    for c,x in enumerate(['Factory','E123','Candidate',46266,'','','source','EP']):cell(s,7305,3,c,x)
    return s


def test_independent_calendar_counts_first_day_and_caps_exclusive_stop():
    s=calendar_fixture();scope={'from':'2026-09-01','to':'2026-09-07','group':'LĐPT','factory':'Tất cả'}
    rows,_=project(s,scope);assert rows[3]['value']==6*8*100
    rows,_=project(s,scope,stops={'EP':'2026-09-03'});assert rows[3]['value']==2*8*100
    cell(s,7305,3,4,46266)
    rows,_=project(s,scope);assert rows[3]['value']==8*100


def test_same_scope_recomputation_preserves_zero_and_unknown():
    s=calendar_fixture();scope={'from':'2026-10-01','to':'2026-10-31','group':'LĐPT','factory':'Tất cả'}
    cell(s,6240,150,4,1)
    rows,totals=project(s,scope);assert rows[3]['value']==0 and list(totals.values())==[0]
    cell(s,6240,150,5,False)
    rows,totals=project(s,scope);assert rows[3]['value']is None and list(totals.values())==[None]


def test_common_projection_fails_if_native_baseline_is_not_matched():
    s=calendar_fixture();cell(s,7000,5,1,46266);cell(s,7000,5,4,46272);cell(s,7503,3,9,999)
    with pytest.raises(SyncBlocked,match='BASELINE_MISMATCH'):
        check_common({'A':s,'B':s},{'from':'2026-09-01','to':'2026-09-07','group':'LĐPT','factory':'Tất cả'})


def test_native_parity_does_not_coerce_unknown_to_zero():
    a=empty();a['sheets']=[{'sheetId':sid,'gridProperties':{'rowCount':5}}for sid in [7500,7501,7851,7852]]
    for c,x in enumerate([46266,'Factory','LĐPT',0]):cell(a,7500,3,c,x)
    b=copy.deepcopy(a);b['cells'].pop('7500:3:3')
    scope={'from':'2026-09-01','to':'2026-09-30','group':'LĐPT','factory':'Tất cả'}
    with pytest.raises(SyncBlocked,match='FACTS_DIFFER'):compare_facts({'A':a,'B':b},scope)
