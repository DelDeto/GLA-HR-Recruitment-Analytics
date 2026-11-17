"""Stable-key upserts and an explicit computed-region ownership boundary."""
from __future__ import annotations
from .sync_runtime import SyncBlocked, digest
from .sync_safety import validate_plan_writes, request_rect

# No ownership of Meta's scheduler-owned META_RAW, human policy/fee inputs,
# approval/execution ledgers, charts, or any UI. Profiles are further restricted
# by the private manifest and the actual target capacities.
OWNERS = {
    'lead': {7500, 7600},
    'pv_ob': {7501, 7601, 7305},
    'attendance': {7851, 7852, 7853, 7304, 7504},
    'forecast': {7950, 7503, 7002},
    'bonus': {7907, 7401},
    'meta': {7502},
}


def key(sid, row, col):
    return f'{sid}:{row}:{col}'


def value(snapshot, sid, row, col):
    return snapshot['cells'].get(key(sid, row, col), {}).get('userEnteredValue', {})


def scalar(cell):
    if 'formulaValue' in cell:
        raise SyncBlocked('FORMULA_IN_FACT_TABLE')
    return next(iter(cell.values()), None)


def entered(v):
    if v is None or v == '':
        return {}
    kind = 'boolValue' if isinstance(v, bool) else 'numberValue' if isinstance(v, (int, float)) else 'stringValue'
    return {kind: v}


def capacity(snapshot, sid):
    sh = next((s for s in snapshot['sheets'] if s['sheetId'] == sid), None)
    if not sh:
        raise SyncBlocked('TARGET_TAB_MISSING')
    return sh['gridProperties']['rowCount'], sh['gridProperties']['columnCount']


def validate_owned(requests, snapshot, role, branch, regions):
    validate_plan_writes(requests, {'installed': True, 'workbook_role': role})
    for request in requests:
        sid, r0, r1, c0, c1 = request_rect(request)
        if sid not in OWNERS[branch]:
            raise SyncBlocked('BRANCH_DOES_NOT_OWN_TAB')
        if branch=='bonus' and ((role=='MASTER_V23' and sid!=7907) or (role=='SEPTEMBER_V22' and sid!=7401)):
            raise SyncBlocked('BONUS_OUTPUT_LAYOUT_DOES_NOT_MATCH_ROLE')
        nr, nc = capacity(snapshot, sid)
        if r1 > nr or c1 > nc:
            raise SyncBlocked('TARGET_CAPACITY_EXCEEDED')
        if not any(sid == region[0] and r0 >= region[1] and r1 <= region[2]
                   and c0 >= region[3] and c1 <= region[4] for region in regions):
            raise SyncBlocked('OUTSIDE_DECLARED_OWNERSHIP')
        if branch == 'meta' and c0 <= 8 < c1:
            raise SyncBlocked('META_FILTER_FORMULA_IS_NOT_A_FACT')


def table_upserts(snapshot, table):
    """Upsert only supplied facts. Unknown/None never erases last-good data.

    coordinates and keys are zero-based. Stable key columns belong to the
    actual business table, not physical row numbers or candidate names alone.
    Conflicting duplicates fail the branch. Existing facts can be immutable.
    """
    sid, start, end = table['sheet_id'], table['start_row'], table['end_row']
    cols, keys = table['columns'], table['key_columns']
    if not keys or not set(keys) <= set(cols) or len(cols) != len(set(cols)):
        raise SyncBlocked('INVALID_STABLE_KEY_COLUMNS')
    if cols != sorted(cols) or min(cols) < 0 or start < 0 or end <= start:
        raise SyncBlocked('INVALID_TABLE_LAYOUT')
    if table.get('identity_basis') not in ('lead_day_group_phone', 'event_episode',
                                          'attendance_episode_period', 'account_day_campaign',
                                          'award_episode_policy_line'):
        raise SyncBlocked('UNVERIFIED_BUSINESS_IDENTITY')
    nr, nc = capacity(snapshot, sid)
    if end > nr or max(cols) >= nc:
        raise SyncBlocked('TARGET_CAPACITY_EXCEEDED')
    headers = table.get('expected_headers')
    if not isinstance(headers, dict) or not headers or {int(c) for c in headers} != set(cols):
        raise SyncBlocked('EXPECTED_TABLE_HEADERS_MISSING')
    header_guards = {}
    for c, expected in headers.items():
        c = int(c)
        if not isinstance(expected,str) or not expected or start < 1 or scalar(value(snapshot, sid, start-1, c)) != expected:
            raise SyncBlocked('TABLE_SCHEMA_CHANGED')
        header_guards[key(sid,start-1,c)] = {'before': entered(expected), 'after': entered(expected)}
    index, occupied = {}, []
    for row in range(start, end):
        values = [scalar(value(snapshot, sid, row, col)) for col in keys]
        if all(v is None for v in values):
            if any(value(snapshot, sid, row, c) for c in cols):
                raise SyncBlocked('EXISTING_ROW_MISSING_KEY')
            continue
        if any(v is None for v in values):
            raise SyncBlocked('EXISTING_ROW_INCOMPLETE_KEY')
        stable = digest(values)
        if stable in index:
            raise SyncBlocked('DUPLICATE_EXISTING_KEY')
        index[stable] = row; occupied.append(row)
    tail = max(occupied, default=start-1) + 1
    changes, guards, incoming = [], header_guards, {}
    for record in table['rows']:
        if len(record) != len(cols):
            raise SyncBlocked('ROW_WIDTH_CHANGED')
        values = dict(zip(cols, record)); identity = [values[k] for k in keys]
        if any(v is None or v == '' for v in identity):
            raise SyncBlocked('INCOMING_IDENTITY_MISSING')
        stable = digest(identity)
        if stable in incoming:
            if incoming[stable] != record:
                raise SyncBlocked('CONFLICTING_SOURCE_DUPLICATE')
            continue
        incoming[stable] = record
        existed = stable in index
        row = index.get(stable, tail)
        if not existed:
            if tail >= end:
                raise SyncBlocked('TARGET_CAPACITY_EXCEEDED')
            index[stable] = row; tail += 1
        for c in keys:
            guards[key(sid, row, c)] = {'before': value(snapshot, sid, row, c), 'after': entered(values[c])}
        for c in cols:
            if values[c] is None or values[c] == '':
                continue
            before, after = value(snapshot, sid, row, c), entered(values[c])
            if before == after:
                continue
            if existed and table.get('immutable_existing'):
                raise SyncBlocked('HISTORICAL_FACT_CONFLICT')
            if 'formulaValue' in before:
                raise SyncBlocked('ATTEMPT_TO_REPLACE_FORMULA_WITH_FACT')
            changes.append({'key': key(sid, row, c), 'before': before, 'after': after})
    return changes, guards


def requests_for(changes):
    # Group consecutive cells in a physical row; never bridge an unowned gap.
    ordered=sorted(changes,key=lambda c:tuple(map(int,c['key'].split(':'))))
    result=[];last=None
    for c in ordered:
        sid,row,col=map(int,c['key'].split(':'))
        if last is not None and (sid,row,col)==(last[0],last[1],last[2]+1):
            result[-1]['updateCells']['rows'][0]['values'].append({'userEnteredValue':c['after']})
        else:
            result.append({'updateCells':{'start':{'sheetId':sid,'rowIndex':row,'columnIndex':col},
                'rows':[{'values':[{'userEnteredValue':c['after']}]}],'fields':'userEnteredValue'}})
        last=(sid,row,col)
    return result


def expand_forecast(requests, snapshot):
    """Materialize native autofill expected formulas for full readback checks."""
    from openpyxl.formula.translate import Translator
    from openpyxl.utils import get_column_letter
    pending = {}
    for req in requests:
        kind, data = next(iter(req.items()))
        sid, r0, r1, c0, c1 = request_rect(req)
        if kind == 'updateCells' and data.get('fields') == 'userEnteredValue' and 'start' in data:
            for i, row in enumerate(data['rows']):
                for j, cell in enumerate(row['values']):
                    pending[key(sid,r0+i,c0+j)] = cell.get('userEnteredValue', {})
        elif kind == 'autoFill':
            spec = data['sourceAndDestination']; src = spec['source']
            if spec['dimension'] != 'ROWS' or src['endRowIndex']-src['startRowIndex'] != 1:
                raise SyncBlocked('UNSUPPORTED_FORECAST_FILL')
            for c in range(c0,c1):
                anchor = key(sid,r0,c); original = pending.get(anchor, value(snapshot,sid,r0,c))
                for r in range(r0+1,r1):
                    new = dict(original)
                    if 'formulaValue' in new:
                        new['formulaValue'] = Translator(new['formulaValue'], origin=f'{get_column_letter(c+1)}{r0+1}').translate_formula(f'{get_column_letter(c+1)}{r+1}')
                    pending[key(sid,r,c)] = new
        else:
            raise SyncBlocked('UNSUPPORTED_FORECAST_REFRESH_MUTATION')
    return [{'key': k, 'before': snapshot['cells'].get(k,{}).get('userEnteredValue',{}), 'after': v}
            for k,v in pending.items() if snapshot['cells'].get(k,{}).get('userEnteredValue',{}) != v]
