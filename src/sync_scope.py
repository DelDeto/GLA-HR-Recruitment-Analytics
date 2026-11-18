"""Private same-scope calendar cross-check; never change production filters.

This is an independent check of the installed calendar, not a replacement fee
or forecast engine. Its per-row results must first match each native baseline.
"""
from __future__ import annotations
from datetime import date,timedelta
import re
from .sync_business import v,serial,revenue_rules
from .sync_runtime import SyncBlocked


BAD=r'OFF_DATE_MISSING|OFF_BEFORE_JOIN|DUPLICATE_EMPLOYEE_ID|AUX_DATE_AMBIGUOUS|CONFLICTING_OFF_DATE|Thiếu ngày nghỉ|chưa rõ ngày nghỉ'


def project(snapshot,scope,*,stops=None):
    lo,hi=serial(scope['from']),serial(scope['to'])
    if hi<lo:raise SyncBlocked('INVALID_RECONCILIATION_SCOPE')
    rules=revenue_rules(snapshot)
    holidays={(v(snapshot,6240,r,8),v(snapshot,6240,r,9))for r in range(3,120)}
    rows={};totals={}
    for r in range(3,2000):
        fac=v(snapshot,7305,r,0);join=v(snapshot,7305,r,3);key=v(snapshot,7305,r,7)
        if not fac or not key:continue
        if not isinstance(join,(int,float))or isinstance(join,bool):raise SyncBlocked('FORECAST_JOIN_INVALID')
        if join>hi:continue
        group=v(snapshot,7305,r,12)or'LĐPT'
        if scope['group']!='Tất cả'and group!=scope['group']:continue
        if scope['factory']!='Tất cả'and fac!=scope['factory']:continue
        month=date.fromisoformat(scope['from']).replace(day=1)
        while serial(month)<=hi:
            totals.setdefault((month.isoformat(),fac),None)
            month=date(month.year+(month.month==12),month.month%12+1,1)
        off=v(snapshot,7305,r,4);warning=str(v(snapshot,7305,r,5)or'')
        dayjoin=(date(1899,12,30)+timedelta(days=int(join))).isoformat()
        hits=[p for p in rules if p['active']and p['factory']==fac and
              (not p['from']or p['from']<=dayjoin)and(not p['to']or p['to']>=dayjoin)]
        bad=bool(re.search(BAD,warning))or(isinstance(off,(int,float))and off<join)
        value=None;months={}
        if len(hits)==1 and not bad:
            policy=hits[0];basis=policy['basis'];limit=policy['days']or 0;price=policy['rate']or 0
            begin,end=v(snapshot,7503,r,20),v(snapshot,7503,r,21)
            sourceok=isinstance(begin,(int,float))and isinstance(end,(int,float))
            good=(basis in ('CALENDAR','WORKDAYS','SOURCE_PERIOD')and
                  (limit>0 or basis=='SOURCE_PERIOD'and sourceok)and(price>0 or policy['tier_group']))
            if basis=='SOURCE_PERIOD'and not sourceok:good=False
            if good:
                stop=hi
                if isinstance(off,(int,float)):stop=min(stop,max(join,off-1))
                if basis=='SOURCE_PERIOD':stop=min(stop,end)
                elif basis=='CALENDAR':stop=min(stop,join+limit-1)
                inferred=(stops or {}).get(key)if stops is not None else v(snapshot,7950,r,10)
                if isinstance(inferred,str):inferred=serial(inferred)
                if isinstance(inferred,(int,float)):stop=min(stop,max(serial('2026-09-01'),inferred)-1)
                value=0;monthcount=0;cumulative=0
                for ds in range(int(join),int(stop)+1):
                    day=date(1899,12,30)+timedelta(days=ds)
                    if day.day==1:monthcount=0
                    flag=(ds==join or((day.weekday()<5 if fac=='LG Electronic'else day.weekday()!=6)and(fac,ds)not in holidays))
                    monthcount+=int(flag)
                    working=flag and monthcount<=(24 if fac=='Pegatron'else 31 if fac=='LG Electronic'else 26)
                    cumulative+=int(working)
                    if not working or ds<lo or(basis=='SOURCE_PERIOD'and ds<begin)or(basis=='WORKDAYS'and cumulative>limit):continue
                    rate=price
                    if policy['tier_group']:
                        tiers=[t for t in policy['tiers']if t['from']<=cumulative<=t['to']]
                        rate=tiers[0]['rate']if len(tiers)==1 else 0
                    if not isinstance(rate,(int,float))or rate<=0:value=None;months={};break
                    amount=8*rate;value+=amount
                    mk=(day.replace(day=1).isoformat(),fac)
                    months[mk]=months.get(mk,0)+amount
        rows[r]={'key':key,'value':value,'months':months}
        if value is not None:
            for mk in totals:
                if mk[1]==fac:totals[mk]=(totals[mk]or 0)+months.get(mk,0)
    return rows,totals


def check_common(snapshots,scope):
    """Require native baseline agreement before accepting a private projection."""
    projections={};baselines={}
    for role,s in snapshots.items():
        native_scope={'from':(date(1899,12,30)+timedelta(days=int(v(s,7000,5,1)))).isoformat(),
            'to':(date(1899,12,30)+timedelta(days=int(v(s,7000,5,4)))).isoformat(),
            'group':'Tất cả','factory':'Tất cả'}
        rows,_=project(s,native_scope)
        differences=sum(item['value']!=v(s,7503,row,9)for row,item in rows.items())
        baselines[role]={'rows':len(rows),'mismatches':differences}
        if differences:raise SyncBlocked('INDEPENDENT_CALENDAR_BASELINE_MISMATCH_'+role)
        _,projections[role]=project(s,scope)
    if projections['A']!=projections['B']:raise SyncBlocked('COMMON_SCOPE_FORECAST_MISMATCH')
    return {'state':'PASS','basis':'PRIVATE_PROJECTION_VALIDATED_AGAINST_NATIVE_BASELINES',
            'scope':scope,'rows':len(projections['A']),'baselines':baselines}


def compare_facts(snapshots,scope):
    """Parity of existing facts, independent of selected presentation filters.

    This does not certify source completeness or replace direct API validation.
    Unknown and zero have distinct representations in every comparison.
    """
    lo,hi=serial(scope['from']),serial(scope['to']);out={}
    for role,s in snapshots.items():
        metrics={}
        def add(kind,key,value):
            dest=metrics.setdefault(kind,{})
            if value is None or isinstance(value,bool):dest[key]=None
            elif key not in dest:dest[key]=value
            elif dest[key]is not None:dest[key]+=value
        for sid,kind in [(7500,'lead'),(7501,'pv_ob')]:
            end=next(p['gridProperties']['rowCount']for p in s['sheets']if p['sheetId']==sid)
            for row in range(3,end):
                day=v(s,sid,row,0);fac=v(s,sid,row,1);group=v(s,sid,row,2)
                if not isinstance(day,(int,float))or not lo<=day<=hi:continue
                if scope['group']!='Tất cả'and group!=scope['group']:continue
                if scope['factory']!='Tất cả'and fac!=scope['factory']:continue
                key=(day,fac,group,v(s,sid,row,3)if sid==7501 else'LEAD')
                add(kind,key,v(s,sid,row,4 if sid==7501 else 3))
        for sid,kind in [(7851,'actual_daily'),(7852,'actual_period')]:
            end=next(p['gridProperties']['rowCount']for p in s['sheets']if p['sheetId']==sid)
            for row in range(3,end):
                begin=v(s,sid,row,0);stop=v(s,sid,row,1)if sid==7852 else begin
                if not isinstance(begin,(int,float))or not isinstance(stop,(int,float))or begin<lo or stop>hi:continue
                fac=v(s,sid,row,2 if sid==7852 else 1)
                if scope['factory']!='Tất cả'and fac!=scope['factory']:continue
                if scope['group']not in ('Tất cả','LĐPT'):continue
                episode=v(s,sid,row,12)
                key=(begin,stop,fac,episode,v(s,sid,row,9))
                add(kind,key,v(s,sid,row,8))
        out[role]=metrics
    if out['A']!=out['B']:raise SyncBlocked('COMMON_SCOPE_NATIVE_FACTS_DIFFER')
    return {'state':'PASS','basis':'CURRENT_NATIVE_FACTS_PARITY_ONLY',
            'groups':{k:len(x)for k,x in out['A'].items()},'scope':scope}
