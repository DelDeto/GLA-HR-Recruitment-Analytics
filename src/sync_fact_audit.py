"""Private evidence for immutable differences; never authorize a correction."""
from .sync_runtime import digest


def audit_table(snapshot,table):
    sid=table['sheet_id'];cols=table['columns'];keys=table['key_columns'];index={}
    def value(row,col):
        c=snapshot['cells'].get(f'{sid}:{row}:{col}',{})
        v=c.get('userEnteredValue',{})
        if 'formulaValue'in v:v=c.get('effectiveValue',{})
        return next(iter(v.values()),None)
    for row in range(table['start_row'],table['end_row']):
        identity=tuple(value(row,c)for c in keys)
        if any(v is None for v in identity):continue
        index.setdefault(identity,[]).append(row)
    out=[]
    for incoming in table['rows']:
        record=dict(zip(cols,incoming));identity=tuple(record[c]for c in keys)
        for row in index.get(identity,[]):
            changes=[]
            for col in cols:
                old,new=value(row,col),record[col]
                if old==new or new in(None,''):continue
                changes.append({'column':col,'before':old,'proposed':new})
            if not changes:continue
            metadata={7500:{4,5},7600:{4,5},7305:{6,8},7851:{10,11,20},7852:{10,11,15}}.get(sid,set())
            financial={7851:{6,7,8,9,13,15,16,17,18,19,21,22,23},7852:{6,7,8,9,13,16,17,18,19,20,21,22,23,24}}.get(sid,set())
            out.append({'sheet_id':sid,'row':row+1,'identity_hash':digest(identity),
                'before_hash':digest([value(row,c)for c in cols]),'proposal_hash':digest(incoming),
                'classification':'PROVENANCE_ONLY'if all(c['column']in metadata for c in changes)else'FEE_OR_ELIGIBILITY_REVIEW'if any(c['column']in financial for c in changes)else'BUSINESS_FACT_REVIEW',
                'changes':changes,'action':'RETAIN_LAST_GOOD_NO_PRODUCTION_WRITE'})
    return out
