"""Scheduled dual-Meta sync plus conservatively scoped GLA fact copies."""
import argparse
import json
import os
import tempfile
from .meta_sync import Settings
from .meta_dual_sync import run as meta_run
from .sync_deployment import run as source_run
from .sync_runtime import PrivateState,SyncBlocked


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--days',type=int,default=8)
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--skip-if-synced',action='store_true')
    parser.add_argument('--run-kind',choices=['daily','manual','retry','watchdog'],default='daily')
    args=parser.parse_args();os.umask(0o077)
    report={'mode':'DRY_RUN'if args.dry_run else'SCOPED_DAILY_SYNC'}
    try:report['meta']=meta_run(Settings.from_env(args))
    except Exception:report['meta']={'state':'PARTIAL','reason':'META_PREFLIGHT_OR_TRANSPORT_FAILED'}
    try:
        with tempfile.TemporaryDirectory(prefix='gla-daily-private-')as folder:
            report['sources']=source_run(PrivateState(folder),scoped_apply=not args.dry_run)
    except Exception as exc:
        report['sources']={'state':'PARTIAL','reason':str(exc)if isinstance(exc,SyncBlocked)else'GLA_SOURCE_SYNC_FAILED'}
    print(json.dumps(report,ensure_ascii=False))
    print('GLA_META_STATE='+report['meta']['state'],flush=True)
    print('GLA_FULL_RELEASE=BLOCKED_SOURCE_REVIEW_REQUIRED',flush=True)
    print('GLA_SOURCE_WRITE_REQUESTS='+str(report['sources'].get('production_writes',0)),flush=True)
    for name,target in report['sources'].get('scoped_copy',{}).get('targets',{}).items():
        print('GLA_SOURCE_TARGET '+name+' '+target['state'],flush=True)
        for branch,status in target.get('branches',{}).items():
            print('GLA_SOURCE_BRANCH '+name+' '+branch+' '+status['state']+
                  ' ROWS='+str(status.get('rows',0))+' CELLS='+str(status.get('cells',0))+
                  ' PARENT_HELD='+str(status.get('rows_held_for_parent',0)),flush=True)
    meta_ok=report['meta']['state']in('SUCCESS','DRY_RUN_READY')
    source=report['sources']
    if args.dry_run:
        source_ok=all(t['state']=='DRY_RUN_READY'for t in source.get('targets',{}).values())and bool(source.get('targets'))
    else:
        targets=source.get('scoped_copy',{}).get('targets',{})
        source_ok=bool(targets)and all(t['state']=='VERIFIED_VALID_SUBSETS_SOURCE_REVIEW_HELD'for t in targets.values())
    return 0 if meta_ok and source_ok else 2


if __name__=='__main__':raise SystemExit(main())
