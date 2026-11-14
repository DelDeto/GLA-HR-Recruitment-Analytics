"""Generate the same native forecast controls for each production workbook.

Inputs are private live reads; never commit them. Existing calendar engines
remain authoritative. This module adds only a forecast cap and traceability.
"""
import re
from datetime import date
from .revenue_forecast import cap_calendar_formula

TAB='FORECAST_V22'
SHEET_ID=7950
SOURCE_ROW=1004


def serial(iso):
    return (date.fromisoformat(iso[:10])-date(1899,12,30)).days if iso else ''


def cell(value):
    if value is None or value=='': return {}
    key='boolValue' if isinstance(value,bool) else 'numberValue' if isinstance(value,(int,float)) else 'formulaValue' if str(value).startswith('=') else 'stringValue'
    return {'userEnteredValue':{key:value}}


def put(sheet,row,col,rows):
    return {'updateCells':{'start':{'sheetId':sheet,'rowIndex':row-1,'columnIndex':col-1},'rows':[{'values':[cell(v) for v in r]} for r in rows],'fields':'userEnteredValue'}}


def local_baseline(formula):
    return re.sub(r'(?<![A-Z!$])\b([CDEUV])(\d+)\b',r'QL_DU_KIEN!$\1\2',formula)


def trace_rows(people, evaluated_at):
    out=[]
    for p in people:
        r=p['row']; month_start=lambda m:f'DATE(2026,{m},1)'
        source=lambda m:f'IFNA(INDEX(DOANH_THU!$K$1004:$K$1200,MATCH($D{r}&"|"&TEXT({month_start(m)},"yyyy-mm"),DOANH_THU!$L$1004:$L$1200,0)),"MISSING")'
        # T:AE = Jan-Dec presence; blank = unknown, FALSE = known absence.
        refs={m:chr(83+m) if m<=7 else {8:'AA',9:'AB',10:'AC',11:'AD',12:'AE'}[m] for m in range(1,13)}
        gaps=[]
        for m in range(9,13):
            prev=f'{refs[m-1]}{r}'; now=f'{refs[m]}{r}'
            gaps.append(f'IF(AND($Q{r}=TRUE,ISLOGICAL({prev}),{prev}=TRUE,ISLOGICAL({now}),{now}=FALSE,{source(m)}="COMPLETE"),DATE(2026,{m},1),99999)')
        inferred=f'=LET(cut,MIN({",".join(gaps)}),IF(cut=99999,"",cut))'
        last=f'=IF(COUNTIF(T{r}:AE{r},TRUE)=0,"",MAX(ARRAYFORMULA(IF(T{r}:AE{r}=TRUE,DATE(2026,SEQUENCE(1,12),1),0))))'
        nxt=f'EDATE(G{r},1)'
        ns=f'=IF(G{r}="","MISSING",IFNA(INDEX(DOANH_THU!$K$1004:$K$1200,MATCH(D{r}&"|"&TEXT({nxt},"yyyy-mm"),DOANH_THU!$L$1004:$L$1200,0)),"MISSING"))'
        np=f'=IF(OR(G{r}="",MONTH(G{r})=12),"",IF(ISLOGICAL(INDEX(T{r}:AE{r},1,MONTH(G{r})+1)),INDEX(T{r}:AE{r},1,MONTH(G{r})+1),""))'
        # Existing source-window/calendar policy logic is preserved for expiry.
        expiry=f'=IF(COUNTIFS(DT_DON_GIA!$A$151:$A$190,D{r},DT_DON_GIA!$F$151:$F$190,TRUE,DT_DON_GIA!$B$151:$B$190,"<="&F{r},DT_DON_GIA!$C$151:$C$190,">="&F{r})>1,"",IF(ISNUMBER(QL_DU_KIEN!V{r}),QL_DU_KIEN!V{r}+1,IFERROR(LET(hits,(DT_DON_GIA!$A$151:$A$190=D{r})*(DT_DON_GIA!$F$151:$F$190=TRUE)*((DT_DON_GIA!$B$151:$B$190="")+(DT_DON_GIA!$B$151:$B$190<=F{r})>0)*((DT_DON_GIA!$C$151:$C$190="")+(DT_DON_GIA!$C$151:$C$190>=F{r})>0),idx,MATCH(1,hits,0),IF(AND(SUM(hits)=1,INDEX(DT_DON_GIA!$K$151:$K$190,idx)="NGÀY LỊCH"),F{r}+INDEX(DT_DON_GIA!$E$151:$E$190,idx),"")),"")))'
        # Preserve the approved first-workday rule, even for same-day leaving.
        effective=f'=LET(official,IF(AND(ISNUMBER(J{r}),J{r}>=F{r}),MAX(F{r}+1,J{r}),""),limits,HSTACK(official,K{r},L{r}),IF(COUNT(limits)=0,"",MIN(FILTER(limits,ISNUMBER(limits)))))'
        status=f'=IF(Q{r}<>TRUE,"IDENTITY_REVIEW",IF(ISNUMBER(K{r}),IF(SUMPRODUCT(N(T{r}:AE{r}=TRUE),N(DATE(2026,SEQUENCE(1,12),1)>K{r}))>0,"REJOIN_REVIEW","INFERRED_STOP"),IF(ISNUMBER(J{r}),"OFFICIAL_STOP",IF(ISNUMBER(G{r}),"PRESENT","NO_ATTENDANCE_EVIDENCE"))))'
        evidence=' | '.join(v for m,v in sorted(p['evidence'].items()) if m>='2026-08-01')
        # Keep cells bounded; source manifest contains all file/tab fingerprints.
        evidence=evidence[:45000]
        proof=f'=TEXTJOIN(" | ",TRUE,R{r},IF(ISNUMBER(K{r}),IFNA(INDEX(DOANH_THU!$E$1004:$E$1200,MATCH(D{r}&"|"&TEXT(K{r},"yyyy-mm"),DOANH_THU!$L$1004:$L$1200,0)),""),""))'
        row=[f'=QL_DU_KIEN!R{r}',f'=QL_DU_KIEN!A{r}',f'=QL_DU_KIEN!B{r}',f'=QL_DU_KIEN!C{r}',f'=QL_DU_KIEN!F{r}',f'=QL_DU_KIEN!D{r}',last,ns,np,f'=IF(ISNUMBER(QL_DU_KIEN!E{r}),QL_DU_KIEN!E{r},"")',inferred,expiry,effective,status,proof,evaluated_at,f'=AND(A{r}=S{r},{"TRUE"if p["identity_ok"]else"FALSE"})',evidence,p['key']]
        row += [p['presence'].get(f'2026-{m:02}-01') for m in range(1,13)]
        out.append(row)
    return out


def source_rows(sources, confirmations=None):
    confirmations=confirmations or {}
    out=[]
    for i,s in enumerate(sources,SOURCE_ROW):
        approved=confirmations.get(s['factory']+'|'+s['month'],{})
        # No default COMPLETE. Confirmation fields are user-owned, revision-bound.
        row=[s['factory'],serial(s['month']),s['imported'],s['fingerprint'],s['evidence'],approved.get('state',s['state']),approved.get('by',''),approved.get('at',''),approved.get('fingerprint',''),approved.get('evidence','')]
        row += [f'=IF(F{i}="COMPLETE",IF(C{i}<>TRUE,"ERROR",IF(AND(D{i}<>"",D{i}=I{i},G{i}<>"",H{i}<>""),"COMPLETE","PENDING_CONFIRMATION")),F{i})',f'=A{i}&"|"&TEXT(B{i},"yyyy-mm")']
        out.append(row)
    return out


def wrap_revenue_ui(ground, summary_expression, trace_expression):
    """Preserve every existing mode, pagination and filter behavior."""
    cells={}
    dv=None
    for sh in ground['sheets']:
        if sh['properties']['title']!='DOANH_THU':continue
        for d in sh.get('data',[]):
            for ri,row in enumerate(d.get('rowData',[])):
                for ci,c in enumerate(row.get('values',[])):
                    key=(d.get('startRow',0)+ri+1,d.get('startColumn',0)+ci+1)
                    cells[key]=c.get('userEnteredValue',{}).get('formulaValue')
                    if key==(5,2):dv=c.get('dataValidation')
    cache=cells[(15,14)];prefix,tail=cache.split('allData,',1);old,end=tail.rsplit(',VSTACK(HSTACK(ROWS(allData)',1)
    cache=prefix+'allData,IF(B5="Dự báo V2.2 — tháng × nhà máy",'+summary_expression+',IF(B5="Dự báo V2.2 — truy vết",'+trace_expression+','+old+')),VSTACK(HSTACK(ROWS(allData)'+end
    q=[put(7002,15,14,[[cache]])]
    heads={'Dự báo V2.2 — tháng × nhà máy':['Tháng','Nhà máy','DK trước sửa','DK sau sửa','Giảm dự kiến','Phí thực tế','Chưa đối chiếu','NV ngừng dự báo'],
           'Dự báo V2.2 — truy vết':['Mã NV','Ứng viên','Nhà máy','Có tên T9','Có tên T10','Có tên T11','Trạng thái','Dừng từ ngày','Nguồn chứng minh']}
    for col in range(1,13):
        f=cells[(15,col)][1:]
        for mode,labels in heads.items():f=f'IF($B$5="{mode}","{labels[col-1]if col<=len(labels)else""}",{f})'
        q.append(put(7002,15,col,[['='+f]]))
    display=cells[(16,1)]
    display=display.replace('datecols,SWITCH(B5,','datecols,SWITCH(B5,"Dự báo V2.2 — tháng × nhà máy","1","Dự báo V2.2 — truy vết","8",')
    display=display.replace('moneycols,SWITCH(B5,','moneycols,SWITCH(B5,"Dự báo V2.2 — tháng × nhà máy","3,4,5,6,7",')
    q.append(put(7002,16,1,[[display]]))
    dv['condition']['values']=[{'userEnteredValue':m}for m in heads]+dv['condition']['values']
    q.append({'setDataValidation':{'range':{'sheetId':7002,'startRowIndex':4,'endRowIndex':5,'startColumnIndex':1,'endColumnIndex':2},'rule':dv}})
    return q
