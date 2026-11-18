import pytest
from src.sync_sources import GoogleTransport
from src.sync_runtime import SyncBlocked


def test_snapshot_batches_hidden_tabs_and_keeps_offsets_errors_and_notes():
    class Transport(GoogleTransport):
        def __init__(self):self.calls=[]
        def json(self,method,url,params):
            self.calls.append(params)
            if params['fields']=='spreadsheetId,sheets.properties':
                return {'sheets':[{'properties':{'sheetId':i,'title':f'Tab {i}',
                    'hidden':True,'gridProperties':{'rowCount':1000,'columnCount':50}}}for i in range(6)]}
            return {'sheets':[{'properties':{'sheetId':0},'data':[{'startRow':40,'startColumn':3,
                'rowData':[{'values':[{'effectiveValue':{'errorValue':{'type':'REF'}},'note':'keep'}]}]}]}]}
    t=Transport();snapshot=t.snapshot('target')
    assert len(t.calls)==3
    assert [len(p['ranges'])for p in t.calls[1:]]==[4,2]
    assert snapshot['cells']['0:40:3']['effectiveValue']['errorValue']['type']=='REF'
    assert snapshot['cells']['0:40:3']['note']=='keep'
    assert len(snapshot['sheets'])==6


def test_snapshot_rejects_data_without_a_verified_native_sheet_id():
    class Transport(GoogleTransport):
        def __init__(self):pass
        def json(self,method,url,params):
            if params['fields']=='spreadsheetId,sheets.properties':
                return {'sheets':[{'properties':{'sheetId':1,'title':'Tab',
                    'gridProperties':{'rowCount':1,'columnCount':1}}}]}
            return {'sheets':[{'data':[]}]}
    with pytest.raises(SyncBlocked,match='SHEET_ID_UNVERIFIED'):Transport().snapshot('target')
