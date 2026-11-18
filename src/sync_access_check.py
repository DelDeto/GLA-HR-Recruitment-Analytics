"""Credentialed read-only diagnostics in the existing, explicitly scoped CI job.

No personal data, source IDs/URLs, credentials or raw snapshots leave the
ephemeral private directory. This is not the full V2.4 acceptance runner.
"""
from __future__ import annotations
import argparse
from datetime import date,datetime
import hashlib
import json
import os
import re
import tempfile
import uuid
from zoneinfo import ZoneInfo
from .sync_runtime import PrivateState,SyncBlocked
from .sync_sources import GoogleTransport,collect_once,SHEETS
from .sync_source_scope import UNUSED_SOURCE_HASHES


# Hashes authorize only the resources named in the task. No private source
# location or personnel identifier is embedded in the public repository.
RESOURCE_HASHES={
 'A':'d3ee04aafdbd507a56987c9e577d278bcb478725bf65d876e2ac2104c1203e3b',
 'B':'642e830a76a9f831a736f16c5819214d3aa34eeb7bb2e0c4b7c9b43e056461a2',
 'sale_le':'9e93568aaf0916334e14a99c1e0f05b931186e857b9dab9442c1a48bcba3903b',
 'sale_thao':'0a20efe7db9f94e4e632db61cba8a3de6f9379c5fb345eddb5fdb311c3967725',
 'sale_yen':'31bce3f4654d16d99737b0ab7237c5f32767accaa6c4a8cd18c12174e4ec21a0',
 'crm':'c84ee8c546af817c52216709627df42875f4ef917cb40d4339f54fe9ddc55365',
 'pv':'e8a81eb87b96482f8c0a720bdc62592b485fab76e96df3f773253a5a968ae60d',
 'ob':'d97348cf7204085522827ee3d30a4921f66cb60841a54456e80cdbfba5b3a756',
 'form_epu':'1d45147decf2230d76e625ae725ab730dfab99826ba2b255de741836fec1e321',
 'form_gtvt':'21c08448685d41b847f6aaf3844a609a83e05ad907606eda3c8ec2cdb9fbe3be',
 'form_fevc_gtvt':'46c653bf116cb742c7c2e4539414e93367d9b3444adc4a343a73ef1a5399ff75',
 'form_uet':'6851f5a8a74b739158d7c3984adf7bf1f641a7c88e2d38b29d64a83f871320de',
 'folder':'73eee506b7887a19ab88caf19ea4ad965729ed7f881d3edba21dc70ff1324ffc'}
HINT_CELLS=[(6204,10,4),(6240,117,1),(6240,1799,7),(6240,2337,7),
            (7100,10,7),(7306,10,1),(7506,202,0)]
ACCOUNT_HASHES={'686c736bd4c577e53a76c003f79b0232e7d3768ff3e8ad989f9599ce502a4d7e',
 'e5506cb22174c34ce192e3674d768633c2747cd099bf9a2eda7a4bf5bda00dd6',
 '243f85dcc44d5e493d94b26157a5f247061726300245c09e792aae654a6caa7b'}


def authorize_root(root):
    if not root or hashlib.sha256(root.encode()).hexdigest()!=RESOURCE_HASHES['A']:
        raise SyncBlocked('AUTHORIZED_MASTER_SECRET_MISSING_OR_MISMATCH')


def discover(values,root):
    authorize_root(root)
    wanted={v:k for k,v in RESOURCE_HASHES.items()};out={'A':root}
    for text in values:
        if not isinstance(text,str):continue
        for candidate in re.findall(r'[A-Za-z0-9_-]{20,}',text):
            role=wanted.get(hashlib.sha256(candidate.encode()).hexdigest())
            if role:out[role]=candidate
    return out


def read_hints(transport,root):
    from openpyxl.utils import get_column_letter
    authorize_root(root)
    meta=transport.json('GET',SHEETS+root,params={'fields':'spreadsheetId,sheets.properties'})
    titles={s['properties']['sheetId']:s['properties']['title']for s in meta['sheets']}
    ranges=["'"+titles[sid].replace("'","''")+"'!"+get_column_letter(c+1)+str(r+1)
            for sid,r,c in HINT_CELLS if sid in titles]
    if not ranges:raise SyncBlocked('REVIEWED_DISCOVERY_CELLS_MISSING')
    body=transport.json('GET',SHEETS+root,params={'ranges':ranges,'includeGridData':'true',
        'fields':'sheets(data(rowData(values(effectiveValue,userEnteredValue))))'})
    values=[]
    for sheet in body.get('sheets',[]):
        for block in sheet.get('data',[]):
            for row in block.get('rowData',[]):
                for cell in row.get('values',[]):
                    for field in ('effectiveValue','userEnteredValue'):
                        for kind in ('stringValue','formulaValue'):
                            text=cell.get(field,{}).get(kind)
                            if isinstance(text,str):values.append(text)
    return discover(values,root)


def forbid_writes(transport):
    original=transport.json
    def read_only(method,*args,**kwargs):
        if method.upper()!='GET':raise SyncBlocked('PRODUCTION_WRITE_FORBIDDEN')
        return original(method,*args,**kwargs)
    transport.json=read_only
    def denied(*args,**kwargs):raise SyncBlocked('PRODUCTION_WRITE_FORBIDDEN')
    transport.write=denied
    return transport


def access_checks(transport,resources):
    checks={}
    for role in RESOURCE_HASHES:
        if role not in resources:
            checks[role]={'state':'BLOCKED','reason':'REVIEWED_RESOURCE_REFERENCE_NOT_FOUND'};continue
        try:
            info=transport.file_info(resources[role]);editable=info.get('capabilities',{}).get('canEdit')is True
            ok=not info.get('trashed')and(role not in ('A','B')or editable)
            checks[role]={'state':'PASS'if ok else'BLOCKED','readable':not info.get('trashed',False)}
            if role in ('A','B'):checks[role]['can_edit']=editable
        except Exception as exc:
            checks[role]={'state':'BLOCKED','reason':str(exc)if isinstance(exc,SyncBlocked)else'SERVICE_ACCOUNT_ACCESS_CHECK_FAILED'}
    return checks


def meta_check(state):
    from .meta_sync import MetaClient,parse_accounts
    from .sync_meta_snapshot import capture,validate
    token=os.getenv('META_ACCESS_TOKEN');raw_accounts=os.getenv('META_AD_ACCOUNT_IDS')
    if not token or not raw_accounts or not raw_accounts.strip():
        raise SyncBlocked('META_RUNTIME_TOKEN_OR_AUTHORIZED_ACCOUNT_SCOPE_MISSING')
    # Parse failures must retain the same safe diagnostic as missing runtime
    # secrets, rather than being reported as an unexplained API failure.
    from .meta_sync import SyncError
    try:
        accounts=parse_accounts(raw_accounts)
    except SyncError:
        raise SyncBlocked('META_RUNTIME_TOKEN_OR_AUTHORIZED_ACCOUNT_SCOPE_MISSING') from None
    if {hashlib.sha256(a.encode()).hexdigest()for a in accounts}!=ACCOUNT_HASHES:
        raise SyncBlocked('META_RUNTIME_TOKEN_OR_AUTHORIZED_ACCOUNT_SCOPE_MISSING')
    today=datetime.now(ZoneInfo('Asia/Ho_Chi_Minh')).date()
    snapshot=capture(accounts,date(2026,1,1),today,MetaClient(token,os.getenv('META_API_VERSION','v27.0')))
    validate(snapshot,{'accounts':accounts,'from':'2026-01-01'},today.isoformat())
    state.save('direct-meta-snapshot.json',snapshot,immutable=True)
    return {'state':'PASS','accounts':len(accounts),'rows':len(snapshot['rows']),
        'from':'2026-01-01','to':today.isoformat(),'source':'META_MARKETING_API_DIRECT',
        'snapshot_sha256':hashlib.sha256((state.root/'direct-meta-snapshot.json').read_bytes()).hexdigest()}


def run_check(state,*,scan_sources=False,read_meta=False):
    report={'attempt_id':uuid.uuid4().hex,'mode':'CREDENTIALED_READ_ONLY_CANARY',
            'production_writes':0,'release_state':'BLOCKED','full_v24_e2e':'NOT_RUN_DATA_RELEASE_GATES_REMAIN'}
    report['source_exclusions']={role:'USER_CONFIRMED_UNUSED'for role in UNUSED_SOURCE_HASHES}
    run_id=os.getenv('GITHUB_RUN_ID','')
    if re.fullmatch(r'\d+',run_id):report['github_run_id']=run_id
    try:
        transport=forbid_writes(GoogleTransport.from_env(state));resources=read_hints(transport,os.getenv('GOOGLE_SHEET_ID',''))
        report['master_reference_read']={'state':'PASS','resources_discovered':len(resources)}
        report['access']=access_checks(transport,resources)
        if scan_sources and len(resources)==len(RESOURCE_HASHES):
            files=[fid for role,fid in resources.items()if role not in ('A','B','folder')]
            bundle=collect_once(transport,[resources['folder']],files)
            state.save('source-bundle.json',bundle,immutable=True)
            report['source_scan']={'state':'PASS'if bundle['transport_scan_complete']else'BLOCKED',
                'listed_files':bundle['listed_files'],'parsed_files':bundle['parsed_files'],'tabs':bundle['listed_tabs'],
                'formula_error_cells':sum(len(t.get('formula_errors',[]))for s in bundle['sources']for t in s['tabs'])if bundle['transport_scan_complete']else None,
                'errors':bundle['errors']}
        else:report['source_scan']={'state':'BLOCKED','reason':'RESOURCE_DISCOVERY_INCOMPLETE_OR_SCAN_NOT_REQUESTED'}
    except Exception as exc:
        report['google']={'state':'BLOCKED','reason':str(exc)if isinstance(exc,SyncBlocked)else'GOOGLE_READ_ONLY_CHECK_FAILED'}
    if read_meta:
        try:report['meta_snapshot']=meta_check(state)
        except Exception as exc:
            report['meta_snapshot']={'state':'BLOCKED','reason':str(exc)if isinstance(exc,SyncBlocked)else'META_DIRECT_CAPTURE_FAILED'}
    passed=(len(report.get('access',{}))==len(RESOURCE_HASHES)and
        all(c['state']=='PASS'for c in report.get('access',{}).values())and
        report.get('source_scan',{}).get('state')=='PASS'and
        (not read_meta or report.get('meta_snapshot',{}).get('state')=='PASS'))
    report['canary_state']='PASS'if passed else'BLOCKED'
    state.save('access-report.json',report,immutable=True)
    return report


def main():
    parser=argparse.ArgumentParser(description='Read-only access/source/Meta diagnostics; no apply option')
    parser.add_argument('--scan-sources',action='store_true');parser.add_argument('--read-meta',action='store_true')
    args=parser.parse_args();os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix='gla-access-')as folder:
        state=PrivateState(folder)
        report=run_check(state,scan_sources=args.scan_sources,read_meta=args.read_meta)
        # Raw inputs remain private and are removed with the ephemeral directory.
        print(json.dumps(report,ensure_ascii=False))
    return 0 if report['canary_state']=='PASS'else 2


if __name__=='__main__':raise SystemExit(main())
