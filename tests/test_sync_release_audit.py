import copy
import pytest
from src.sync_runtime import SyncBlocked,digest
from src.sync_source_audit import formula_error_audit,source_scope_audit,resolve_contracts,phone
from src.sync_plan import table_upserts
from src.sync_fact_audit import audit_table
from src.sync_legacy_leads import review,merge_receipts


def snapshot(sid=7305):
    return {'cells':{},'sheets':[{'sheetId':sid,'gridProperties':{'rowCount':20,'columnCount':25}}]}


def put(s,sid,r,c,x,formula=None):
    value={'boolValue'if isinstance(x,bool)else'numberValue'if isinstance(x,(int,float))else'stringValue':x}
    s['cells'][f'{sid}:{r}:{c}']={'userEnteredValue':{'formulaValue':formula}if formula else value,'effectiveValue':value}


def test_native_errors_exclude_only_fields_proven_unused_by_the_consumer():
    t={'id':1,'rows':[[0,[[0,'ID'],[5,'Phone'],[32,'CV']]],
        [1,[[5,912345678]]],[2,[[32,'https://example.invalid/cv']]], [3,[[1,'Candidate']]]],
        'formula_errors':[{'row':r,'column':0,'type':'VALUE'}for r in (1,2,3)]}
    c={'state':'PARSED','parser':'CRM_APPLICANTS','header_row':0,'headers':{'0':'ID'},'consumed_columns':[0,1,5,32]}
    audit=formula_error_audit(t,c)
    assert [x['state']for x in audit]==['EXCLUDED','EXCLUDED','CRITICAL']
    assert audit[-1]['reason']=='CRM_IDENTITY_MISSING_WITH_FORMULA_ERROR'
    assert source_scope_audit({'tabs':[t]},{'1':c})['1']['state']=='UNVERIFIED'
    assert phone(912345678)=='0912345678'
    assert phone('84912345678')=='0912345678'
    assert phone(841234567)=='0841234567'
    assert phone(912345678.0)=='0912345678'


def test_consumed_date_or_hours_error_cannot_be_treated_as_zero():
    t={'id':'tab','rows':[[0,[[0,'Date'],[1,'Hours']]]],
       'formula_errors':[{'row':1,'column':1,'type':'REF'}]}
    c={'state':'PARSED','parser':'ATTENDANCE','consumed_columns':[0,1]}
    a=formula_error_audit(t,c)
    assert a[0]['state']=='CRITICAL'
    assert all('value'not in x for x in a)


def test_tab_exclusion_does_not_survive_unreviewed_content_change():
    t={'id':1,'rows':[[0,[[0,'Audit']]]],'formula_errors':[{'row':1,'column':1,'type':'REF'}]}
    c={'state':'VERIFIED_OUT_OF_SCOPE','header_row':0,'headers':{'0':'Audit'},'reason_code':'REPORT_ONLY','content_sha':digest(t)}
    assert source_scope_audit({'tabs':[t]},{'1':c})['1']['state']=='VERIFIED_OUT_OF_SCOPE'
    t['rows'].append([2,[[0,'New input']]])
    assert source_scope_audit({'tabs':[t]},{'1':c})['1']['state']=='UNVERIFIED'


def test_new_tab_can_reuse_reviewed_parser_but_not_an_exclusion():
    source={'file_id':'new','metadata':{'name':'USI new.xlsx'},'tabs':[{'id':'T11','rows':[[0,[[0,'ID'],[1,'Name']]]]}]}
    template={'source_role':'attendance','filename_token':'USI','state':'PARSED','parser':'USI',
        'header_row':0,'headers':{'0':'ID','1':'Name'},'consumed_all_columns':True}
    assert resolve_contracts(source,{'schema_templates':[template]})['T11']['consumed_columns']==[0,1]
    template['state']='VERIFIED_OUT_OF_SCOPE'
    assert resolve_contracts(source,{'schema_templates':[template]})=={}


def roster_table():
    return {'sheet_id':7305,'start_row':1,'end_row':20,'columns':list(range(9)),'key_columns':[7],
        'expected_headers':{str(c):str(c)for c in range(9)},'identity_basis':'event_episode',
        'retain_duplicate_identity_columns':[0,1,2,3,4,7],'preserve_existing_columns':[6,8],
        'rows':[['Factory','E123','Candidate',46266,None,'','new-source','EP','new-proof']]}


def test_identical_roster_rows_keep_both_ids_and_provenance_without_appending():
    s=snapshot();t=roster_table()
    for c in range(9):put(s,7305,0,c,str(c))
    for row,source in [(1,'old-source-a'),(4,'old-source-b')]:
        for c,x in enumerate(['Factory','E123','Candidate',46266,None,'',source,'EP','old-proof']):
            if x is not None:put(s,7305,row,c,x)
    before=copy.deepcopy(s);changes,_=table_upserts(s,t)
    assert changes==[]and s==before
    put(s,7305,4,2,'Different candidate')
    with pytest.raises(SyncBlocked,match='DUPLICATE_EXISTING_KEY'):table_upserts(s,t)


def test_formula_group_is_verified_and_preserved_in_place():
    s=snapshot(7501)
    for c,x in enumerate(['Key','Group']):put(s,7501,0,c,x)
    put(s,7501,1,0,'event');put(s,7501,1,1,'LĐPT',formula='=GROUP_LOOKUP()')
    t={'sheet_id':7501,'start_row':1,'end_row':20,'columns':[0,1],'key_columns':[0],
        'expected_headers':{'0':'Key','1':'Group'},'identity_basis':'event_episode','rows':[['event','LĐPT']],
        'verified_formula_columns':[1]}
    changes,guards=table_upserts(s,t)
    assert not changes and guards['7501:1:1']['after']=={'formulaValue':'=GROUP_LOOKUP()'}
    t['rows'][0][1]='IDL'
    with pytest.raises(SyncBlocked,match='PRESERVED_FORMULA_VALUE_DIFFERS'):table_upserts(s,t)


def test_provenance_retention_cannot_suppress_a_fee_amount_difference():
    s=snapshot(7851)
    for c in [0,8,10,12]:put(s,7851,0,c,str(c))
    for c,x in [(0,46266),(8,100),(10,'old-source'),(12,'EP')]:put(s,7851,1,c,x)
    t={'sheet_id':7851,'start_row':1,'end_row':20,'columns':[0,8,10,12],'key_columns':[0,12],
       'expected_headers':{str(c):str(c)for c in [0,8,10,12]},'identity_basis':'attendance_episode_period',
       'immutable_existing':True,'preserve_existing_columns':[10],'rows':[[46266,200,'new-source','EP']]}
    audit=audit_table(s,t)
    assert audit[0]['classification']=='FEE_OR_ELIGIBILITY_REVIEW'
    assert audit[0]['changes'][0]=={'column':8,'before':100,'proposed':200}
    with pytest.raises(SyncBlocked,match='HISTORICAL_FACT_CONFLICT'):table_upserts(s,t)
    t['preserve_existing_columns'].append(8)
    with pytest.raises(SyncBlocked,match='PRESERVE_COLUMN_NOT_PROVENANCE'):table_upserts(s,t)


def test_cold_sales_rows_are_retained_and_not_automatically_added_to_leads():
    from datetime import date
    source={'file_id':'sale','tabs':[{'id':1,'rows':[[0,[[0,'Date'],[1,'Full Name'],[2,'Contact']]],
        [1,[[0,'2026-11-01'],[1,'Candidate'],[2,'0912345678']]],
        [2,[[0,'2026-11-02'],[1,'Other'],[2,'0987654321']]], [3,[[1,'No date'],[2,'0977777777']]]]}]}
    opts={'source_roles':{'sale_le':'sale'},'tab_contracts':{'sale':{'1':{'parser':'LEGACY_SALES_AUDIT','header_row':0}}}}
    r=review([source],opts,[{'date':'2026-11-01','phone':'0912345678'}],lambda x:date.fromisoformat(x)if x else None,'2026-11-17')
    assert r['counts']=={'already_counted':1,'outside_period':0,'unknown_date':1,'needs_review':1}
    assert all(x['included_in_lead_count']is False for x in r['quarantine'])


def test_user_confirmed_cold_intake_merges_with_stable_factory_group_keys():
    from datetime import date
    source={'file_id':'sale','tabs':[{'id':1,'name':'Factory','rows':[[0,[[0,'Date'],[1,'Full Name'],[2,'Contact']]],
        [1,[[0,'2026-11-01'],[1,'Candidate'],[2,'0912345678']]],
        [2,[[0,'2026-11-02'],[1,'New candidate'],[2,'0987654321']]],
        [3,[[0,'2026-11-02'],[1,'New candidate'],[2,'0987654321']]],
        [4,[[1,'Unknown date'],[2,'0977777777']]]]}]}
    opts={'source_roles':{'sale_le':'sale'},'legacy_intake_confirmed':True,'legacy_default_group':'LĐPT',
        'tab_contracts':{'sale':{'1':{'parser':'LEGACY_SALES_AUDIT','header_row':0}}}}
    base=[{'date':'2026-11-01','phone':'0912345678','identity':'0912345678','group':'LĐPT','factory':'Factory'}]
    result=review([source],opts,base,lambda x:date.fromisoformat(x)if x else None,'2026-11-17',lambda x:x)
    merged,duplicates=merge_receipts(base,result['receipts'])
    assert len(merged)==2 and duplicates==2
    assert result['counts']['unknown_date']==1
    assert len(result['quarantine'])==1
    assert result['receipts'][0]['group']=='LĐPT'


def test_student_marker_wins_without_merging_two_ldpt_factory_intakes():
    rows=[{'date':'2026-11-01','phone':'0912345678','identity':'0912345678','group':'LĐPT','factory':f}for f in ['Factory A','Factory B']]
    assert len(merge_receipts(rows,[])[0])==2
    student=dict(rows[0],group='IDL SV')
    merged,_=merge_receipts(rows,[student])
    assert merged==[student]


def test_native_source_keeps_errors_typed_for_consumer_scope_checks():
    from src.sync_sources import GoogleTransport
    t=GoogleTransport(None)
    t.file_info=lambda _:{'mimeType':'application/vnd.google-apps.spreadsheet','version':'1'}
    s=snapshot(1);s['sheets'][0].update(title='Data')
    put(s,1,0,0,'Hours');put(s,1,1,0,0)
    s['cells']['1:2:0']={'effectiveValue':{'errorValue':{'type':'REF'}}}
    t.snapshot=lambda _:s
    out=t.source('source')
    assert out['tabs'][0]['formula_errors']==[{'row':2,'column':0,'type':'REF'}]
    assert out['tabs'][0]['rows'][1]==[1,[(0,0)]]
    assert len(out['fingerprint'])==64


def test_historical_lead_backfill_can_increase_but_not_reduce_known_counts():
    s=snapshot(7500)
    for c in range(4):put(s,7500,0,c,str(c))
    for c,x in enumerate([46266,'Factory','LĐPT',10]):put(s,7500,1,c,x)
    t={'sheet_id':7500,'start_row':1,'end_row':20,'columns':[0,1,2,3],'key_columns':[0,1,2],
       'expected_headers':{str(c):str(c)for c in range(4)},'identity_basis':'lead_day_group_phone',
       'nondecreasing_columns':[3],'rows':[[46266,'Factory','LĐPT',12]]}
    changes,_=table_upserts(s,t);assert changes[0]['after']=={'numberValue':12}
    t['rows'][0][3]=9
    with pytest.raises(SyncBlocked,match='HISTORICAL_LEAD_COUNT_DECREASE_REVIEW'):table_upserts(s,t)
