"""Protocol bindings to the reviewed, private GLA source programs.

The originals remain private and are checked against live deployment anchors.
No program is selected by a workspace glob, executable source-data cell, or
unverified filename. All temporary inputs/output stay under a private directory.
"""
from __future__ import annotations
import collections
from contextlib import contextmanager, redirect_stdout
from datetime import date, datetime, timedelta
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from .sync_runtime import SyncBlocked, digest
from .sync_source_scope import active_roles, exclude_legacy_forms, UNUSED_SOURCE_HASHES


def v(snapshot, sid, row, col):
    cell=snapshot['cells'].get(f'{sid}:{row}:{col}',{})
    val=cell.get('effectiveValue',cell.get('userEnteredValue',{}))
    if 'errorValue' in val:raise SyncBlocked('BUSINESS_INPUT_FORMULA_ERROR')
    if 'formulaValue' in val:return None
    return next(iter(val.values()),None)


def authored(snapshot,sid,row,col):
    return snapshot['cells'].get(f'{sid}:{row}:{col}',{}).get('userEnteredValue',{})


def iso(value):
    if isinstance(value,(int,float)) and not isinstance(value,bool):
        return (date(1899,12,30)+timedelta(days=int(value))).isoformat()
    if isinstance(value,(date,datetime)):return value.isoformat()[:10]
    return str(value)[:10] if value else ''


def serial(value):
    return (date.fromisoformat(str(value)[:10])-date(1899,12,30)).days if value else None


def legacy_cells(snapshot, titles=None):
    props={s['sheetId']:s for s in snapshot['sheets'] if titles is None or s['title'] in titles}
    out={s['title']:{'cells':{}} for s in props.values()}
    from openpyxl.utils import get_column_letter
    for key,cell in snapshot['cells'].items():
        sid,row,col=map(int,key.split(':'))
        if sid not in props:continue
        val=cell.get('effectiveValue',cell.get('userEnteredValue',{}))
        if 'errorValue' in val:raise SyncBlocked('BUSINESS_INPUT_FORMULA_ERROR')
        x=next(iter(val.values()),None)
        if x is not None and 'formulaValue' not in val:
            out[props[sid]['title']]['cells'][get_column_letter(col+1)+str(row+1)]=x
    return out


class Book:
    def __init__(self,sheets):self.sheets=sheets
    def __getitem__(self,title):return Sheet(self.sheets[title]['cells'])
    def __contains__(self,title):return title in self.sheets


class Sheet:
    def __init__(self,cells):
        self.cells=cells
        from openpyxl.utils import coordinate_to_tuple
        coords=[coordinate_to_tuple(k)for k in cells]
        self.max_row=max((x[0]for x in coords),default=0)
        self.max_col=max((x[1]for x in coords),default=0)
    def __getitem__(self,coord):
        class Cell:
            def __init__(self,value):self.value=value
        return Cell(self.cells.get(coord))
    def cell(self,row,col):
        from openpyxl.utils import get_column_letter
        return self[get_column_letter(col)+str(row)]
    @property
    def values(self):
        for r in range(1,self.max_row+1):yield tuple(self.cell(r,c).value for c in range(1,self.max_col+1))


def native_source(source):
    sheets=[]
    for tab in source['tabs']:
        blocks=[]
        for row,pairs in tab['rows']:
            values=[{} for _ in range(max((int(c)for c,_ in pairs),default=-1)+1)]
            for c,x in pairs:
                kind='boolValue'if isinstance(x,bool)else'numberValue'if isinstance(x,(int,float))else'stringValue'
                if x is not None:values[int(c)]={'effectiveValue':{kind:x}}
            blocks.append({'startRow':int(row),'startColumn':0,'rowData':[{'values':values}]})
        sheets.append({'properties':{'title':tab['name'],'sheetId':tab['id']},'data':blocks})
    return {'spreadsheetId':source['file_id'],'sheets':sheets}


def load_verified(spec,snapshot,module_name):
    path=Path(spec['path'])
    if path.is_symlink() or not path.is_file():raise SyncBlocked('BUSINESS_PROGRAM_MISSING')
    raw=path.read_bytes();sha=hashlib.sha256(raw).hexdigest()
    if sha!=spec['sha256']:raise SyncBlocked('BUSINESS_PROGRAM_SHA_MISMATCH')
    anchor=spec['anchor']
    code=v(snapshot,anchor['sheet_id'],anchor['row'],anchor['column'])
    if not isinstance(code,str) or hashlib.sha256(code.encode()).hexdigest()!=sha:
        raise SyncBlocked('LIVE_BUSINESS_ANCHOR_CHANGED')
    if 'hash_row' in anchor and v(snapshot,anchor['sheet_id'],anchor['hash_row'],anchor['column'])!=sha:
        raise SyncBlocked('LIVE_BUSINESS_DECLARED_SHA_MISMATCH')
    module_spec=importlib.util.spec_from_file_location(module_name,path)
    module=importlib.util.module_from_spec(module_spec)
    sys.modules[module_name]=module
    module_spec.loader.exec_module(module)
    return module


def coverage(payload,used,options):
    """A byte read is not proof that a business parser consumed a new schema."""
    out={}
    for source in payload['sources']['sources']:
        from .sync_source_audit import source_scope_audit,resolve_contracts
        role=next((k for k,fid in options.get('source_roles',{}).items()if fid==source['file_id']),None)
        if role in UNUSED_SOURCE_HASHES:
            active_roles(options['source_roles'])
            out[source['file_id']]={'fingerprint':source['fingerprint'],'tabs':{
                str(t['id']):{'state':'VERIFIED_OUT_OF_SCOPE','reason_code':'USER_CONFIRMED_UNUSED'}for t in source['tabs']}}
            continue
        program='collector'if role and role!='ob'else'normalizer'
        sha=options.get('programs',{}).get(program,{}).get('sha256')
        reviewed=source_scope_audit(source,resolve_contracts(source,options),sha)
        claims={}
        for tab in source['tabs']:
            status={'state':'VERIFIED_OUT_OF_SCOPE','reason_code':'OTHER_PIPELINE_SOURCE'}
            if source['file_id']in used:
                status=reviewed[str(tab['id'])]
                if not tab['rows']and not tab.get('formula_errors'):
                    status={'state':'VERIFIED_OUT_OF_SCOPE','reason_code':'EMPTY_TAB'}
            claims[str(tab['id'])]=status
        out[source['file_id']]={'fingerprint':source['fingerprint'],'tabs':claims}
    return out


def envelope(payload,options,normalized,used):
    claims=coverage(payload,used,options)
    quarantine=normalized.get('lead_source_quarantine',[])
    isolated={(r['file_id'],str(r['tab_id']),r['row']) for r in quarantine}
    for file_id, claim in claims.items():
        for tab_id, status in claim['tabs'].items():
            errors=[e for e in status.get('formula_errors',[]) if e['state']=='CRITICAL']
            if errors and all((file_id,tab_id,e['row']+1) in isolated for e in errors):
                status['state']='PARSED'
    complete=payload['sources']['transport_scan_complete']and all(
        t['state']in ('PARSED','VERIFIED_OUT_OF_SCOPE')for f in claims.values()for t in f['tabs'].values())
    return {'version':options['version'],'complete':complete,'validation':'PASS'if complete else'PARTIAL',
            'coverage':claims,'normalized':normalized}


def table(snapshot,sid,columns,keys,rows,identity,*,start=3,end=None,immutable=False):
    props=next((s for s in snapshot['sheets']if s['sheetId']==sid),None)
    if props is None:raise SyncBlocked('BUSINESS_TARGET_TAB_MISSING')
    headers={str(c):v(snapshot,sid,start-1,c)for c in columns}
    if any(not isinstance(x,str)or not x for x in headers.values()):
        raise SyncBlocked('BUSINESS_TARGET_HEADER_UNVERIFIED')
    return {'sheet_id':sid,'start_row':start,'end_row':end or props['gridProperties']['rowCount'],
            'columns':columns,'key_columns':keys,'rows':rows,'identity_basis':identity,
            'expected_headers':headers,'immutable_existing':immutable}


@contextmanager
def legacy_environment(payload,options,work,*,collector=False):
    import openpyxl
    master=payload['targets']['A'];saved_load=openpyxl.load_workbook;saved_argv=sys.argv[:]
    saved_modules={k:sys.modules.get(k)for k in ['folder_revenue_sync','bonus_policy_engine','bonus_sheet_adapter','read_sheet_xml']}
    normalizer=load_verified(options['programs']['normalizer'],master,'folder_revenue_sync')
    try:
        if collector:
            sheets=legacy_cells(master,{'LEADS_CV_AUDIT_09_11','LEADS_CV_RULES'})
            openpyxl.load_workbook=lambda *a,**k:Book(sheets)
            sys.argv=['collector','--work',str(work),'--asof',payload['as_of'],'--from-date','2026-01-01','--workbook','in-memory']
        yield normalizer
    finally:
        openpyxl.load_workbook=saved_load;sys.argv=saved_argv
        for k,old in saved_modules.items():
            if old is None:sys.modules.pop(k,None)
            else:sys.modules[k]=old


def recruitment(payload,options,work,*,with_leads=True):
    roles=active_roles(options['source_roles']);sources={s['file_id']:s for s in payload['sources']['sources']}
    from .sync_source_audit import resolve_contracts, quarantine_lead_rows
    resolved=dict(options,tab_contracts={fid:resolve_contracts(source,options)for fid,source in sources.items()})
    required=(['sale_le','sale_thao','sale_yen','crm','form_epu','form_gtvt','form_fevc_gtvt','form_uet']if with_leads else['pv','ob'])
    if any(roles.get(k)not in sources for k in required):raise SyncBlocked('RECRUITMENT_SOURCE_MISSING')
    quarantine=[]
    with legacy_environment(payload,options,work)as normalizer:
        for role in required:
            filename='opt-form-'+role[5:]+'.json' if role.startswith('form_') else 'opt-'+role+'_full.json'
            source=sources[roles[role]]
            contracts=resolved['tab_contracts'][roles[role]]
            if role=='crm':
                primary=[t for t in source['tabs']if contracts.get(str(t['id']),{}).get('parser')=='CRM_APPLICANTS']
                if len(primary)!=1:raise SyncBlocked('CRM_PRIMARY_SCHEMA_AMBIGUOUS_OR_MISSING')
                source=dict(source,tabs=primary+[t for t in source['tabs']if t['id']!=primary[0]['id']])
            if role not in ('pv','ob'):
                source, held=quarantine_lead_rows(source,contracts,options['programs']['collector']['sha256'],normalizer.date)
                quarantine.extend(held)
            (work/filename).write_text(json.dumps(native_source(source),ensure_ascii=False))
    with legacy_environment(payload,options,work,collector=True):
        collector=load_verified(options['programs']['collector'],payload['targets']['A'],'gla_current_collector')
        with exclude_legacy_forms(collector,options['source_roles']), redirect_stdout(io.StringIO()):
            leads,issues=collector.build_leads()if with_leads else([],[])
            events,whitelist,eventissues=([],[],[])if with_leads else collector.build_events([])
        legacy={}
        if with_leads:
            from .sync_legacy_leads import review,merge_receipts
            legacy=review(payload['sources']['sources'],resolved,leads,sys.modules['folder_revenue_sync'].date,payload['as_of'],collector.plant)
            leads,duplicate_count=merge_receipts(leads,legacy['receipts'])
            legacy['merged_duplicates']=duplicate_count
    return {'leads':leads,'events':events,'onboard_all':whitelist,'issues':issues+eventissues,
            'asof':payload['as_of'],'source_roles':roles,'legacy_sales_audit':legacy,
            'source_exclusions':{role:'USER_CONFIRMED_UNUSED'for role in UNUSED_SOURCE_HASHES},
            'lead_source_quarantine':quarantine}


def lead_adapter(payload,options,work):
    result=recruitment(payload,options,work)
    # Identity reconciliation is independent of source/file/tab order.
    unique={}
    for r in result['leads']:
        k=(r['date'],r['group'],r['identity'],r['factory']if r['group']=='LĐPT'else '')
        if k not in unique:unique[k]=r
    result['leads']=list(unique.values())
    counts=collections.Counter((r['date'],r['factory'],r['group'])for r in result['leads'])
    recent=[];history=[]
    for (day,fac,group),count in sorted(counts.items()):
        row=[serial(day),fac,group,count,'Verified current collector; stable person/day/group key','Sales / CRM / Form']
        (recent if day>='2026-09-01'else history).append(row)
    used={fid for role,fid in active_roles(options['source_roles']).items() if role not in ('pv','ob')}
    out=envelope(payload,options,result,used);out['tables']={}
    legacy_counts=result.get('legacy_sales_audit',{}).get('counts',{})
    if result['lead_source_quarantine'] or legacy_counts.get('needs_review') or legacy_counts.get('unknown_date'):
        out['held']={role:['LEAD_SOURCE_ROWS_QUARANTINED'] for role in payload['targets']}
    for role,s in payload['targets'].items():
        import re
        from openpyxl.utils import column_index_from_string
        routes={}
        for row in range(3,1999):
            formula=authored(s,7500,row,3).get('formulaValue')
            if not formula:continue
            match=re.fullmatch(r'=N\(LEADS_LDPT!([A-P])(\d+)\)',formula)
            if not match:raise SyncBlocked('LEAD_FORMULA_BINDING_UNVERIFIED')
            col=column_index_from_string(match[1])-1;rr=int(match[2])-1
            if col in (0,11)or v(s,6203,2,col)!=v(s,7500,row,1)or v(s,6203,rr,0)!=v(s,7500,row,0):
                raise SyncBlocked('LEAD_SOURCE_ROUTE_KEY_MISMATCH')
            routes[(v(s,7500,row,0),v(s,7500,row,1),'LĐPT')]=(rr,col)
        direct=[];matrix={};cols=[0]+[c for c in range(1,16)if c!=11]
        for record in recent:
            route=routes.get(tuple(record[:3]))
            if route is None:direct.append(record);continue
            rr,col=route
            values=matrix.setdefault(rr,{0:record[0]});values[col]=record[3]
        matrices=[[values.get(c)for c in cols]for row,values in sorted(matrix.items())]
        out['tables'][role]=[table(s,6203,cols,[0],matrices,'lead_day_group_phone',end=1000),
                             table(s,7500,list(range(6)),[0,1,2],direct,'lead_day_group_phone',end=1999),
                             table(s,7600,list(range(6)),[0,1,2],history,'lead_day_group_phone',end=1999)]
        out['tables'][role][0]['nondecreasing_columns']=cols[1:]
        for target_table in out['tables'][role][1:]:target_table['nondecreasing_columns']=[3]
        for target_table in out['tables'][role][1:]:target_table['preserve_existing_columns']=[4,5]
        out['normalized'].setdefault('ownership_audit',{})[role]={'formula_routes':len(routes),'source_matrix_rows':len(matrix),'direct_rows':len(direct)}
    return out


def pv_adapter(payload,options,work):
    result=recruitment(payload,options,work,with_leads=False)
    # Legacy keys are retained only for unique event buckets. Ambiguous legacy
    # name/day buckets are quarantined, never given a row-ordinal identity.
    buckets=collections.defaultdict(list)
    for r in result['events']:buckets[(r['factory'],r['stage'],r['date'],r['name'].strip().upper())].append(r)
    events=[];issues=list(result.get('issues',[]))
    for bucket,rows in buckets.items():
        if len(rows)!=1:
            issues.append({'type':'EVENT_IDENTITY_REVIEW','bucket_hash':digest(bucket)});continue
        r=dict(rows[0]);r['identity_review']=not bool(r.get('phone')or r.get('cccd')or r.get('id'))
        events.append(r)
    master=payload['targets']['A'];previous=prior_roster(master)
    sources={s['file_id']:s for s in payload['sources']['sources']}
    ob=native_source(sources[options['source_roles']['ob']])
    with legacy_environment(payload,options,work)as normalizer:
        roster,roster_issues=normalizer.load_roster(ob,[r for r in previous if r['factory']=='Pegatron'and r['id']],previous)
        normalizer.add_aux_roster(ob,roster,roster_issues)
        norm_name=normalizer.norm
        for event in events:
            # The suffix is a fixed canonical bucket, never a source row ordinal.
            bucket=(event['factory'],event['stage'],event['date'],norm_name(event['name']))
            event['canonical_key']=hashlib.sha256('|'.join(map(str,(*bucket,0))).encode()).hexdigest()[:24]
    norm={'events':events,'onboard_all':result['onboard_all'],'issues':issues+roster_issues,
          'roster':[{k:x for k,x in r.items()if k!='phone'}for r in roster],
          'whitelist_loaded':True,'asof':payload['as_of']}
    out=envelope(payload,options,norm,{options['source_roles'][k]for k in ['pv','ob']});out['tables']={}
    out['held']={};norm['event_alias_review']={};norm['source_reference_reuse']={}
    for role,s in payload['targets'].items():
        rows=[];reviews=[];reused=[]
        # Refuse a parallel set of event IDs on top of the installed legacy IDs.
        # An explicit, reviewed identity migration is required before deployment.
        old_sources={};old_events=collections.defaultdict(set);legacy_people={}
        for row in range(1799,2600):
            key=v(s,6240,row,0)
            if key:legacy_people[key]=(v(s,6240,row,1),norm_name(v(s,6240,row,2)),v(s,6240,row,3),v(s,6240,row,8))
        for sid,end in [(7501,999),(7601,1499)]:
            for row in range(3,end):
                source=v(s,sid,row,6)
                if source:
                    old_sources.setdefault((v(s,sid,row,0),v(s,sid,row,1),v(s,sid,row,3),source),set()).add(v(s,sid,row,5))
                    old_events[(v(s,sid,row,0),v(s,sid,row,1),v(s,sid,row,3))].add(v(s,sid,row,5))
        for event in events:
            if event['identity_review']:
                reviews.append({'event':event,'action':'MISSING_STABLE_IDENTITY_NO_APPEND'})
                continue
            candidates={event['canonical_key'],'EV-'+event['canonical_key'],event['key'],'EV-'+event['key']}
            hist='HIST-'+hashlib.sha256((event['stage']+'|'+event['factory']+'|'+norm_name(event['name'])+'|'+event['date']).encode()).hexdigest()[:24]
            candidates.add(hist)
            canonical='EV-'+event['canonical_key']
            if event['stage']=='ONBOARD':
                people=[p for p in roster if p['factory']==event['factory']and p['join']==event['date']and norm_name(p['name'])==norm_name(event['name'])]
                if len(people)!=1:raise SyncBlocked('EVENT_ONBOARD_EPISODE_UNVERIFIED')
                canonical=people[0]['key'];candidates.add(canonical)
            record=[serial(event['date']),event['factory'],'LĐPT',event['stage'],1,canonical,event['source'],event['method']]
            aliases=old_sources.get((record[0],record[1],record[3],record[6]),set())
            expected_person=(event['factory'],norm_name(event['name']),record[0],event['stage'])
            # A row URL is provenance, not a person's identity. External row
            # insertions may reuse it for a different, evidenced candidate.
            for old_key in list(aliases):
                previous_person=legacy_people.get(old_key)
                if previous_person and previous_person!=expected_person and old_key not in candidates:
                    reused.append({'old_key':old_key,'current_key':canonical,'source':event['source'],
                        'reason':'SOURCE_ROW_REUSED_DIFFERENT_VERIFIED_PERSON','action':'PRESERVE_OLD_ID_DO_NOT_ALIAS'})
                    aliases=aliases-{old_key}
            for key in old_events.get((record[0],record[1],record[3]),set()):
                if key in candidates or legacy_people.get(key)==expected_person:
                    aliases=aliases|{key};candidates.add(key)
            if aliases and(len(aliases)!=1 or not aliases<=candidates):
                reviews.append({'event':event,'aliases':sorted(aliases),'candidates':sorted(candidates),
                    'legacy_people':{k:legacy_people.get(k)for k in aliases},'action':'RETAIN_ALL_EXISTING_IDS_NO_APPEND'})
                continue
            if aliases:record[5]=next(iter(aliases))
            rows.append(record)
        existing_keys={v(s,7305,row,7) for row in range(3,2000)}
        rr=[]
        for person in roster:
            if person['key'] not in existing_keys and not person.get('id'):
                reviews.append({'episode':person,'action':'MISSING_EMPLOYEE_ID_NO_APPEND'})
                continue
            rr.append([person['factory'],person['id'],person['name'],serial(person['join']),
                       serial(person['off']),person['problem'],person['source'],person['key'],person['bridge']])
        out['tables'][role]=[
            table(s,7501,list(range(8)),[5],[r for r in rows if r[0]>=serial('2026-09-01')],'event_episode',end=999,immutable=True),
            table(s,7601,list(range(8)),[5],[r for r in rows if r[0]<serial('2026-09-01')],'event_episode',end=1499,immutable=True),
            table(s,7305,list(range(9)),[7],rr,'event_episode',end=2000,immutable=True)]
        out['tables'][role][0]['verified_formula_columns']=[2]
        for event_table in out['tables'][role][:2]:
            event_table['preserve_existing_columns']=[6,7]
        out['tables'][role][2].update(retain_duplicate_identity_columns=[0,1,2,3,4,7],preserve_existing_columns=[6,8])
        norm['event_alias_review'][role]=reviews
        norm['source_reference_reuse'][role]=reused
        if reviews or any(i.get('type')=='EVENT_IDENTITY_REVIEW' for i in issues):
            out['held'][role]=['LEGACY_EVENT_ALIAS_REVIEW_REQUIRED']
    (work/'event-alias-review.json').write_text(json.dumps(norm['event_alias_review'],ensure_ascii=False))
    return out


def revenue_rules(snapshot):
    rules=[];basis_map={'NGÀY LỊCH':'CALENDAR','CÔNG XÁC NHẬN':'WORKDAYS','KỲ TÍNH PHÍ NGUỒN':'SOURCE_PERIOD'}
    for row in range(150,190):
        vals=[v(snapshot,6240,row,c)for c in range(12)]
        if not vals[0]:continue
        tier=vals[11];tiers=[]
        for tr in range(200,220):
            t=[v(snapshot,6240,tr,c)for c in range(5)]
            if tier and t[0]==tier and t[4]is True:tiers.append({'from':t[1],'to':t[2],'rate':t[3]})
        if vals[5]is True and vals[10]not in basis_map:raise SyncBlocked('ACTIVE_FEE_BASIS_UNKNOWN')
        rules.append({'factory':vals[0],'from':iso(vals[1]),'to':iso(vals[2]),'rate':vals[3],
            'days':vals[4],'active':vals[5]is True,'program':vals[6],
            'basis':basis_map.get(vals[10],'UNCONFIRMED'),'tier_group':tier,'tiers':tiers})
    if not rules:raise SyncBlocked('FEE_RULES_NOT_READ')
    return rules


def prior_roster(snapshot):
    out=[];seen={}
    for row in range(3,2000):
        values=[v(snapshot,7305,row,c)for c in range(9)]
        if not values[0]:continue
        item=dict(zip(['factory','id','name','join','off','problem','source','key','bridge'],values))
        item['join']=iso(item['join']);item['off']=iso(item['off'])
        item={k:(x if x is not None else '')for k,x in item.items()}
        core=tuple(item[k]for k in ('factory','id','name','join','off','problem'))
        if item['key']in seen:
            if seen[item['key']]!=core:raise SyncBlocked('CONFLICTING_PRIOR_ROSTER_EPISODE')
            continue  # In-memory alias only; never delete the native duplicate.
        seen[item['key']]=core;out.append(item)
    return out


def previous_fees(snapshot):
    result={'daily':[],'monthly':[]}
    layouts=[('daily',7851,['date','factory','id','name','join','fee_end','hours','rate','revenue','status','source','onboard_source','episode_key','pending','program','confirmed_workdays','workdays_before','workdays_after','basis','raw_hours','note','billable_hours','fee_start','raw_fee_end']),
             ('monthly',7852,['period_start','period_end','factory','id','name','join','hours','rate','revenue','status','source','onboard_source','episode_key','pending','program','note','confirmed_workdays','source_amount','source_adjustment','basis','billable_hours','fee_start','fee_end','raw_fee_start','raw_fee_end'])]
    for kind,sid,fields in layouts:
        nr=next(s['gridProperties']['rowCount']for s in snapshot['sheets']if s['sheetId']==sid)
        for row in range(3,nr):
            vals=[v(snapshot,sid,row,c)for c in range(len(fields))]
            if vals[0]is None:continue
            item=dict(zip(fields,vals))
            if kind=='monthly':item['date']=''
            for f in ['date','join','fee_start','fee_end','period_start','period_end']:
                if f in item:item[f]=iso(item[f])
            result[kind].append(item)
    return result


def attendance_files(payload,options,work):
    """Include newly discovered attendance files; convert native inputs locally."""
    sources={s['file_id']:s for s in payload['sources']['sources']}
    ids=set(options.get('attendance_files',[]))|set(sources)-set(options['source_roles'].values())
    files=[]
    for fid in sorted(ids):
        import re
        if not re.fullmatch(r'[A-Za-z0-9_-]+',fid):raise SyncBlocked('ATTENDANCE_SOURCE_ID_INVALID')
        if fid not in sources:raise SyncBlocked('ATTENDANCE_FILE_MISSING')
        source=sources[fid];mime=source['metadata'].get('mimeType');path=work/(fid+'.xlsx')
        if mime=='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':
            original=source.get('blob_path')
            if not original or hashlib.sha256(Path(original).read_bytes()).hexdigest()!=source['fingerprint']:
                raise SyncBlocked('ORIGINAL_XLSX_BYTES_NOT_VERIFIED')
            path.write_bytes(Path(original).read_bytes())
        elif mime=='application/vnd.google-apps.spreadsheet':
            if digest(source['tabs'])!=source['fingerprint']:raise SyncBlocked('NATIVE_ATTENDANCE_CONTENT_CHANGED')
            import openpyxl,re,zipfile
            book=openpyxl.Workbook();book.remove(book.active)
            for tab in source['tabs']:
                title=tab['name']
                if len(title)>31 or re.search(r'[\\/*?:\[\]]',title):
                    raise SyncBlocked('NATIVE_ATTENDANCE_TITLE_MAPPING_REQUIRED')
                sheet=book.create_sheet(title)
                for row,cols in tab['rows']:
                    for col,x in cols:
                        # Source strings beginning '=' are data, never executed.
                        c=sheet.cell(row+1,col+1,x)
                        if isinstance(x,str):c.data_type='s'
            book.properties.created=book.properties.modified=datetime(2000,1,1)
            raw=io.BytesIO();book.save(raw);book.close()
            # Zip timestamps must not invalidate native-source approval on retry.
            with zipfile.ZipFile(io.BytesIO(raw.getvalue()))as src,zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED)as dst:
                for name in sorted(src.namelist()):
                    info=zipfile.ZipInfo(name,date_time=(2000,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
                    content=src.read(name)
                    if name=='docProps/core.xml':
                        content=re.sub(rb'(<dcterms:modified[^>]*>).*?(</dcterms:modified>)',rb'\g<1>2000-01-01T00:00:00Z\2',content)
                    dst.writestr(info,content)
        else:raise SyncBlocked('ATTENDANCE_SOURCE_MIME_UNSUPPORTED')
        files.append({'id':fid,'name':source['metadata']['name'],'path':str(path),
                      'modified':source['metadata'].get('modifiedTime','')})
    return files


def attendance_adapter(payload,options,work):
    roles=options['source_roles'];master=payload['targets']['A'];previous=prior_roster(master)
    sources={s['file_id']:s for s in payload['sources']['sources']}
    ob=roles.get('ob')
    if ob not in sources or not payload['normalized'].get('pv_ob',{}).get('whitelist_loaded'):
        raise SyncBlocked('FRESH_ONBOARD_WHITELIST_MISSING')
    files=attendance_files(payload,options,work)
    inputs={'folder-inputs.json':files,'onboard-input.json':native_source(sources[ob]),
        'revenue-rules.json':revenue_rules(master),'previous-roster.json':previous,
        'previous-normalized.json':previous_fees(master),'as-of.json':{'from':'2026-01-01','to':payload['as_of']},
        'pegatron-aux.json':[r for r in previous if r['factory']=='Pegatron'and r['id']],
        'bonus-rules.json':[],'fee-hour-adjustments.json':options['fee_hour_adjustments'],
        'file-periods.json':{}}
    for row in range(3,1000):
        key=v(master,7304,row,11);lo=v(master,7304,row,12);hi=v(master,7304,row,13)
        if key and lo and hi:inputs['file-periods.json'][key]={'from':iso(lo),'to':iso(hi)}
    for name,value in inputs.items():(work/name).write_text(json.dumps(value,ensure_ascii=False))
    with legacy_environment(payload,options,work)as normalizer:
        with redirect_stdout(io.StringIO()):normalizer.process(work)
    result=json.loads((work/'revenue-normalized.json').read_text())
    if any(r['state']=='CẦN KIỂM TRA MẪU'for r in result['manifest']):raise SyncBlocked('ATTENDANCE_NEW_SCHEMA_UNVERIFIED')
    out=envelope(payload,options,result,{f['id']for f in files}|{ob});out['tables']={}
    dr=[[serial(r['date']),r['factory'],r['id'],r['name'],serial(r['join']),serial(r.get('fee_end')),r['hours'],r['rate'],r['revenue'],r['status'],r['source'],r['onboard_source'],r['episode_key'],int(r['status']!='VALID'),r['program'],r.get('confirmed_workdays'),r.get('workdays_before'),r.get('workdays_after'),r.get('basis'),r.get('raw_hours'),r.get('note'),r.get('billable_hours'),serial(r.get('fee_start')),r.get('raw_fee_end')]for r in result['daily']]
    mr=[[serial(r['period_start']),serial(r['period_end']),r['factory'],r['id'],r['name'],serial(r['join']),r['hours'],r['rate'],r['revenue'],r['status'],r['source'],r['onboard_source'],r['episode_key'],int(r['status']!='VALID'),r['program'],r.get('note'),r.get('confirmed_workdays'),r.get('source_amount'),r.get('source_adjustment'),r.get('basis'),r.get('billable_hours'),serial(r.get('fee_start')),serial(r.get('fee_end')),r.get('raw_fee_start'),r.get('raw_fee_end')]for r in result['monthly']]
    for role,snapshot in payload['targets'].items():
        out['tables'][role]=[table(snapshot,7851,list(range(24)),[0,12],dr,'attendance_episode_period',immutable=True),
                            table(snapshot,7852,list(range(25)),[0,1,12],mr,'attendance_episode_period',immutable=True)]
    return out


def bonus_adapter(payload,options,work):
    master=payload['targets']['A'];programs=options['programs'];saved={k:sys.modules.get(k)for k in ['read_sheet_xml','bonus_policy_engine','bonus_sheet_adapter']}
    try:
        reader=load_verified(programs['read_sheet_xml'],master,'read_sheet_xml')
        engine=load_verified(programs['bonus_engine'],master,'bonus_policy_engine')
        load_verified(programs['bonus_adapter'],master,'bonus_sheet_adapter')
        operations=load_verified(programs['bonus_operations'],master,'gla_bonus_operations')
        cells=legacy_cells(master,{'TT_NHAN_SU','TT_YTD_NGAY','TT_YTD_KY','DT_DON_GIA','CHINH_SACH_THUONG','OPS_THUONG','QL_PIPELINE'})
        cells['QL_PIPELINE']['cells']['B432']=serial(payload['as_of'])
        reader.read_xlsx=lambda _:cells
        with redirect_stdout(io.StringIO()):data,result,rows=operations.from_export('in-memory')
        if not result['entitlements']:
            raise SyncBlocked('NO_CONFIRMED_BONUS_ACCEPTANCE_CASE')
        if any(r[14]=='Đã thực hiện thưởng'for r in rows):raise SyncBlocked('BONUS_PROGRAM_CLAIMS_EXECUTION')
        out=envelope(payload,options,{'input':data,'result':result,'rows':rows},set());out['tables']={}
        out['tables']['A']=[table(master,7908,list(range(22)),[0],rows,'award_episode_policy_line',start=2000,end=5000)]
        # B retains its own legacy schema. Only reviewed entitlements may be
        # appended; no unsupported/no-policy pseudo-awards are manufactured.
        b=payload['targets']['B'];cols=list(range(14))+[18,19];legacy=[]
        byepisode={p['episode']:p for p in data['people']};policies={p['id']:p for p in data['policies']}
        for e in result['entitlements']:
            p=byepisode[e['episode']];policy=policies[e['policy']]
            legacy.append([e['id'],p['factory'],p['name'],p.get('worker'),serial(p['join']),e['policy'],e['line'],serial(e['payable_after']),float(e['accrued']),None,e['status'],policy['evidence'],p['source'],e['payer'],e['episode']+'|'+e['policy']+'|'+e['line'],float(e['confirmed_units'])])
        out['tables']['B']=[table(b,7401,cols,[0],legacy,'award_episode_policy_line',immutable=True)]
        return out
    finally:
        for k,old in saved.items():
            if old is None:sys.modules.pop(k,None)
            else:sys.modules[k]=old


def forecast_adapter(payload,options,work):
    """Refresh only the installed V2.2 inputs, retaining native physical rows."""
    if not payload['normalized'].get('pv_ob',{}).get('whitelist_loaded'):
        raise SyncBlocked('FRESH_ONBOARD_WHITELIST_MISSING')
    from .attendance_presence import read_sources, match_presence
    sources_by_id={s['file_id']:s for s in payload['sources']['sources']}
    files=attendance_files(payload,options,work)
    records,manifests,errors=read_sources(files,date.fromisoformat(payload['as_of']))
    for record in records:
        # Presence approvals bind the original native source, not a local ZIP.
        fid=record['source'].split('/d/',1)[1].split('/',1)[0]
        record['fingerprint']=sources_by_id[fid]['fingerprint']
    for manifest in manifests:manifest['fingerprint']=sources_by_id[manifest['file_id']]['fingerprint']
    if errors:raise SyncBlocked('FORECAST_PRESENCE_SCHEMA_UNVERIFIED')
    configs={};decisions={}
    from .revenue_forecast import Source,evaluate
    for role,snapshot in payload['targets'].items():
        roster=[]
        for row in range(3,2000):
            key=v(snapshot,7305,row,7)
            if not key:continue
            roster.append({'row':row+1,'key':key,'id':v(snapshot,7305,row,1)or'',
                'name':v(snapshot,7305,row,2)or'','factory':v(snapshot,7305,row,0),
                'join':iso(v(snapshot,7305,row,3)),'official':iso(v(snapshot,7305,row,4)),
                'group':v(snapshot,7305,row,12)or'LĐPT'})
        people=match_presence(roster,records,manifests)
        existing=[];registry=[];confirmations={}
        for row in range(1003,1200):
            fac=v(snapshot,7002,row,0);month=iso(v(snapshot,7002,row,1))
            if not fac:
                if any(v(snapshot,7002,row,c)not in(None,'')for c in range(5,10)):
                    raise SyncBlocked('ORPHAN_SOURCE_CONFIRMATION')
                continue
            if len(month)!=10:raise SyncBlocked('SOURCE_REGISTRY_MONTH_INVALID')
            existing.append(fac+'|'+month[:7])
            ms=[m for m in manifests if m['factory']==fac and m['month']==month]
            fingerprints=sorted({m['fingerprint']+'|'+m['file_id']+'|'+m['sheet']for m in ms})
            fp=hashlib.sha256('\n'.join(fingerprints).encode()).hexdigest()if ms else''
            registry.append({'factory':fac,'month':month,'imported':bool(ms),'fingerprint':fp,
                'state':'PENDING_CONFIRMATION'if ms else'MISSING',
                'evidence':' | '.join(f"https://drive.google.com/file/d/{m['file_id']}/view#sheet={m['sheet']}"for m in ms)})
            confirmations[fac+'|'+month]={name:v(snapshot,7002,row,c)or''
                for name,c in [('state',5),('by',6),('at',7),('fingerprint',8),('evidence',9)]}
        expected={(m['factory'],m['month'])for m in manifests if m['month']>='2026-08-01'}
        missing=expected-{(s['factory'],s['month'])for s in registry}
        if missing:raise SyncBlocked('NEW_FORECAST_REGISTRY_SCOPE_REQUIRES_REVIEW')
        original=snapshot['cells'].get('7950:3:38',{}).get('note')
        coverage_formula=snapshot['cells'].get('7950:1:0',{}).get('note')
        if not original or not coverage_formula:raise SyncBlocked('NATIVE_FORECAST_NOTES_MISSING')
        configs[role]={'people':people,'sources':registry,'confirmations':confirmations,
            'evaluated_at':payload['as_of']+' ICT','original_calendar_formula':original,
            'original_coverage_formula':coverage_formula,'coverage_existing':True,
            'ui_ground':{},'installed':True,'workbook_role':'MASTER_V23'if role=='A'else'SEPTEMBER_V22',
            'source_scan_complete':payload['sources']['transport_scan_complete'],
            'source_coverage':{'listed_files':len(files),'parsed_files':len(files),
                'listed_tabs':sum(len(sources_by_id[f['id']]['tabs'])for f in files),
                'parsed_tabs':sum(len(sources_by_id[f['id']]['tabs'])for f in files),
                'errors':errors,'whitelist_loaded':payload['normalized']['pv_ob']['whitelist_loaded']},
            'existing_registry_keys':existing}
        result=[]
        for p in people:
            states={date.fromisoformat(s['month']):Source(
                state=confirmations[p['factory']+'|'+s['month']].get('state')or s['state'],
                fingerprint=s['fingerprint'],
                confirmed_fingerprint=str(confirmations[p['factory']+'|'+s['month']]['fingerprint']),
                confirmed_by=str(confirmations[p['factory']+'|'+s['month']]['by']),
                confirmed_at=str(confirmations[p['factory']+'|'+s['month']]['at']),
                imported=s['imported'],evidence=s['evidence'])for s in registry if s['factory']==p['factory']}
            decision=evaluate({date.fromisoformat(m):x for m,x in p['presence'].items()},states,
                              identity_ok=p['identity_ok'],
                              official_stop=date.fromisoformat(p['official'])if p['official']else None)
            result.append({'key':p['key'],'status':decision.status,
                           'inferred_stop':decision.inferred_stop.isoformat()if decision.inferred_stop else None})
        decisions[role]=result
    out=envelope(payload,options,{'decisions':decisions},{f['id']for f in files})
    out['forecast']=configs
    return out


def invoke(payload, work):
    """Protocol entry shared by the pinned subprocess and private audit."""
    options=payload['options']
    branches={'lead':lead_adapter,'pv_ob':pv_adapter,'attendance':attendance_adapter,
              'forecast':forecast_adapter,'bonus':bonus_adapter}
    if payload['branch']=='meta':
        from .sync_meta_snapshot import adapter
        return adapter(payload,options,work)
    if payload['branch']not in branches:raise SyncBlocked('BUSINESS_BRANCH_UNKNOWN')
    return branches[payload['branch']](payload,options,Path(work))


def main():
    import os
    os.umask(0o077)
    try:
        payload=json.load(sys.stdin)
        with tempfile.TemporaryDirectory(prefix='business-',dir='.')as work:
            result=invoke(payload,work)
        print(json.dumps(result,ensure_ascii=False,allow_nan=False))
        return 0
    except Exception as exc:
        # No traceback/source exception body can expose candidate data.
        print(str(exc)if isinstance(exc,SyncBlocked)else'BUSINESS_ADAPTER_REJECTED',file=sys.stderr)
        return 2


if __name__=='__main__':raise SystemExit(main())
