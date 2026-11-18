"""First-install, credentialed six-branch dry run. No apply or schedule path.

Business source is accepted only at reviewed native anchors with hard-coded
SHA256 pins. It is never selected from source data or an instruction cell.
All personnel data and programs remain on the ephemeral private job volume.
"""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo
from .sync_runtime import PrivateState, SyncBlocked, digest
from .sync_sources import GoogleTransport
from .sync_access_check import forbid_writes, read_hints, RESOURCE_HASHES
from .sync_business import v, iso
from .sync_runner import BRANCHES, stage_meta_snapshot, stage_run, execute_stage


PROGRAMS = {
    'collector': ('collector.py', 7506, 320, 0, 321,
        'ec8f5c56eab23936af1a1b407fdea5e74712784da80eaf1bc575db9cfb0b4b40'),
    'normalizer': ('folder_revenue_sync.py', 7306, 1, 0, 2,
        '3dd93fd06816f296dadba8b69b5bf022fcf905cca3c7c7cdfe0f4a90104150ee'),
    'read_sheet_xml': ('read_sheet_xml.py', 7908, 99, 1, None,
        '245a936e90b4f6328397ebd2989e12578a6308105d827b0562cfcd30409aebfa'),
    'bonus_engine': ('bonus_policy_engine.py', 7908, 100, 1, None,
        'f465aa67264419122b2a87f0fb3be6a600d03a6d2adc4d5c8c318a16fff4c5a7'),
    'bonus_adapter': ('bonus_sheet_adapter.py', 7908, 101, 1, None,
        '6c3af3f046df02353f40bc20360217965f05f3e79c0e5bef2eb84b5effdc1762'),
    'bonus_operations': ('bonus_operations_report.py', 7908, 102, 1, None,
        'ede2de6d0d5b7062d4b573ae478b53075732e66143cb5c6603851afd90726183'),
}


def install_programs(snapshot, state):
    programs = {}
    # Validate the complete set before writing or importing any business code.
    verified = []
    for name, (filename, sid, row, col, hash_row, expected) in PROGRAMS.items():
        source = v(snapshot, sid, row, col)
        if not isinstance(source, str) or hashlib.sha256(source.encode()).hexdigest() != expected:
            raise SyncBlocked('REVIEWED_DEPLOYMENT_PROGRAM_CHANGED')
        if hash_row is not None and v(snapshot, sid, hash_row, col) != expected:
            raise SyncBlocked('REVIEWED_DEPLOYMENT_DECLARED_HASH_CHANGED')
        anchor = {'sheet_id': sid, 'row': row, 'column': col}
        if hash_row is not None: anchor['hash_row'] = hash_row
        verified.append((name, filename, source, expected, anchor))
    for name, filename, source, expected, anchor in verified:
        path = state.save_blob(filename, source.encode())
        programs[name] = {'path': str(path), 'sha256': expected, 'anchor': anchor}
    return programs


def schema_contracts(resources, programs, registry):
    contracts = {}
    # Only explicit reviewed tab identities inherit exclusions. New/renamed
    # tabs remain unverified until a separately reviewed contract is installed.
    for role, fid in resources.items():
        if role in ('A', 'B', 'folder'): continue
        contracts[fid] = {'by_title_hash': {}}
        for item in registry:
            if item['source_role'] != role: continue
            spec = {k: x for k, x in item.items() if k not in ('source_role', 'title_sha256')}
            if spec['state'] == 'VERIFIED_OUT_OF_SCOPE':
                spec['dependency_sha'] = programs['normalizer' if role == 'ob' else 'collector']['sha256']
            contracts[fid]['by_title_hash'][item['title_sha256']] = spec
    return contracts


def manifest(resources, before, programs, adapter, registry, as_of):
    source_roles = {k: x for k, x in resources.items() if k not in ('A', 'B', 'folder')}
    options = {'version': 'v2.4-first-install', 'programs': programs,
               'source_roles': source_roles, 'reviewed_title_contracts': schema_contracts(resources, programs, registry),
               'legacy_intake_confirmed': True, 'legacy_default_group': 'LĐPT',
               'fee_hour_adjustments': []}
    for row in (230, 231):
        s = before['A']
        if v(s, 6240, row, 7) is True:
            if not v(s, 6240, row, 2) or not isinstance(v(s, 6240, row, 6), (int, float)):
                raise SyncBlocked('APPROVED_FEE_CAP_SCHEMA_CHANGED')
            options['fee_hour_adjustments'].append({'id':v(s,6240,row,0), 'factory':v(s,6240,row,1),
                'episode_key': v(s, 6240, row, 2),
                'period_start': iso(v(s, 6240, row, 3)), 'period_end': iso(v(s, 6240, row, 4)),
                'cap_hours': v(s, 6240, row, 6), 'active': True,
                'approved_by':v(s,6240,row,8), 'approved_at':iso(v(s,6240,row,9)),
                'evidence':v(s,6240,row,10)})
    ownership = {
        'lead': [[6203,3,1000,0,11],[6203,3,1000,12,16],[7500,3,1999,0,6],[7600,3,1999,0,6]],
        'pv_ob': [[7501,3,999,0,8],[7601,3,1499,0,8],[7305,3,2000,0,9]],
        'attendance': [[7851,3,20000,0,24],[7852,3,2000,0,25]],
        # Forecast ownership must be separately grounded against the installed
        # A/B layouts. Empty ownership cannot silently approve an inferred map.
        'forecast': [], 'bonus': [], 'meta': [],
    }
    targets = {role: {'id': resources[role], 'role': name, 'ownership': deepcopy(ownership)}
               for role, name in [('A','MASTER_V23'),('B','SEPTEMBER_V22')]}
    targets['A']['ownership']['bonus'] = [[7908,2000,5000,0,22]]
    targets['B']['ownership']['bonus'] = [[7401,3,3000,0,14],[7401,3,3000,18,20]]
    end = min([as_of] + [iso(v(s,7000,5,4)) for s in before.values() if v(s,7000,5,4)])
    scope = {'from': '2026-09-01', 'to': end, 'group': 'LĐPT', 'factory': 'Tất cả'}
    return {'as_of': as_of, 'targets': targets, 'source_files': list(source_roles.values()),
        'source_folders': [resources['folder']], 'deployment_approved': False,
        'single_writer_private_volume': False, 'require_service_account_preflight': True,
        'capture_meta_in_runtime': True,
        'adapters': {b: dict(adapter, options=deepcopy(options)) for b in BRANCHES},
        'private_common_scope': scope,
        'reconciliation': {'scope': scope,
            'A': {'sheet_id':7950,'row_start':1199,'row_end':1343,'month_col':48,'factory_col':49,
                  'metrics':{'forecast':50,'actual':51,'pending':52}},
            'B': {'sheet_id':7950,'row_start':3,'row_end':51,'month_col':48,'factory_col':49,
                  'metrics':{'forecast':51,'actual':53,'pending':54}}}}


class InitialSnapshots:
    def __init__(self, transport, before):
        self.transport = transport
        self.pending = {s['id']: s for s in before.values()}
    def snapshot(self, fid):
        if fid in self.pending: return self.pending.pop(fid)
        return self.transport.snapshot(fid)
    def __getattr__(self, name): return getattr(self.transport, name)


def run(state):
    transport = forbid_writes(GoogleTransport.from_env(state))
    resources = read_hints(transport, os.getenv('GOOGLE_SHEET_ID',''))
    if set(resources) != set(RESOURCE_HASHES): raise SyncBlocked('DEPLOYMENT_RESOURCE_DISCOVERY_INCOMPLETE')
    before = {n: transport.snapshot(resources[n]) for n in ('A','B')}
    programs = install_programs(before['A'], state)
    bundle = PrivateState(state.root / 'adapter')
    bundle.save_blob('entry.py', b'from src.sync_business import main\nraise SystemExit(main())\n')
    # Public reviewed code is copied into this pinned isolated bundle. Business
    # programs above are selected only by PROGRAMS, never by a workspace glob.
    source_root = Path(__file__).parent
    for path in sorted(source_root.glob('*.py')):
        target = bundle.root / 'src' / path.name
        target.parent.mkdir(mode=0o700, exist_ok=True)
        target.write_bytes(path.read_bytes()); target.chmod(0o600)
    files = {str(p.relative_to(bundle.root)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in bundle.root.rglob('*.py')}
    adapter = {'entrypoint': str(bundle.root/'entry.py'), 'sha256': files['entry.py'],
               'files': files, 'version':'v2.4-first-install', 'timeout_seconds': 600}
    registry = json.loads((source_root/'sync_schema_registry.json').read_text())
    as_of = datetime.now(ZoneInfo('Asia/Ho_Chi_Minh')).date().isoformat()
    config = manifest(resources, before, programs, adapter, registry, as_of)
    state.save('production-manifest.json', config)
    config = stage_meta_snapshot(config, state)
    transport = InitialSnapshots(transport, before)
    run_id, stage = stage_run(config, transport, state)
    report = execute_stage(run_id, stage, transport, state, apply=False)
    report.update(production_writes=0, release_state='BLOCKED',
                  runtime_setup={'programs':len(programs),'reviewed_tab_contracts':len(registry),
                                 'persistent_writer_installed':False})
    report['source_scan'] = {k: stage['sources'][k] for k in ('listed_files','parsed_files','listed_tabs','transport_scan_complete')}
    report['source_formula_errors'] = sum(len(t.get('formula_errors',[])) for s in stage['sources']['sources'] for t in s['tabs'])
    state.save('installation-dry-run-report.json', report)
    return report


def main():
    os.umask(0o077)
    try:
        with tempfile.TemporaryDirectory(prefix='gla-v24-private-') as folder:
            report = run(PrivateState(folder))
            print(json.dumps(report, ensure_ascii=False))
        return 0 if all(t['state']=='DRY_RUN_READY' for t in report['targets'].values()) else 2
    except Exception as exc:
        print(json.dumps({'state':'BLOCKED','production_writes':0,
            'reason':str(exc) if isinstance(exc,SyncBlocked) else 'PRIVATE_DEPLOYMENT_DRY_RUN_FAILED'}))
        return 2


if __name__=='__main__': raise SystemExit(main())
