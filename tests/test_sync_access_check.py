import hashlib
import json
import pytest
from src.sync_runtime import PrivateState,SyncBlocked
from src import sync_access_check as check


def test_discovery_follows_only_preapproved_resource_hashes(monkeypatch):
    root='A'*24;source='S'*24;other='U'*24
    monkeypatch.setattr(check,'RESOURCE_HASHES',{'A':hashlib.sha256(root.encode()).hexdigest(),
        'source':hashlib.sha256(source.encode()).hexdigest()})
    assert check.discover([f'https://example.invalid/{source}',other],root)=={'A':root,'source':source}
    with pytest.raises(SyncBlocked,match='MASTER_SECRET'):check.discover([source],other)


def test_hyperlink_labels_cannot_hide_reviewed_resource_references(monkeypatch):
    root='A'*24;source='S'*24
    monkeypatch.setattr(check,'RESOURCE_HASHES',{'A':hashlib.sha256(root.encode()).hexdigest(),
        'source':hashlib.sha256(source.encode()).hexdigest()})
    class Fake:
        def json(self,method,url,params):
            if params.get('fields')=='spreadsheetId,sheets.properties':
                return {'sheets':[{'properties':{'sheetId':6204,'title':'Hints'}}]}
            return {'sheets':[{'data':[{'rowData':[{'values':[{'effectiveValue':{'stringValue':'Open'},
                'userEnteredValue':{'formulaValue':f'=HYPERLINK("https://example.invalid/{source}","Open")'}}]}]}]}]}
    assert check.read_hints(Fake(),root)['source']==source


def test_canary_rejects_any_google_mutation():
    class Fake:
        def __init__(self):self.calls=[]
        def json(self,*args,**kwargs):self.calls.append(args);return {}
    t=check.forbid_writes(Fake());t.json('GET','metadata')
    with pytest.raises(SyncBlocked,match='WRITE_FORBIDDEN'):t.json('POST','metadata')
    with pytest.raises(SyncBlocked,match='WRITE_FORBIDDEN'):t.write('target',[])
    assert len(t.calls)==1


def test_access_check_does_not_confuse_view_permission_with_edit(monkeypatch):
    monkeypatch.setattr(check,'RESOURCE_HASHES',{'A':'a','B':'b','source':'s'})
    class Fake:
        def file_info(self,id):return {'capabilities':{'canEdit':id!='B'}}
    out=check.access_checks(Fake(),{'A':'A','B':'B','source':'source'})
    assert out['A']['state']=='PASS'and out['source']['state']=='PASS'
    assert out['B']=={'state':'BLOCKED','readable':True,'can_edit':False}


def test_credential_errors_never_print_exception_payload(monkeypatch,tmp_path):
    def failed(*args,**kwargs):raise ValueError('SENSITIVE_TOKEN_OR_EMPLOYEE_PAYLOAD')
    monkeypatch.setattr(check.GoogleTransport,'from_env',failed)
    monkeypatch.setattr(check,'meta_check',failed)
    out=check.run_check(PrivateState(tmp_path/'private'),scan_sources=True,read_meta=True)
    assert out['canary_state']=='BLOCKED'and out['release_state']=='BLOCKED'
    assert 'SENSITIVE'not in json.dumps(out)
    assert out['production_writes']==0


def test_passing_canary_cannot_claim_full_v24_readiness(monkeypatch,tmp_path):
    monkeypatch.setattr(check,'RESOURCE_HASHES',{'A':'a','B':'b','folder':'f','source':'s'})
    class Fake:
        def json(self,*args,**kwargs):return {}
        def file_info(self,id):return {'capabilities':{'canEdit':True}}
    monkeypatch.setattr(check.GoogleTransport,'from_env',lambda *args:Fake())
    monkeypatch.setattr(check,'read_hints',lambda *args:{r:r for r in check.RESOURCE_HASHES})
    monkeypatch.setattr(check,'collect_once',lambda *args:{'sources':[],'errors':[],
        'transport_scan_complete':True,'listed_files':1,'parsed_files':1,'listed_tabs':1})
    out=check.run_check(PrivateState(tmp_path/'private'),scan_sources=True)
    assert out['canary_state']=='PASS'
    assert out['release_state']=='BLOCKED'
    assert out['full_v24_e2e'].startswith('NOT_RUN')
