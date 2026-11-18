from dataclasses import replace
import pytest
from src import meta_dual_sync as dual
from src.meta_sync import GoogleSheets, SyncError, campaign_updates
from test_meta_sync import FakeSheets, FakeMeta, make_settings


def test_secondary_preflight_failure_cannot_write_primary(monkeypatch):
    calls=[]
    def sync(config,*args):
        calls.append((config.spreadsheet_id,config.dry_run))
        if config.spreadsheet_id=='B':raise SyncError('bad schema')
        return {}
    monkeypatch.setattr(dual,'sync',sync)
    with pytest.raises(SyncError):dual.run(make_settings(False),sheet_factory=lambda *x:FakeSheets(),
        meta=FakeMeta(),resolve_secondary=lambda _: 'B')
    assert calls==[('test-sheet',True),('B',True)]


def test_write_failure_remains_partial_while_other_target_can_finish(monkeypatch):
    def sync(config,*args):
        if not config.dry_run and config.spreadsheet_id=='test-sheet':raise SyncError('private payload')
        return {'changed':0}
    monkeypatch.setattr(dual,'sync',sync)
    report=dual.run(make_settings(False),sheet_factory=lambda *x:FakeSheets(),
        meta=FakeMeta(),resolve_secondary=lambda _: 'B')
    assert report['state']=='PARTIAL'
    assert report['targets']['A']['state']=='PARTIAL'
    assert report['targets']['B']['state']=='SUCCESS'
    assert 'private payload'not in str(report)


def test_native_readback_failure_never_writes_success_checkpoint():
    from src.meta_sync import sync
    class FailedReadback(FakeSheets):
        def verify_ranges(self,*args,**kwargs):raise SyncError('mismatch')
    sheet=FailedReadback()
    with pytest.raises(SyncError,match='mismatch'):sync(make_settings(False),FakeMeta(),sheet)
    assert len(sheet.changes)==1
    assert not any('META_SYNC_HEALTH'in r for mode,changes in sheet.changes for r,rows in changes)


def test_meta_calls_are_cached_without_sharing_mutable_rows():
    class API(FakeMeta):
        def __init__(self):self.calls=0
        def insights(self,*args):self.calls+=1;return [['original']]
    api=API();cache=dual.CachedMeta(api)
    first=cache.insights('account','begin','end','VND');first[0][0]='changed'
    assert cache.insights('account','begin','end','VND')==[['original']]
    assert api.calls==1


@pytest.mark.parametrize('name',['=IMPORTXML("bad")','2026-11-18',"'quoted",'Ordinary campaign'])
def test_new_campaign_names_are_literal_under_user_entered(name):
    incoming=[[1,'123456789',name,1,1,1,0,'VND','account']]
    row=campaign_updates([],incoming,100)[0][1][0]
    assert row[1]=="'"+name


def test_native_readback_compares_formulas_and_literal_escape():
    class Sheet(GoogleSheets):
        def __init__(self):pass
        def _request(self,*args,**kwargs):
            return {'valueRanges':[{'values':[['123','=1+1','=SUM(A1:A2)']]}]}
    Sheet().verify_ranges([('Data!A1:C1',[["'123","'=1+1",'=SUM(A1:A2)']])],mode='USER_ENTERED')
    with pytest.raises(SyncError,match='readback'):
        Sheet().verify_ranges([('Data!A1:C1',[['wrong','=1+1','=SUM(A1:A2)']])])
