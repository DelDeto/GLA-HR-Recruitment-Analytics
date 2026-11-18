"""Consumer-aware source errors. No error is ever converted to a numeric zero."""
from __future__ import annotations
import re
from .sync_runtime import digest,SyncBlocked


def phone(value):
    if isinstance(value,float)and value.is_integer():value=int(value)
    text=re.sub(r'\D','',str(value or''))
    if text.startswith('84')and len(text)==11:text='0'+text[2:]
    if len(text)==9:text='0'+text
    return text if re.fullmatch(r'0\d{9}',text)else''


def formula_error_audit(tab,contract):
    """An optional CRM ID can be unused only with an independent strong ID.

    Rules live in the reviewed schema contract, not a source-cell instruction.
    Missing required identity stays critical even when another audit tab mirrors
    the same error. Row coordinates are private evidence, never worker keys.
    """
    cells={int(r):dict(cs)for r,cs in tab['rows']}
    consumed=set(contract.get('consumed_columns',[]));out=[]
    for err in tab.get('formula_errors',[]):
        row,col=err['row'],err['column'];state='CRITICAL';reason='UNVERIFIED_ERROR_SCOPE'
        if contract.get('state')=='VERIFIED_OUT_OF_SCOPE'and contract.get('reason_code'):
            state='EXCLUDED';reason=contract['reason_code']
        elif col not in consumed and consumed:
            state='EXCLUDED';reason='NONCONSUMED_FIELD'
        elif contract.get('parser')=='CRM_APPLICANTS'and col==0:
            values=cells.get(row,{})
            if phone(values.get(5)):
                state='EXCLUDED';reason='OPTIONAL_ID_UNUSED_VERIFIED_PHONE'
            elif re.match(r'^https?://\S+$',str(values.get(32)or'')):
                state='EXCLUDED';reason='OPTIONAL_ID_UNUSED_VERIFIED_CV'
            else:reason='CRM_IDENTITY_MISSING_WITH_FORMULA_ERROR'
        out.append(dict(err,state=state,reason=reason))
    return out


def validate_contract(tab,contract,consumer_sha=None):
    if not contract:return False
    if not tab['rows']and not tab.get('formula_errors'):
        return contract.get('parser')=='EMPTY_TAB'
    cells={int(r):dict(cs)for r,cs in tab['rows']}
    headers=contract.get('headers',{})
    matched=bool(headers)and all(cells.get(contract.get('header_row'),{}).get(int(c))==x for c,x in headers.items())
    if not matched:return False
    if contract.get('state')=='PARSED':
        return bool(contract.get('parser'))and bool(contract.get('consumed_columns'))
    if contract.get('state')=='VERIFIED_OUT_OF_SCOPE':
        # Excluding a complete tab also binds its content; changed/new rows must
        # be reviewed instead of silently inheriting an old exclusion decision.
        proof=contract.get('content_sha')==digest(tab)or(bool(consumer_sha)and contract.get('dependency_sha')==consumer_sha)
        return bool(contract.get('reason_code'))and proof
    return False


def source_scope_audit(source,contracts,consumer_sha=None):
    results={}
    for tab in source['tabs']:
        spec=contracts.get(str(tab['id']),{})
        valid=validate_contract(tab,spec,consumer_sha);errors=formula_error_audit(tab,spec)if valid else []
        critical=sum(e['state']=='CRITICAL'for e in errors)
        results[str(tab['id'])]={'state':spec.get('state')if valid and not critical else'UNVERIFIED',
            'reason_code':spec.get('reason_code'),'formula_errors':errors,
            'critical_errors':critical,'excluded_errors':len(errors)-critical}
    return results


def resolve_contracts(source,options):
    """New tabs may reuse a reviewed parser family; exclusions never spread."""
    role=next((k for k,fid in options.get('source_roles',{}).items()if fid==source['file_id']),'attendance')
    result=dict(options.get('tab_contracts',{}).get(source['file_id'],{}))
    for tab in source['tabs']:
        if str(tab['id'])in result:continue
        import hashlib
        reviewed=options.get('reviewed_title_contracts',{}).get(source['file_id'],{}).get('by_title_hash',{})
        pinned=reviewed.get(hashlib.sha256(tab.get('name','').encode()).hexdigest())
        if pinned:
            # Header validation and consumer SHA proof still run downstream.
            result[str(tab['id'])]=dict(pinned)
            continue
        matches=[]
        for template in options.get('schema_templates',[]):
            if template.get('source_role')!=role or template.get('state')!='PARSED':continue
            token=template.get('filename_token')
            if token and token.casefold()not in source['metadata'].get('name','').casefold():continue
            if len(template.get('headers',{}))<2:continue
            spec=dict(template)
            if spec.pop('consumed_all_columns',False):
                width=max((int(c)+1 for r,cs in tab['rows']for c,x in cs),default=0)
                spec['consumed_columns']=list(range(width))
            if validate_contract(tab,spec):matches.append(spec)
        unique={digest(m):m for m in matches}
        if len(unique)==1:result[str(tab['id'])]=next(iter(unique.values()))
    return result


# Columns checked by the pinned recruitment collector. Dates are required
# even where the legacy collector simply skips an undated row.
LEAD_FIELDS = {
    'SALE_LE': (1, (2,), (4,)), 'SALE_THAO': (1, (2,), (4,)),
    'SALE_YEN': (1, (2,), (3,)), 'CRM_APPLICANTS': (23, (1,), (5,)),
    'FORM_EPU': (0, (1,), (7,)), 'FORM_GTVT': (0, (24,), (25,)),
    'FORM_FEVC_GTVT': (0, (52,24,37), (53,25,43)),
    'FORM_UET': (0, (2,), (4,)),
}


def quarantine_lead_rows(source, contracts, collector_sha, parse_date):
    """Filter the collector input only, preserving the original source bundle."""
    tabs, quarantined = [], []
    for tab in source['tabs']:
        contract = contracts.get(str(tab['id']), {})
        parser = contract.get('parser')
        if parser not in LEAD_FIELDS or not validate_contract(tab, contract, collector_sha):
            tabs.append(tab)
            continue
        day_col, names, phones = LEAD_FIELDS[parser]
        header = contract['header_row']
        critical = {e['row'] for e in formula_error_audit(tab, contract)
                    if e['state'] == 'CRITICAL' and e['row'] > header}
        rows = []
        for row, pairs in tab['rows']:
            cells = dict(pairs)
            is_record = any(cells.get(c) for c in (*names, *phones))
            identity = any(phone(cells.get(c)) for c in phones)
            if parser == 'CRM_APPLICANTS':
                identity = identity or bool(re.fullmatch(r'https?://\S+',str(cells.get(32) or ''))
                                            or re.fullmatch(r'GLA-\d{6}-\d+',str(cells.get(0) or '')))
            reason = None
            if row in critical:
                reason = 'CONSUMED_FORMULA_ERROR'
            elif row > header and is_record:
                if not parse_date(cells.get(day_col)):
                    reason = 'INTAKE_DATE_MISSING'
                elif not identity or not any(cells.get(c) for c in names):
                    reason = 'INTAKE_IDENTITY_MISSING'
            if reason:
                quarantined.append({'file_id':source['file_id'],'tab_id':tab['id'],
                                    'row':row+1,'reason':reason})
                critical.discard(row)
            else:
                rows.append([row,pairs])
        quarantined.extend({'file_id':source['file_id'],'tab_id':tab['id'],
                            'row':row+1,'reason':'CONSUMED_FORMULA_ERROR'} for row in sorted(critical))
        tabs.append(dict(tab, rows=rows))
    return dict(source,tabs=tabs), quarantined
