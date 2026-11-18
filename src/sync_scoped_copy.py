"""Serialized, idempotent copies of validated independent fact subsets.

This is deliberately separate from the full checkpoint-promoting writer.
Only Lead, immutable PV/OB and immutable actual-fee plans are eligible.
No source watermark or last-good checkpoint is advanced by a partial copy.
The native destination is authoritative for crash recovery: stable keys and
exact preimages are recollected on every invocation; there is no blind replay.
"""
import os
from collections import defaultdict
from .sync_runtime import SyncBlocked, digest
from .sync_runner import protected_hash, formula_errors
from .sync_plan import requests_for, validate_owned
from .sync_business import v, iso
from .attendance_presence import norm

HELD = {
    'lead': {'LEAD_SOURCE_ROWS_QUARANTINED','HISTORICAL_LEAD_COUNT_DECREASE_REVIEW'},
    'pv_ob': {'LEGACY_EVENT_ALIAS_REVIEW_REQUIRED'},
    'attendance': {'HISTORICAL_FACT_CONFLICT'},
}


def require_coordinator():
    if (os.getenv('GITHUB_ACTIONS')!='true' or os.getenv('GITHUB_REPOSITORY_ID')!='1453850214'
        or os.getenv('GLA_V24_SERIALIZED_WRITER')!='gla-meta-ads-daily-sync'):
        raise SyncBlocked('SCOPED_COPY_REQUIRES_AUTHORIZED_SERIALIZED_JOB')


def copy_validated(stage, report, writer, state):
    require_coordinator()
    if report.get('mode')!='DRY_RUN' or not report.get('run_id'):
        raise SyncBlocked('SCOPED_COPY_NATIVE_DRY_RUN_PROOF_MISSING')
    result={'mode':'VALIDATED_SUBSET_COPY','full_source_state':'PARTIAL',
            'watermarks_advanced':False,'write_requests':0,'targets':{}}
    for name,target in stage['config']['targets'].items():
        proof=report['targets'].get(name,{})
        out={'state':'HELD','branches':{},'rows_verified':0}
        result['targets'][name]=out
        if (proof.get('protected_hash_match')is not True or proof.get('authored_hash_match')is not True
            or proof.get('formula_errors')!=0):
            out['reason']='NATIVE_TARGET_CHANGED_DURING_DRY_RUN';continue
        try:
            current=writer.snapshot(target['id'])
            if protected_hash(current,target['role'])!=stage['protected'][name]or formula_errors(current):
                raise SyncBlocked('SCOPED_COPY_PROTECTED_PREIMAGE_CHANGED')
            for branch,allowed_reasons in HELD.items():
                branch_stage=stage['branches'][branch]
                status=branch_stage.get('targets',{}).get(name,{})
                plan=branch_stage.get('plans',{}).get(name)
                if (branch_stage.get('normalization_state')!='VALIDATED' or plan is None
                    or not set(status.get('held_reasons',[]))<=allowed_reasons
                    or status.get('state')not in ('READY','PARTIAL')
                    or status.get('state')=='PARTIAL'and status.get('reason')not in allowed_reasons):
                    out['branches'][branch]={'state':'HELD'};continue
                changes=plan['changes'];held_rows=0
                if branch=='attendance':
                    changes,held_rows=attendance_with_native_parent(changes,current,
                        stage.get('normalized',{}).get('pv_ob',{}).get('roster',[]))
                keys=list({c['key']for c in plan['changes']}|set(plan['guards']))
                actual=writer.read_cells(target['id'],current,keys)if keys else{}
                if any(actual[k].get('userEnteredValue',{})not in(g['before'],g['after'])
                       for k,g in plan['guards'].items()):
                    raise SyncBlocked('SCOPED_COPY_STABLE_KEY_CHANGED')
                pending=[]
                for change in changes:
                    value=actual[change['key']].get('userEnteredValue',{})
                    if value==change['after']:continue
                    if value!=change['before']:raise SyncBlocked('SCOPED_COPY_FACT_PREIMAGE_CHANGED')
                    pending.append(change)
                requests=requests_for(pending)
                validate_owned(requests,current,target['role'],branch,target['ownership'][branch])
                for offset in range(0,len(requests),200):
                    writer.write(target['id'],requests[offset:offset+200]);result['write_requests']+=1
                reread=writer.read_cells(target['id'],current,[c['key']for c in changes])if changes else{}
                if any(reread[c['key']].get('userEnteredValue',{})!=c['after']for c in changes):
                    raise SyncBlocked('SCOPED_COPY_NATIVE_READBACK_MISMATCH')
                current['cells'].update(reread)
                rows=len({c['key'].rsplit(':',1)[0]for c in pending})
                out['rows_verified']+=rows
                out['branches'][branch]={'state':'VERIFIED_VALID_SUBSET','rows':rows,
                    'cells':len(pending),'rows_held_for_parent':held_rows,
                    'plan_hash':digest({'changes':changes,'guards':plan['guards']}),'checkpoint_advanced':False}
            final=writer.snapshot(target['id'])
            if protected_hash(final,target['role'])!=stage['protected'][name]or formula_errors(final):
                raise SyncBlocked('SCOPED_COPY_FINAL_NATIVE_AUDIT_FAILED')
            out['state']=('VERIFIED_VALID_SUBSETS_SOURCE_REVIEW_HELD'if any(
                b['state']=='VERIFIED_VALID_SUBSET'for b in out['branches'].values())else'HELD_NO_VALIDATED_PLAN')
        except Exception as exc:
            out['state']='PARTIAL'
            out['reason']=str(exc)if isinstance(exc,SyncBlocked)else'SCOPED_COPY_TRANSPORT_OR_READBACK_FAILED'
    state.save('scoped-copy-'+report['run_id']+'.json',result)
    return result


def attendance_with_native_parent(changes,snapshot,fresh_roster):
    """No fee fact can arrive ahead of its independently verified OB episode."""
    fresh=defaultdict(list)
    for person in fresh_roster:fresh[person['key']].append(person)
    native=defaultdict(list)
    for row in range(3,2000):
        key=v(snapshot,7305,row,7)
        if key:native[key].append((v(snapshot,7305,row,0),v(snapshot,7305,row,1),
            norm(v(snapshot,7305,row,2)),iso(v(snapshot,7305,row,3)),v(snapshot,7305,row,5)))
    allowed=set()
    for key,people in fresh.items():
        if len(people)!=1:continue
        p=people[0]
        identity=(p['factory'],p.get('id'),norm(p['name']),p['join'],p.get('problem')or'')
        if p.get('id')and not p.get('problem')and native.get(key)and all(
            (*r[:4],r[4]or'')==identity for r in native[key]):allowed.add(key)
    rows=defaultdict(list)
    for change in changes:rows[change['key'].rsplit(':',1)[0]].append(change)
    retained=[];held=0
    for row_key,parts in rows.items():
        episode=next((c['after'].get('stringValue')for c in parts if c['key']==row_key+':12'),None)
        if episode is None:
            episode=snapshot['cells'].get(row_key+':12',{}).get('userEnteredValue',{}).get('stringValue')
        if episode in allowed:retained.extend(parts)
        else:held+=1
    return retained,held
