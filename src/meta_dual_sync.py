"""One Meta writer, two explicitly authorized native workbooks.

Both native plans must pass dry-run before either workbook is written.
The existing META_RAW/campaign/health scope and approved historical decisions
remain unchanged. No employee records or source IDs enter public logs.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import re
from .meta_sync import Settings, GoogleSheets, MetaClient, SyncError, sync

ROOT_HASH='d3ee04aafdbd507a56987c9e577d278bcb478725bf65d876e2ac2104c1203e3b'
SECONDARY_HASH='642e830a76a9f831a736f16c5819214d3aa34eeb7bb2e0c4b7c9b43e056461a2'
HINTS=[(6204,10,4),(6240,117,1),(6240,1799,7),(6240,2337,7),
       (7100,10,7),(7306,10,1),(7506,202,0)]


def secondary(sheet):
    if hashlib.sha256(sheet.id.encode()).hexdigest()!=ROOT_HASH:
        raise SyncError('Authorized master identity mismatch')
    meta=sheet._request('GET','',params={'fields':'sheets.properties'})
    titles={s['properties']['sheetId']:s['properties']['title'] for s in meta['sheets']}
    ranges=["'"+titles[sid].replace("'","''")+"'!"+chr(65+c)+str(r+1)
            for sid,r,c in HINTS if sid in titles]
    if not ranges:raise SyncError('Reviewed master references missing')
    data=sheet._request('GET','',params={'ranges':ranges,'includeGridData':'true',
        'fields':'sheets(data(rowData(values(effectiveValue,userEnteredValue))))'})
    found=set()
    for sh in data.get('sheets',[]):
        for block in sh.get('data',[]):
            for row in block.get('rowData',[]):
                for cell in row.get('values',[]):
                    for field in ('effectiveValue','userEnteredValue'):
                        for kind in ('stringValue','formulaValue'):
                            for candidate in re.findall(r'[A-Za-z0-9_-]{20,}',cell.get(field,{}).get(kind,'')):
                                if hashlib.sha256(candidate.encode()).hexdigest()==SECONDARY_HASH:found.add(candidate)
    if len(found)!=1:raise SyncError('Authorized secondary reference missing or ambiguous')
    return found.pop()


class CachedMeta:
    def __init__(self,api):self.api=api;self.currencies={};self.rows={}
    def currency(self,account):
        if account not in self.currencies:self.currencies[account]=self.api.currency(account)
        return self.currencies[account]
    def insights(self,account,begin,end,currency):
        key=(account,begin,end,currency)
        if key not in self.rows:self.rows[key]=self.api.insights(account,begin,end,currency)
        return deepcopy(self.rows[key])


def run(settings,*,sheet_factory=GoogleSheets,meta=None,resolve_secondary=secondary):
    a=sheet_factory(settings.google_json,settings.spreadsheet_id)
    bid=resolve_secondary(a)
    b=sheet_factory(settings.google_json,bid)
    api=CachedMeta(meta or MetaClient(settings.access_token,settings.api_version))
    targets={'A':(settings,a),'B':(replace(settings,spreadsheet_id=bid),b)}
    plans={}
    for role,(config,sheet)in targets.items():
        plans[role]=sync(replace(config,dry_run=True),api,sheet)
    if settings.dry_run:return {'state':'DRY_RUN_READY','production_writes':0,'targets':plans}
    results={}
    for role,(config,sheet)in targets.items():
        try:results[role]={'state':'SUCCESS','result':sync(config,api,sheet)}
        except Exception:results[role]={'state':'PARTIAL','reason':'META_TARGET_WRITE_OR_READBACK_FAILED'}
    return {'state':'SUCCESS'if all(r['state']=='SUCCESS'for r in results.values())else'PARTIAL','targets':results}


def main():
    parser=argparse.ArgumentParser(description='Guarded dual-workbook Meta sync')
    parser.add_argument('--days',type=int,default=8)
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--skip-if-synced',action='store_true')
    parser.add_argument('--run-kind',choices=['manual','daily','retry','watchdog'],default='manual')
    args=parser.parse_args()
    try:
        result=run(Settings.from_env(args))
        print(json.dumps(result))
        return 0 if result['state']in ('SUCCESS','DRY_RUN_READY')else 2
    except Exception:
        print(json.dumps({'state':'BLOCKED','reason':'META_DUAL_PREFLIGHT_OR_SCOPE_FAILED'}))
        return 2


if __name__=='__main__':raise SystemExit(main())
