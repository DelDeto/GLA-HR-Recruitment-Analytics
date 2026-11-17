"""Equal-definition native readback comparisons, without changing filters."""
from datetime import date, timedelta
import calendar
from .sync_plan import key
from .sync_runtime import SyncBlocked


def effective(snapshot, sid, row, col):
    val=snapshot['cells'].get(key(sid,row,col),{}).get('effectiveValue',{})
    if 'errorValue' in val:raise SyncBlocked('RECONCILIATION_FORMULA_ERROR')
    return next(iter(val.values()),None)


def reconcile(snapshots, spec):
    if not spec or set(snapshots)!={'A','B'}:
        raise SyncBlocked('NATIVE_RECONCILIATION_CONFIG_MISSING')
    scope=spec['scope'];lo=(date.fromisoformat(scope['from'])-date(1899,12,30)).days
    hi=(date.fromisoformat(scope['to'])-date(1899,12,30)).days
    start_day=date.fromisoformat(scope['from']);end_day=date.fromisoformat(scope['to'])
    closed=end_day.day==calendar.monthrange(end_day.year,end_day.month)[1]
    if hi<lo or start_day.day!=1:raise SyncBlocked('INVALID_RECONCILIATION_SCOPE')
    projected={}
    for name,snapshot in snapshots.items():
        # Both reports must include all requested days and end at the same day.
        begin=effective(snapshot,7000,5,1);end=effective(snapshot,7000,5,4)
        if not isinstance(begin,(int,float)) or not isinstance(end,(int,float)) or begin>lo or end<hi or (not closed and end!=hi):
            raise SyncBlocked('FILTER_DATE_SCOPES_NOT_EQUIVALENT')
        if effective(snapshot,7000,4,4)!=scope['group'] or effective(snapshot,7000,4,7)!=scope['factory']:
            raise SyncBlocked('FILTER_GROUP_FACTORY_NOT_EQUIVALENT')
        layout=spec[name];rows={}
        for r in range(layout['row_start'],layout['row_end']):
            month=effective(snapshot,layout['sheet_id'],r,layout['month_col'])
            factory=effective(snapshot,layout['sheet_id'],r,layout['factory_col'])
            if not isinstance(month,(int,float)) or not lo<=month<=hi or not factory:
                continue
            if scope['factory']!='Tất cả' and factory!=scope['factory']:continue
            k=(month,factory)
            if k in rows:raise SyncBlocked('DUPLICATE_MONTH_FACTORY_READBACK')
            rows[k]={m:effective(snapshot,layout['sheet_id'],r,c) for m,c in layout['metrics'].items()}
        if not rows:raise SyncBlocked('EMPTY_NATIVE_RECONCILIATION')
        projected[name]=rows
    if projected['A']!=projected['B']:
        raise SyncBlocked('NATIVE_CROSS_FILE_MISMATCH')
    return {'state':'PASS','rows':len(projected['A']),'scope':scope}
