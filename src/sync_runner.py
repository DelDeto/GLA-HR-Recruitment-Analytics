"""Unscheduled private dual-workbook runner. Dry-run is the default.

Business adapters are private, explicitly version/SHA pinned programs, not
downloaded code and not old scripts silently selected from the workspace.
They read a JSON envelope and return normalized tables / forecast config.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import time
import uuid
from .sync_runtime import PrivateState, SyncBlocked, digest
from .sync_sources import GoogleTransport, collect_once
from .sync_plan import table_upserts, requests_for, expand_forecast, validate_owned
from .sync_safety import protected_rects

BRANCHES = ('lead','pv_ob','attendance','forecast','bonus','meta')
DEPENDENCIES = {'attendance': ('pv_ob',), 'forecast': ('attendance',), 'bonus': ('attendance',)}


def formula_errors(snapshot):
    return [digest(k) for k,v in snapshot['cells'].items()
            if 'errorValue' in v.get('effectiveValue', {})]


def protected_hash(snapshot, role):
    out = {}
    for k, cell in snapshot['cells'].items():
        sid,r,c = map(int,k.split(':'))
        if any(sid==s and a<=r<b and x<=c<y for s,a,b,x,y in protected_rects(role)):
            authored = {f: cell[f] for f in ('userEnteredValue','note') if f in cell}
            if authored:
                out[k] = authored
    return digest({'cells':out, 'sheets':snapshot['sheets']})


def validate_envelope(output, bundle):
    if output.get('complete') is not True:
        raise SyncBlocked('ADAPTER_SOURCE_PARTIAL')
    actual = {s['file_id']: s for s in bundle['sources']}
    claims = output.get('coverage', {})
    if set(claims) != set(actual):
        raise SyncBlocked('ADAPTER_FILE_COVERAGE_INCOMPLETE')
    for file_id, source in actual.items():
        claim = claims[file_id]
        if claim.get('fingerprint') != source['fingerprint']:
            raise SyncBlocked('ADAPTER_SOURCE_FINGERPRINT_CHANGED')
        expected = {str(t['id']) for t in source['tabs']}
        if set(claim.get('tabs', {})) != expected:
            raise SyncBlocked('ADAPTER_TAB_COVERAGE_INCOMPLETE')
        for status in claim['tabs'].values():
            if status.get('state') not in ('PARSED','VERIFIED_OUT_OF_SCOPE'):
                raise SyncBlocked('ADAPTER_TAB_UNVERIFIED')
            if status['state']=='VERIFIED_OUT_OF_SCOPE' and not status.get('reason_code'):
                raise SyncBlocked('OUT_OF_SCOPE_REASON_MISSING')


def adapter_diagnostics(output):
    """Only allowlisted counts leave private normalization artifacts."""
    files=output.get('coverage',{});tabs=[t for f in files.values()for t in f.get('tabs',{}).values()]
    result={'files':len(files),'tabs':len(tabs),
        'unverified_tabs':sum(t.get('state')not in ('PARSED','VERIFIED_OUT_OF_SCOPE')for t in tabs),
        'critical_formula_errors':sum(t.get('critical_errors',0)for t in tabs),
        'excluded_formula_errors':sum(t.get('excluded_errors',0)for t in tabs)}
    legacy=output.get('normalized',{}).get('legacy_sales_audit',{})
    result['legacy_sales']={k:v for k,v in legacy.get('counts',{}).items()
        if k in ('already_counted','outside_period','unknown_date','needs_review')and type(v)is int}
    if type(legacy.get('merged_duplicates'))is int:result['legacy_sales']['merged_duplicates']=legacy['merged_duplicates']
    result['event_alias_groups']={role:len(rows)for role,rows in output.get('normalized',{}).get('event_alias_review',{}).items()if role in ('A','B')}
    result['lead_source_rows_quarantined']=len(output.get('normalized',{}).get('lead_source_quarantine',[]))
    return result


def branch_bundle(config, branch, bundle):
    """Missing unrelated sources must not invalidate an independent branch."""
    if bundle['transport_scan_complete']:
        return bundle
    from .sync_source_scope import active_roles
    roles = active_roles(config.get('adapters', {}).get(branch, {}).get('options', {}).get('source_roles', {}))
    seen = {source['file_id'] for source in bundle['sources']}
    if branch == 'meta':
        complete = True  # Its own API snapshot and native scope proof are required.
    elif branch == 'lead':
        inputs = {fid for role,fid in roles.items() if role not in ('pv','ob')}
        complete = bool(inputs) and inputs <= seen
    elif branch == 'pv_ob':
        complete = all(roles.get(role) in seen for role in ('pv','ob'))
    else:
        complete = False  # Attendance needs the complete folder and roster.
    return dict(bundle, transport_scan_complete=complete)


def pinned_adapter(spec, payload, state):
    if not spec or not spec.get('version') or not spec.get('sha256'):
        raise SyncBlocked('ADAPTER_VERSION_OR_SHA_MISSING')
    entry = Path(spec['entrypoint'])
    if entry.is_symlink() or not entry.is_file():
        raise SyncBlocked('ADAPTER_FILE_MISSING')
    if hashlib.sha256(entry.read_bytes()).hexdigest() != spec['sha256']:
        raise SyncBlocked('ADAPTER_SHA_MISMATCH')
    # Pin every local dependency as well; Python/system environment is managed
    # separately with requirements lock/review, never a floating workspace glob.
    files = spec.get('files')
    if not isinstance(files, dict) or entry.name not in files or files[entry.name] != spec['sha256']:
        raise SyncBlocked('ADAPTER_BUNDLE_MANIFEST_MISSING')
    root = entry.resolve().parent
    for relative, expected in files.items():
        path = root / relative
        if path.is_symlink() or not path.resolve().is_relative_to(root) or not path.is_file():
            raise SyncBlocked('ADAPTER_DEPENDENCY_MISSING')
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise SyncBlocked('ADAPTER_DEPENDENCY_SHA_MISMATCH')
    envelope = json.dumps(payload, allow_nan=False)
    # Do not pass Meta/Google credentials to private normalization subprocesses.
    env = {k:v for k,v in os.environ.items() if k in ('PATH','LANG','LC_ALL','TZ')}
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    try:
        result = subprocess.run([sys.executable, str(entry.resolve())], input=envelope,
                                capture_output=True, text=True, cwd=state.root, env=env,
                                timeout=spec.get('timeout_seconds', 300), check=False)
        if result.returncode:
            reason=result.stderr.strip()
            if re.fullmatch(r'[A-Z][A-Z0-9_]{2,100}',reason):
                raise SyncBlocked(reason)
            raise SyncBlocked('ADAPTER_PROCESS_FAILED')
        output = json.loads(result.stdout)
    except (subprocess.TimeoutExpired, ValueError):
        raise SyncBlocked('ADAPTER_OUTPUT_INVALID') from None
    if output.get('version') != spec['version']:
        raise SyncBlocked('ADAPTER_REPORTED_VERSION_MISMATCH')
    return output


def validate_config(config):
    targets = config.get('targets', {})
    if set(targets) != {'A','B'} or targets['A'].get('role')!='MASTER_V23' or targets['B'].get('role')!='SEPTEMBER_V22':
        raise SyncBlocked('TWO_EXPLICIT_TARGET_ROLES_REQUIRED')
    if not all(t.get('id') for t in targets.values()) or targets['A']['id']==targets['B']['id']:
        raise SyncBlocked('DISTINCT_TARGET_IDS_REQUIRED')
    ids = {t['id'] for t in targets.values()}
    if any(not re.fullmatch(r'[A-Za-z0-9_-]+',i) for i in ids):
        raise SyncBlocked('INVALID_NATIVE_TARGET_ID')
    if ids & set(config.get('source_files', [])):
        raise SyncBlocked('PRODUCTION_IS_NOT_AN_EXTERNAL_SOURCE')
    if not config.get('source_files') and not config.get('source_folders'):
        raise SyncBlocked('SOURCE_LOCATIONS_MISSING')


def stage_meta_snapshot(config, state):
    """Refresh the pinned Meta input inside the credential-bearing runtime."""
    if config.get('capture_meta_in_runtime') is not True:
        return config
    from datetime import date
    from .meta_sync import MetaClient, parse_accounts
    from .sync_meta_snapshot import capture, validate
    from .sync_access_check import ACCOUNT_HASHES
    token = os.getenv('META_ACCESS_TOKEN')
    accounts = parse_accounts(os.getenv('META_AD_ACCOUNT_IDS'))
    if not token or {hashlib.sha256(a.encode()).hexdigest() for a in accounts} != ACCOUNT_HASHES:
        return config
    start = '2026-01-01'
    try:
        snapshot = capture(accounts,date.fromisoformat(start),date.fromisoformat(config['as_of']),
                           MetaClient(token,os.getenv('META_API_VERSION','v27.0')))
        validate(snapshot,{'accounts':accounts,'from':start},config['as_of'])
    except Exception:
        return config  # Independent branches can still complete. No stale replacement.
    name = 'meta-' + digest(snapshot) + '.json'
    state.save(name,snapshot,immutable=True)
    path = state.root / name
    adapter = config['adapters']['meta']
    spec = {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'accounts':accounts,'from':start}
    return dict(config,adapters=dict(config['adapters'],
        meta=dict(adapter,options=dict(adapter.get('options',{}),meta_snapshot=spec))))


def stage_run(config, transport, state, adapters=None, *, input_config_hash=None):
    validate_config(config)
    if config.get('require_service_account_preflight'):
        preflight_access(config,transport,state, allow_source_partial=True)
    before = {name: transport.snapshot(t['id']) for name,t in config['targets'].items()}
    for name,snapshot in before.items():
        if snapshot['id'] != config['targets'][name]['id']:
            raise SyncBlocked('NATIVE_TARGET_ID_MISMATCH')
    bundle = collect_once(transport, config.get('source_folders', []), config.get('source_files', []))
    if {s['file_id'] for s in bundle['sources']} & {t['id'] for t in config['targets'].values()}:
        raise SyncBlocked('PRODUCTION_FOUND_IN_SOURCE_FOLDER')
    # Copy cell indexes, not millions of immutable CellData dictionaries.
    working = {n:dict(s,cells=dict(s['cells'])) for n,s in before.items()}
    branches, normalized = {}, {}
    for branch in BRANCHES:
        diagnostics={}
        try:
            scoped_bundle=branch_bundle(config,branch,bundle)
            if not scoped_bundle['transport_scan_complete']:
                raise SyncBlocked('SOURCE_SCAN_PARTIAL')
            if any(d not in normalized for d in DEPENDENCIES.get(branch, ())):
                raise SyncBlocked('DEPENDENCY_NOT_READY')
            spec = config.get('adapters', {}).get(branch)
            payload = {'branch':branch, 'as_of':config['as_of'], 'sources':scoped_bundle,
                       'targets':working, 'normalized':normalized,
                       'options':(spec or {}).get('options', {})}
            output = adapters[branch](payload) if adapters is not None and branch in adapters else pinned_adapter(spec, payload, state)
            diagnostics=adapter_diagnostics(output)
            validate_envelope(output, scoped_bundle)
            if output.get('validation') != 'PASS':
                raise SyncBlocked('BUSINESS_VALIDATION_NOT_PASS')
            # Retain a fully source-validated normalization for downstream
            # read-only diagnostics even if a target plan is blocked. Execution
            # still requires every dependency's actual plan/readback to pass.
            normalized[branch]=output.get('normalized',{})
            if branch != 'forecast' and set(output.get('tables',{})) != {'A','B'}:
                raise SyncBlocked('EXPLICIT_BOTH_TARGET_TABLES_REQUIRED')
            if branch != 'forecast' and any(not output['tables'][n] for n in ('A','B')):
                proof=output.get('read_only_validation',{})
                if (branch!='meta' or set(proof)|set(output.get('plan_blockers',{}))!={'A','B'} or
                    any(output['tables'][n] for n in ('A','B')) or
                    any(type(proof[n].get('rows'))is not int or proof[n]['rows']<0 or
                        not re.fullmatch('[0-9a-f]{64}',str(proof[n].get('hash','')))for n in proof)):
                    raise SyncBlocked('NO_VERIFIABLE_BRANCH_FACT_TABLE')
            plans = {};target_status={}
            for name,target in config['targets'].items():
                try:
                    if output.get('plan_blockers',{}).get(name):
                        raise SyncBlocked(output['plan_blockers'][name])
                    changes, guards, quarantined = [], {}, []
                    if branch == 'forecast':
                        from .forecast_sync import build_plan
                        fc = output['forecast'][name]
                        if not fc.get('installed') or fc.get('workbook_role')!=target['role']:
                            raise SyncBlocked('FORECAST_ROLE_CHANGED')
                        native = build_plan(fc)
                        validate_owned(native,working[name],target['role'],branch,target.get('ownership',{}).get(branch,[]))
                        changes = expand_forecast(native,working[name])
                    else:
                        for table in output.get('tables', {}).get(name, []):
                            if branch=='attendance' and table.get('sheet_id') in (7851,7852,7504) and table.get('immutable_existing') is not True:
                                raise SyncBlocked('ACTUAL_HISTORY_MUST_BE_IMMUTABLE')
                            if branch=='bonus' and table.get('sheet_id')==7401 and table.get('immutable_existing') is not True:
                                raise SyncBlocked('LEGACY_AWARD_HISTORY_MUST_BE_IMMUTABLE')
                            part, keys = table_upserts(working[name],table,
                                quarantined=quarantined if branch in ('lead','pv_ob','attendance') else None)
                            changes.extend(part); guards.update(keys)
                    if len({c['key'] for c in changes}) != len(changes):
                        raise SyncBlocked('OVERLAPPING_BRANCH_TABLES')
                    if branch == 'bonus':
                        for c in changes:
                            if c['after'].get('stringValue') in ('Đã thực hiện thưởng','ĐÃ CHI','ĐÃ DUYỆT','ĐÃ CHỐT'):
                                raise SyncBlocked('BONUS_CANNOT_APPROVE_OR_CLAIM_PAYMENT')
                    validate_owned(requests_for(changes), working[name],target['role'],branch,target.get('ownership',{}).get(branch,[]))
                    held=list(output.get('held',{}).get(name,[]))
                    held.extend(sorted({row['reason'] for row in quarantined}))
                    plans[name] = {'changes':changes, 'guards':guards, 'quarantined':quarantined}
                    target_status[name]={'state':'PARTIAL' if held else 'READY',
                        'held_reasons':held, 'quarantined_target_rows':len(quarantined),
                        'changed_rows':len({c['key'].rsplit(':',1)[0] for c in changes}),
                        'changed_cells':len(changes), 'plan_hash':digest(plans[name])}
                    if held:target_status[name]['reason']=held[0]
                except Exception as exc:
                    target_status[name]={'state':'PARTIAL','reason':str(exc)if isinstance(exc,SyncBlocked)else'TARGET_PLAN_REJECTED'}
            # Simulate only complete target plans. A held subset cannot become
            # a materialized dependency for forecast, fees, or bonus.
            for name,plan in plans.items():
                if target_status[name]['state']!='READY':continue
                for c in plan['changes']:
                    working[name]['cells'][c['key']] = {'userEnteredValue':c['after']}
            reasons=[x['reason'] for x in target_status.values() if x['state']!='READY']
            branches[branch] = {'state':'PARTIAL' if reasons else 'READY', 'plans':plans,
                                'adapter_sha':(spec or {}).get('sha256'),'normalization_state':'VALIDATED','targets':target_status,'diagnostics':diagnostics}
            if reasons:branches[branch]['reason']=reasons[0]
            normalized[branch] = output.get('normalized', {})
        except Exception as exc:
            branches[branch] = {'state':'PARTIAL', 'reason':str(exc) if isinstance(exc,SyncBlocked) else 'ADAPTER_OR_PLAN_REJECTED','diagnostics':diagnostics}
            branches[branch]['targets']={n:dict(state='PARTIAL',reason=branches[branch]['reason'])for n in config['targets']}
    stage = {'config_hash':input_config_hash or digest(config), 'created_at':time.time(), 'config':config,
             'sources':bundle, 'normalized':normalized, 'before':before, 'branches':branches,
             'protected':{n:protected_hash(s,config['targets'][n]['role']) for n,s in before.items()},
             'errors_before':{n:formula_errors(s) for n,s in before.items()}}
    run_id = digest(stage)
    state.save('stage-'+run_id+'.json',stage,immutable=True)
    return run_id, stage


def preflight_access(config,transport,state, *, allow_source_partial=False):
    """Check the actual runtime identity's capabilities, without a write probe."""
    checks={}
    requested={t['id']:('target',n)for n,t in config['targets'].items()}
    requested.update({fid:('source',digest(fid))for fid in config.get('source_files',[])})
    requested.update({fid:('folder',digest(fid))for fid in config.get('source_folders',[])})
    for fid,(kind,label)in requested.items():
        try:
            info=transport.file_info(fid)
            readable=not info.get('trashed',False)
            editable=info.get('capabilities',{}).get('canEdit')is True
            ok=readable and(kind!='target'or editable)
            checks[label]={'kind':kind,'state':'PASS'if ok else'BLOCKED',
                           'readable':readable,'can_edit':editable}
        except Exception:
            checks[label]={'kind':kind,'state':'BLOCKED','reason':'SERVICE_ACCOUNT_ACCESS_UNVERIFIED'}
    state.save('access-preflight.json',checks)
    if any(c['state']!='PASS' and (c['kind']=='target' or not allow_source_partial) for c in checks.values()):
        raise SyncBlocked('SERVICE_ACCOUNT_SOURCE_OR_TARGET_ACCESS_BLOCKED')
    return checks


def execute_stage(run_id, stage, transport, state, *, apply=False):
    targets = stage['config']['targets']
    if apply and (stage['config'].get('deployment_approved') is not True or
                  stage['config'].get('single_writer_private_volume') is not True):
        raise SyncBlocked('PRIVATE_DEPLOYMENT_APPROVAL_AND_SINGLE_WRITER_REQUIRED')
    if apply and time.time()-stage['created_at'] > 3600:
        raise SyncBlocked('STAGE_EXPIRED_RECOLLECT_AND_VALIDATE')
    checkpoints = state.read('checkpoint-'+run_id+'.json', {}) if apply else {}
    results = {}
    decisions = {}
    for name,target in targets.items():
        statuses = {}
        decisions[name]={}
        try:
            current = transport.snapshot(target['id'])
            if protected_hash(current,target['role']) != stage['protected'][name]:
                raise SyncBlocked('PROTECTED_PREIMAGE_CHANGED')
            if formula_errors(current):
                raise SyncBlocked('NATIVE_FORMULA_ERRORS_PRESENT')
            for branch in BRANCHES:
                branch_plan = stage['branches'][branch]
                target_plan=branch_plan.get('targets',{}).get(name,{'state':branch_plan['state']})
                plan=branch_plan.get('plans',{}).get(name)
                partial=target_plan['state']!='READY'
                if plan is None or (partial and not plan['changes']):
                    statuses[branch] = 'PARTIAL'; continue
                if apply and partial and stage['config'].get('approved_partial_plan_hashes',{}).get(name,{}).get(branch)!=digest(plan):
                    statuses[branch]='PARTIAL';continue
                if any(statuses.get(d) not in ('VERIFIED','DRY_RUN_READY') for d in DEPENDENCIES.get(branch, ())):
                    statuses[branch] = 'PARTIAL'; continue
                latest = state.read('last-good-'+name+'-'+branch+'.json', {})
                if apply and latest.get('created_at',0) > stage['created_at']:
                    statuses[branch]='PARTIAL_NEWER_SOURCE_CHECKPOINT';continue
                # Resume uses the same immutable plans; a response lost after a
                # successful write is recognized as already applied, not appended.
                if any(current['cells'].get(k,{}).get('userEnteredValue',{}) not in (g['before'],g['after'])
                       for k,g in plan['guards'].items()):
                    statuses[branch]='PARTIAL_STABLE_ROW_KEY_CHANGED';continue
                pending = []
                preimage_changed=False
                for c in plan['changes']:
                    actual = current['cells'].get(c['key'],{}).get('userEnteredValue',{})
                    if actual == c['after']:
                        continue
                    if actual != c['before']:
                        preimage_changed=True
                        break
                    pending.append(c)
                if preimage_changed:
                    statuses[branch]='PARTIAL_OWNED_PREIMAGE_CHANGED';continue
                if not apply:
                    # Read current authored values through the native bounded
                    # endpoint before trusting the same endpoint after apply.
                    if hasattr(transport,'read_cells') and (pending or plan['guards']):
                        keys=list({c['key'] for c in plan['changes']} | set(plan['guards']))
                        try:
                            reread=transport.read_cells(target['id'],current,keys)
                        except Exception:
                            statuses[branch]='PARTIAL_READBACK_FAILED'
                            continue
                        if set(reread)!=set(keys) or any(
                            reread[k].get('userEnteredValue',{})!=current['cells'].get(k,{}).get('userEnteredValue',{})
                            for k in keys
                        ):
                            statuses[branch]='PARTIAL_READBACK_PREIMAGE_CHANGED'
                            continue
                    for c in plan['changes']:
                        current['cells'][c['key']] = {'userEnteredValue':c['after']}
                    statuses[branch] = 'PARTIAL_DRY_RUN_READY' if partial else 'DRY_RUN_READY'
                    decisions[name][branch]={'changed_rows':len({c['key'].rsplit(':',1)[0] for c in pending}),
                        'changed_cells':len(pending),'plan_hash':digest(plan),
                        'native_bounded_readback':hasattr(transport,'read_cells'),
                        'checkpoint_can_advance':not partial}
                    continue
                native_requests=requests_for(pending)
                for offset in range(0,len(native_requests),200):
                    transport.write(target['id'],native_requests[offset:offset+200])
                # Every changed cell is read natively; final full scan checks all
                # formulas/protected cells once, without rescanning source files.
                if hasattr(transport,'read_cells'):
                    keys=[c['key'] for c in plan['changes']] + list(plan['guards'])
                    current['cells'].update(transport.read_cells(target['id'],current,keys))
                else:
                    current = transport.snapshot(target['id'])
                if any(current['cells'].get(c['key'],{}).get('userEnteredValue',{})!=c['after'] for c in plan['changes']):
                    raise SyncBlocked('NATIVE_READBACK_MISMATCH')
                if protected_hash(current,target['role'])!=stage['protected'][name] or formula_errors(current):
                    raise SyncBlocked('POST_WRITE_PROTECTED_OR_FORMULA_CHECK_FAILED')
                statuses[branch] = 'PARTIAL_VERIFIED' if partial else 'VERIFIED'
                checkpoints[name+':'+branch] = {'plan_hash':digest(plan), 'state':'CELL_READBACK'}
                state.save('checkpoint-'+run_id+'.json',checkpoints)
            complete = all(statuses.get(b)==('VERIFIED' if apply else 'DRY_RUN_READY') for b in BRANCHES)
            results[name] = {'state':('SUCCESS' if apply else 'DRY_RUN_READY') if complete else 'PARTIAL', 'branches':statuses}
        except Exception as exc:
            results[name] = {'state':'PARTIAL', 'branches':statuses,
                             'reason':str(exc) if isinstance(exc,SyncBlocked) else 'READ_OR_WRITE_FAILED'}
    # Dry-run checks actual native targets again, NOT the simulated working copy.
    final_snapshots = {}
    for name,target in targets.items():
        try:
            after = transport.snapshot(target['id'])
            final_snapshots[name] = after
            ok = protected_hash(after,target['role'])==stage['protected'][name]
            results[name]['protected_hash_match'] = ok
            results[name]['formula_errors'] = len(formula_errors(after))
            if not ok or formula_errors(after):
                results[name]['state'] = 'PARTIAL'
        except Exception:
            results[name]['state']='PARTIAL';results[name]['reason']='FINAL_NATIVE_AUDIT_FAILED'
    try:
        from .sync_audit import reconcile
        comparison = reconcile(final_snapshots, stage['config'].get('reconciliation'))
    except Exception as exc:
        comparison = {'state':'FAIL','reason':str(exc) if isinstance(exc,SyncBlocked) else 'RECONCILIATION_INVALID'}
        for result in results.values():result['state']='PARTIAL'
    if apply:
        for name,result in results.items():
            if not result.get('protected_hash_match') or result.get('formula_errors'):
                continue
            for branch,status in result['branches'].items():
                if status!='VERIFIED':continue
                if branch in ('forecast','bonus') and comparison['state']!='PASS':continue
                plan=stage['branches'][branch]['plans'][name]
                final=final_snapshots[name]
                if any(final['cells'].get(c['key'],{}).get('userEnteredValue',{})!=c['after'] for c in plan['changes']):
                    result['state']='PARTIAL';result['branches'][branch]='PARTIAL';continue
                checkpoints[name+':'+branch]={'plan_hash':digest(plan),'state':'VERIFIED'}
                state.save('last-good-'+name+'-'+branch+'.json',{'run_id':run_id,'plan_hash':digest(plan),'created_at':stage['created_at']})
        state.save('checkpoint-'+run_id+'.json',checkpoints)
    for name,result in results.items():
        result['authored_cells_before'] = sum('userEnteredValue' in c for c in stage['before'][name]['cells'].values())
        result['authored_cells_after'] = sum('userEnteredValue' in c for c in final_snapshots.get(name,{'cells':{}})['cells'].values())
        if not apply and name in final_snapshots:
            def authored_digest(snapshot):
                return digest({k:c['userEnteredValue'] for k,c in snapshot['cells'].items() if 'userEnteredValue' in c})
            result['authored_hash_match']=authored_digest(stage['before'][name])==authored_digest(final_snapshots[name])
            if not result['authored_hash_match']:result['state']='PARTIAL'
    report = {'comparison':comparison, 'run_id':run_id, 'mode':'APPLY' if apply else 'DRY_RUN', 'targets':results,
              'blockers':{b:p.get('reason') for b,p in stage['branches'].items() if p['state']!='READY'},
              'planning':{b:p.get('targets',{})for b,p in stage['branches'].items()}}
    report['diagnostics']={b:p.get('diagnostics',{})for b,p in stage['branches'].items()}
    if not apply:report['validated_subsets']=decisions
    if not apply and stage['config'].get('private_common_scope'):
        try:
            from .sync_scope import check_common
            report['private_common_scope']=check_common(final_snapshots,stage['config']['private_common_scope'])
        except Exception as exc:
            report['private_common_scope']={'state':'FAIL','reason':str(exc)if isinstance(exc,SyncBlocked)else'PRIVATE_PROJECTION_INVALID'}
        try:
            from .sync_scope import compare_facts
            if set(final_snapshots)!={'A','B'}:raise SyncBlocked('BOTH_NATIVE_TARGETS_REQUIRED')
            report['common_scope_facts']=compare_facts(final_snapshots,stage['config']['private_common_scope'])
        except Exception as exc:
            report['common_scope_facts']={'state':'FAIL','reason':str(exc)if isinstance(exc,SyncBlocked)else'NATIVE_FACT_COMPARISON_INVALID'}
    state.save('audit-'+run_id+('-apply' if apply else '-dry')+'.json',report)
    return report


def main():
    parser=argparse.ArgumentParser(description='Private GLA runner; no schedules or PR merges')
    parser.add_argument('--config',required=True);parser.add_argument('--state-dir',required=True)
    parser.add_argument('--apply',action='store_true');parser.add_argument('--resume')
    args=parser.parse_args()
    attempt_id=uuid.uuid4().hex;state=None
    try:
        config=json.loads(Path(args.config).read_text());state=PrivateState(args.state_dir)
        with state.lock():
            transport=GoogleTransport.from_env(state)
            if not args.apply:
                from .sync_access_check import forbid_writes
                transport=forbid_writes(transport)
            if args.resume:
                if len(args.resume)!=64 or any(c not in '0123456789abcdef'for c in args.resume):
                    raise SyncBlocked('INVALID_RESUME_ID')
                stage=state.read('stage-'+args.resume+'.json')
                if not stage or digest(stage)!=args.resume or stage['config_hash']!=digest(config):
                    raise SyncBlocked('RESUME_STAGE_OR_CONFIG_CHANGED')
                run_id=args.resume
            else:
                # Re-capture inside this environment. A resume always uses its
                # original immutable stage instead of recapturing data.
                runtime_config=stage_meta_snapshot(config,state)
                run_id,stage=stage_run(runtime_config,transport,state,input_config_hash=digest(config))
            report=execute_stage(run_id,stage,transport,state,apply=args.apply)
        # Report contains counts/reason codes/hashes only; no worker rows or URLs.
        report['attempt_id']=attempt_id
        print(json.dumps(report));return 0 if all(t['state'] in ('SUCCESS','DRY_RUN_READY')for t in report['targets'].values()) else 2
    except (SyncBlocked,OSError,ValueError,KeyError) as exc:
        reason=str(exc) if isinstance(exc,SyncBlocked) else 'CONFIG_OR_RUNTIME_INPUT_INVALID'
        failure={'attempt_id':attempt_id,'state':'BLOCKED','reason':reason}
        if state is not None:state.save('attempt-'+attempt_id+'.json',failure,immutable=True)
        print(json.dumps(failure));return 2

if __name__=='__main__':raise SystemExit(main())
