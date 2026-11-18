import hashlib
import pytest
from src import sync_deployment as deploy
from src.sync_runtime import PrivateState, SyncBlocked
from src.sync_source_audit import resolve_contracts, validate_contract


def test_changed_native_program_blocks_entire_install_before_saving(monkeypatch,tmp_path):
    text='VALUE = 1\n';sha=hashlib.sha256(text.encode()).hexdigest()
    monkeypatch.setattr(deploy,'PROGRAMS',{
        'one':('one.py',1,0,0,None,sha),'two':('two.py',1,1,0,None,sha)})
    snapshot={'cells':{'1:0:0':{'effectiveValue':{'stringValue':text}},
                       '1:1:0':{'effectiveValue':{'stringValue':text+'# changed'}}}}
    state=PrivateState(tmp_path/'private')
    with pytest.raises(SyncBlocked,match='PROGRAM_CHANGED'):deploy.install_programs(snapshot,state)
    assert list(state.root.iterdir())==[]


def test_first_install_can_never_authorize_production_or_infer_ownership():
    empty={'cells':{}}
    config=deploy.manifest({'A':'a','B':'b','folder':'f','crm':'c'},
        {'A':empty,'B':empty},{},{},[],'2026-11-18')
    assert config['deployment_approved']is False
    assert config['single_writer_private_volume']is False
    for target in config['targets'].values():
        assert [7002,1003,1200,5,10]not in target['ownership']['forecast']
    assert [7950,2,51,48,56]not in config['targets']['A']['ownership']['forecast']
    assert set(config['adapters'])==set(deploy.BRANCHES)


def test_reviewed_title_does_not_approve_changed_headers_or_new_tabs():
    sha=hashlib.sha256(b'Reviewed').hexdigest()
    spec={'state':'PARSED','parser':'CRM_APPLICANTS','header_row':0,
          'headers':{'0':'Applicant ID','1':'Full Name'},'consumed_columns':[0,1]}
    options={'reviewed_title_contracts':{'source':{'by_title_hash':{sha:spec}}}}
    tab={'id':1,'name':'Reviewed','rows':[[0,[[0,'Applicant ID'],[1,'Full Name']]]]}
    source={'file_id':'source','tabs':[tab]}
    contract=resolve_contracts(source,options)['1']
    assert validate_contract(tab,contract)
    tab['rows'][0][1][1][1]='Changed'
    assert not validate_contract(tab,contract)
    tab['name']='New'
    assert resolve_contracts(source,options)=={}


def test_preloaded_snapshots_are_used_once_then_live_readback():
    class Transport:
        def snapshot(self,fid):return 'live'
    transport=deploy.InitialSnapshots(Transport(),{'A':{'id':'a'}})
    assert transport.snapshot('a')=={'id':'a'}
    assert transport.snapshot('a')=='live'


def test_sales_group_detection_consumes_error_only_trailing_columns():
    title='Reviewed';sha=hashlib.sha256(title.encode()).hexdigest()
    tab={'id':1,'name':title,'rows':[[0,[[0,'Date'],[1,'Name']]]],
         'formula_errors':[{'row':1,'column':7,'type':'REF'}]}
    spec={'state':'PARSED','parser':'SALE_LE','header_row':0,
          'headers':{'0':'Date','1':'Name'},'consumed_all_columns':True}
    options={'reviewed_title_contracts':{'source':{'by_title_hash':{sha:spec}}}}
    contract=resolve_contracts({'file_id':'source','tabs':[tab]},options)['1']
    assert contract['consumed_columns']==list(range(8))
