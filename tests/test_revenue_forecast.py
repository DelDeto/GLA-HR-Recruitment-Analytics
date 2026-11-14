from datetime import date
from src.revenue_forecast import Source, evaluate, cap_calendar_formula
from src.attendance_presence import match_presence

SEP,OCT,NOV = (date(2026,m,1) for m in (9,10,11))

def complete():
    return Source('COMPLETE','digest','digest','GLA','2026-11-14',True,'source')

def test_continued_presence():
    assert evaluate({SEP:True,OCT:True},{OCT:complete()},identity_ok=True).inferred_stop is None

def test_absence_complete():
    assert evaluate({SEP:True,OCT:False},{OCT:complete()},identity_ok=True).inferred_stop == OCT

def test_missing_source():
    assert evaluate({SEP:True,OCT:False},{},identity_ok=True).inferred_stop is None

def test_partial_source():
    assert evaluate({SEP:True,OCT:False},{OCT:Source('PARTIAL')},identity_ok=True).inferred_stop is None

def test_zero_hours_membership():
    p=[dict(key='episode',factory='F',id='E123',name='Test',join='2026-09-01')]
    r=[dict(factory='F',month='2026-10-01',id='E123',name='Test',join_choices=[],source='source',hours=0)]
    result=match_presence(p,r,[dict(factory='F',month='2026-10-01',imported=True)])
    assert result[0]['presence']['2026-10-01'] is True

def test_official_stop_earliest():
    d=evaluate({SEP:True,OCT:False},{OCT:complete()},identity_ok=True,official_stop=date(2026,9,22),fee_expiry=date(2026,10,8))
    assert d.effective_stop == date(2026,9,22)

def test_ambiguous_identity_blocks():
    assert evaluate({SEP:True,OCT:False},{OCT:complete()},identity_ok=False).status == 'IDENTITY_REVIEW'

def test_rejoin_review_does_not_restart():
    d=evaluate({SEP:True,OCT:False,NOV:True},{OCT:complete()},identity_ok=True)
    assert d.status=='REJOIN_REVIEW' and d.inferred_stop==OCT

def test_reimport_idempotent():
    p=[dict(key='episode',factory='F',id='E123',name='Test',join='2026-09-01')]
    r=dict(factory='F',month='2026-10-01',id='E123',name='Test',join_choices=[],source='source')
    m=[dict(factory='F',month='2026-10-01',imported=True)]
    assert match_presence(p,[r],m)==match_presence(p,[r,r],m)

def test_actual_fees_are_not_mutated():
    fees={'actual':123,'hours':0};before=fees.copy()
    evaluate({SEP:True,OCT:False},{OCT:complete()},identity_ok=True)
    assert fees==before

def test_policy_and_fee_expiry_inclusive():
    d=evaluate({}, {}, identity_ok=True,fee_expiry=date(2026,10,29))
    assert d.effective_stop==date(2026,10,30)

def test_factory_counts_conserve():
    rows=[('A',True),('A',False),('B',True)]
    assert sum(x[1]for x in rows)==sum(sum(x[1]for x in rows if x[0]==f)for f in {'A','B'})

def test_same_inputs_across_workbooks():
    args=({SEP:True,OCT:False},{OCT:complete()})
    assert evaluate(*args,identity_ok=True)==evaluate(*args,identity_ok=True)

def test_jan_aug_cap_guard_and_only_forecast_changes():
    f='=LET(stop,MIN(TONG_QUAN!$E$6,quit-1,join+89),price,15000,stop*price)'
    new=cap_calendar_formula(f,4)
    assert 'MAX(DATE(2026,9,1),FORECAST_V22!$K4)-1' in new
    assert 'quit-1,join+89),price,15000' in new
    assert cap_calendar_formula(new,4)==new

def test_confirmation_is_revision_bound_and_import_required():
    for source in [Source('COMPLETE'),Source('COMPLETE','new','old','GLA','date',True),Source('COMPLETE','x','x','GLA','date',False)]:
        assert source.effective_state()!='COMPLETE'

def test_name_fallback_requires_unique_join_evidence():
    p=[dict(key='episode',factory='F',id='',name='Test',join='2026-09-01')]
    r=dict(factory='F',month='2026-09-01',id='E123',name='Test',join_choices=['2026-09-01'],source='source')
    assert match_presence(p,[r],[dict(factory='F',month='2026-09-01',imported=True)])[0]['identity_ok']
    assert not match_presence(p,[{**r,'join_choices':[]}],[])[0]['identity_ok']

def test_source_error_pending_and_stale_confirmation_cannot_infer():
    for src in [Source('ERROR'),Source('PENDING_CONFIRMATION'),Source('COMPLETE','new','old','A','date',True)]:
        assert evaluate({SEP:True,OCT:False},{OCT:src},identity_ok=True).inferred_stop is None

def test_same_employee_id_two_episodes_needs_join_evidence():
    p=[dict(key='one',factory='F',id='E123',name='Test',join='2026-09-01'),dict(key='two',factory='F',id='E123',name='Test',join='2026-10-01')]
    r=dict(factory='F',month='2026-10-01',id='E123',name='Test',join_choices=[],source='source')
    result=match_presence(p,[r],[dict(factory='F',month='2026-10-01',imported=True)])
    assert all(not x['identity_ok']for x in result)

def test_native_plan_cannot_write_actual_fees_or_policies():
    from src.forecast_sync import build_plan
    from src.forecast_sheets import put
    # Empty/unknown physical layouts must fail before any native write plan.
    import pytest
    with pytest.raises(ValueError):build_plan({'people':[],'sources':[]})
    assert put(7950,4,1,[[0]])['updateCells']['rows'][0]['values'][0]['userEnteredValue']=={'numberValue':0}

def test_raw_missing_id_row_blocks_false_absence(tmp_path):
    import openpyxl
    from src.attendance_presence import read_sources
    wb=openpyxl.Workbook();sh=wb.active;sh.title='Month 10'
    sh.append(['Ngày','Mã nhân viên','Other','Họ tên'])
    sh.append([date(2026,10,1),None,None,'Test Worker'])
    path=tmp_path/'source.xlsx';wb.save(path)
    raw,manifest,errors=read_sources([{'id':'synthetic','name':'PEGATRON.xlsx','path':str(path)}],date(2026,11,14))
    assert not errors and len(raw)==1 and raw[0]['id']==''
    people=[dict(key='one',factory='Pegatron',id='E123',name='Test Worker',join='2026-09-01')]
    assert not match_presence(people,raw,manifest)[0]['identity_ok']
