"""Direct Meta capture and validation; never invoke the existing Meta writer.

Capture runs in the credential-bearing parent environment. Business adapters
receive only a private, content-addressed snapshot, never the access token.
"""
from __future__ import annotations
import argparse
from datetime import date,datetime,timezone
import hashlib
import json
import math
import os
from pathlib import Path
from zoneinfo import ZoneInfo
from .sync_runtime import PrivateState,SyncBlocked,digest


def capture(accounts,begin,end,client,*,now=None):
    from .meta_history import collect
    now=now or datetime.now(timezone.utc)
    rows,scopes,names=collect(client,accounts,begin,end,now.isoformat())
    # Empty responses require separate account evidence. An HTTP 200 alone
    # must not replace the last-good facts with an asserted numeric zero.
    return {'source':'META_MARKETING_API_DIRECT','captured_at':now.isoformat(),
        'from':begin.isoformat(),'to':end.isoformat(),'accounts':sorted(accounts),
        'currency':'VND','rows':rows,'scopes':scopes,'names':names,
        'validation':'PASS'if all(s[4]>0 for s in scopes)else'EMPTY_REQUIRES_REVIEW'}


def validate(snapshot,options,as_of,*,now=None):
    now=now or datetime.now(timezone.utc)
    if snapshot.get('source')!='META_MARKETING_API_DIRECT' or snapshot.get('validation')!='PASS':
        raise SyncBlocked('META_DIRECT_SCOPE_NOT_VERIFIED')
    if snapshot.get('currency')!='VND':raise SyncBlocked('META_CURRENCY_UNVERIFIED')
    try:
        captured=datetime.fromisoformat(snapshot['captured_at'])
        age=(now-captured).total_seconds()
    except (ValueError,TypeError):raise SyncBlocked('META_CAPTURE_TIME_INVALID')from None
    if age<0 or age>options.get('max_age_seconds',86400):raise SyncBlocked('META_SNAPSHOT_STALE')
    if set(snapshot['accounts'])!=set(options['accounts']) or snapshot['from']!=options['from'] or snapshot['to']!=as_of:
        raise SyncBlocked('META_REQUESTED_SCOPE_MISMATCH')
    from .meta_sync import iso_date
    scope_accounts=set()
    for scope in snapshot['scopes']:
        if len(scope)!=11 or scope[0]in scope_accounts or scope[-1]!='COMPLETE':
            raise SyncBlocked('META_SCOPE_PROOF_INVALID')
        if iso_date(scope[2])!=snapshot['from'] or iso_date(scope[3])!=as_of or scope[6]!='VND':
            raise SyncBlocked('META_SCOPE_PROOF_INVALID')
        scope_accounts.add(scope[0])
        rr=[r for r in snapshot['rows']if len(r)==9 and r[8]==scope[0]]
        if len(rr)!=scope[4] or abs(sum(float(r[3])for r in rr)-scope[5])>0.001:
            raise SyncBlocked('META_SCOPE_TOTAL_MISMATCH')
    if scope_accounts!=set(options['accounts']):raise SyncBlocked('META_ACCOUNT_COVERAGE_INCOMPLETE')
    rows={}
    for r in snapshot['rows']:
        if len(r)!=9 or r[8]not in scope_accounts or not snapshot['from']<=iso_date(r[0])<=as_of:
            raise SyncBlocked('META_ROW_OUTSIDE_SCOPE')
        if any(isinstance(r[c],bool)or not math.isfinite(float(r[c]))or float(r[c])<0 for c in (3,4,5,6)):
            raise SyncBlocked('META_METRIC_INVALID')
        k=(str(r[8]),iso_date(r[0]),str(r[1]))
        if k in rows:raise SyncBlocked('META_DUPLICATE_ACCOUNT_DAY_CAMPAIGN')
        rows[k]=(float(r[3]),float(r[6]))
    return rows


def adapter(payload,options,work):
    from .sync_business import envelope,v,iso
    spec=options.get('meta_snapshot')
    if not spec:raise SyncBlocked('CURRENT_DIRECT_META_SNAPSHOT_MISSING')
    path=Path(spec['path'])
    if path.is_symlink()or not path.is_file():raise SyncBlocked('META_SNAPSHOT_MISSING')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=spec['sha256']:raise SyncBlocked('META_SNAPSHOT_SHA_MISMATCH')
    expected=validate(json.loads(raw),spec,payload['as_of'])
    proofs={}
    for role,s in payload['targets'].items():
        actual={}
        for row in range(3,next(p['gridProperties']['rowCount']for p in s['sheets']if p['sheetId']==7502)):
            account=str(v(s,7502,row,11)or'');day=iso(v(s,7502,row,0))
            if account not in spec['accounts']or not spec['from']<=day<=payload['as_of']:continue
            if v(s,7502,row,13)not in ('API','API_HISTORY'):continue
            if v(s,7502,row,14)!=1:continue
            k=(account,day,str(v(s,7502,row,5)))
            if k in actual:raise SyncBlocked('ACTIVE_META_SOURCE_DUPLICATE')
            actual[k]=(v(s,7502,row,4),v(s,7502,row,10))
        if actual!=expected:raise SyncBlocked('META_NATIVE_FACTS_DIFFER_FROM_DIRECT_API')
        proofs[role]={'rows':len(actual),'hash':digest(sorted(actual.items()))}
    out=envelope(payload,options,{'proofs':proofs},set())
    out['tables']={'A':[],'B':[]};out['read_only_validation']=proofs
    return out


def main():
    p=argparse.ArgumentParser(description='Direct Meta snapshot only; no Sheets writes')
    p.add_argument('--from-date',required=True);p.add_argument('--to-date',required=True)
    p.add_argument('--state-dir',required=True)
    args=p.parse_args()
    try:
        from .meta_sync import MetaClient,parse_accounts
        token=os.environ.get('META_ACCESS_TOKEN');accounts=parse_accounts(os.environ.get('META_AD_ACCOUNT_IDS'))
        if not token or not accounts:raise SyncBlocked('META_RUNTIME_CREDENTIAL_OR_SCOPE_MISSING')
        lo,hi=date.fromisoformat(args.from_date),date.fromisoformat(args.to_date)
        if hi>datetime.now(ZoneInfo('Asia/Ho_Chi_Minh')).date()or hi<lo:raise SyncBlocked('META_DATE_SCOPE_INVALID')
        state=PrivateState(args.state_dir)
        snapshot=capture(accounts,lo,hi,MetaClient(token,os.environ.get('META_API_VERSION','v27.0')))
        name='meta-'+digest(snapshot)+'.json';state.save(name,snapshot,immutable=True)
        print(json.dumps({'state':snapshot['validation'],'file':name,
            'sha256':hashlib.sha256((state.root/name).read_bytes()).hexdigest(),'rows':len(snapshot['rows'])}))
        return 0 if snapshot['validation']=='PASS'else 2
    except Exception as exc:
        print(json.dumps({'state':'BLOCKED','reason':str(exc)if isinstance(exc,SyncBlocked)else'META_CAPTURE_FAILED'}))
        return 2


if __name__=='__main__':raise SystemExit(main())
