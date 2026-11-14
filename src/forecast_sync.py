"""Build native Sheets deployment plans from private, bounded live inputs.

Run: python -m src.forecast_sync --input PRIVATE.json --output PLAN.json
The caller applies the returned native batchUpdate requests to each explicitly
selected production ID, then rereads values. No credentials or worker data are
logged or committed. This module never writes actual attendance/fees/policies.
"""
import argparse
import json
import re
from openpyxl.utils import get_column_letter as col
from .forecast_sheets import *

def build_plan(config):
 people=config['people'];sources=config['sources']
 if not people or len(people)>1997 or any(p['row']!=i+4 for i,p in enumerate(people)):
  raise ValueError('Roster layout/capacity changed; audit before writing')
 if len(sources)>197:raise ValueError('Source registry capacity exceeded')
 if config.get('installed') and 'confirmations' not in config:
  raise ValueError('Read existing source confirmations before refreshing')
 coverage=config['original_coverage_formula']
 ix=0 if config.get('coverage_existing') else 1
 navy={'red':.055,'green':.11,'blue':.21};white={'red':1,'green':1,'blue':1}
 q=[{'addSheet':{'properties':{'sheetId':7950,'title':TAB,'hidden':True,'gridProperties':{'rowCount':2000,'columnCount':56,'frozenRowCount':3,'hideGridlines':True}}}}]
 q.append(put(7950,1,1,[['Revenue Forecast V2.2 — dates are exclusive; no actual-fee writes']]))
 heads=['EpisodeKey','EmployeeID','Candidate','Factory','Group','JoinDate','LastConfirmedAttendanceMonth','NextMonthSourceStatus','PresentInNextMonth','OfficialTerminationDate','InferredForecastStopDate','FeeExpiryExclusive','EffectiveForecastStopDate','ForecastEmploymentStatus','EvidenceSource','LastEvaluatedAt','IdentityVerified','PresenceEvidence','IdentityEpisodeAnchor']+[f'Present_{m:02}_2026'for m in range(1,13)]
 q.append(put(7950,3,1,[heads]))
 trace=trace_rows(people,config['evaluated_at'])
 q.append(put(7950,4,1,[trace[0][:16]]))
 q.append({'autoFill':{'sourceAndDestination':{'source':{'sheetId':7950,'startRowIndex':3,'endRowIndex':4,'startColumnIndex':0,'endColumnIndex':16},'dimension':'ROWS','fillLength':len(people)-1},'useAlternateSeries':False}})
 q.append(put(7950,4,17,[r[16:]for r in trace]))
 original=config['original_calendar_formula']
 if 'FORECAST_V22!$K' in original:raise ValueError('Use archived pre-V2.2 calendar formula for the counterfactual baseline')
 baseline=local_baseline(original)
 q.append(put(7950,3,39,[['Before_units','Before_hours','Before_rate','Before_forecast','Before_warning','Before_Sep','Before_Oct','Before_Nov','Before_Dec']]))
 q.append(put(7950,4,39,[[baseline]]))
 q.append({'updateCells':{'start':{'sheetId':7950,'rowIndex':3,'columnIndex':38},'rows':[{'values':[{'note':original}]}],'fields':'note'}})
 q.append({'updateCells':{'start':{'sheetId':7950,'rowIndex':1,'columnIndex':0},'rows':[{'values':[{'note':coverage}]}],'fields':'note'}})
 q.append({'autoFill':{'sourceAndDestination':{'source':{'sheetId':7950,'startRowIndex':3,'endRowIndex':4,'startColumnIndex':38,'endColumnIndex':39},'dimension':'ROWS','fillLength':1996},'useAlternateSeries':False}})
 # Preserve original data-quality gates. Cap both native calendar and comparable-coverage engines.
 q.append(put(7503,4,7,[[cap_calendar_formula(original,4)]]))
 q.append({'autoFill':{'sourceAndDestination':{'source':{'sheetId':7503,'startRowIndex':3,'endRowIndex':4,'startColumnIndex':6,'endColumnIndex':7},'dimension':'ROWS','fillLength':1996},'useAlternateSeries':False}})
 if ix==1:q.append({'updateSheetProperties':{'properties':{'sheetId':7503,'gridProperties':{'columnCount':68}},'fields':'gridProperties.columnCount'}})
 q.append(put(7503,4,24,[[cap_calendar_formula(coverage,4)]]))
 q.append({'autoFill':{'sourceAndDestination':{'source':{'sheetId':7503,'startRowIndex':3,'endRowIndex':4,'startColumnIndex':23,'endColumnIndex':24},'dimension':'ROWS','fillLength':1996},'useAlternateSeries':False}})
 q.append(put(7002,1001,1,[['V2.2 | XÁC NHẬN BẢNG CÔNG ĐẦY ĐỦ — CHỈ COMPLETE MỚI ĐƯỢC SUY LUẬN']]))
 q.append(put(7002,1002,1,[['Chọn trạng thái tại F; nhập người xác nhận G, thời điểm H, sao chép mã nguồn D vào I, ghi căn cứ J. Khi file nguồn thay đổi phải xác nhận lại. “Đã đọc” không đồng nghĩa đầy đủ.']]))
 q.append(put(7002,1003,1,[['Nhà máy','Tháng','Import OK','Mã nguồn hiện tại','Nguồn công','Xác nhận nguồn','Người xác nhận','Thời điểm','Mã nguồn đã duyệt','Căn cứ xác nhận','Trạng thái áp dụng','Khóa kiểm tra']]))
 confirmations=config.get('confirmations',{})
 q.append(put(7002,1004,1,source_rows(sources,confirmations)))
 q.append({'setDataValidation':{'range':{'sheetId':7002,'startRowIndex':1003,'endRowIndex':1003+len(sources),'startColumnIndex':5,'endColumnIndex':6},'rule':{'condition':{'type':'ONE_OF_LIST','values':[{'userEnteredValue':x}for x in ['COMPLETE','PARTIAL','MISSING','ERROR','PENDING_CONFIRMATION']]},'strict':True,'showCustomUi':True}}})
 q.append({'repeatCell':{'range':{'sheetId':7002,'startRowIndex':1003,'endRowIndex':1003+len(sources),'startColumnIndex':1,'endColumnIndex':2},'cell':{'userEnteredFormat':{'numberFormat':{'type':'DATE','pattern':'MM/yyyy'}}},'fields':'userEnteredFormat.numberFormat'}})
 # Shared filtered monthly/factory summary. Blank costs remain blank when unverified.
 summary=[]
 for m in [9,10,11,12]:
  for factory in sorted({p['factory']for p in people}):
   r=4+len(summary);before=col(43+m-9+1) # AR = 44 in Sep
   after=col(12+m-9);pending=col(56+m)
   base=f'FORECAST_V22!${before}$4:${before}$2000';af=f'QL_DU_KIEN!${after}$4:${after}$2000'
   crit=f'QL_DU_KIEN!$C$4:$C$2000,B{r},QL_DU_KIEN!$F$4:$F$2000,IF(TONG_QUAN!$E$5="Tất cả","*",TONG_QUAN!$E$5)'
   mask=f'(QL_DU_KIEN!$C$4:$C$2000=B{r})*IF(TONG_QUAN!$E$5="Tất cả",QL_DU_KIEN!$F$4:$F$2000<>"",QL_DU_KIEN!$F$4:$F$2000=TONG_QUAN!$E$5)'
   b=f'=IF(IFERROR(COUNT(FILTER({base},{mask})),0)=0,"",SUMIFS({base},{crit}))'
   a=f'=IF(IFERROR(COUNT(FILTER({af},{mask})),0)=0,"",SUMIFS({af},{crit}))'
   actualmask=f'(QL_THUC_TE!$C$4:$C$20000=B{r})*(QL_THUC_TE!$A$4:$A$20000>=MAX(A{r},TONG_QUAN!$B$6))*(QL_THUC_TE!$B$4:$B$20000<=MIN(EOMONTH(A{r},0),TONG_QUAN!$E$6))*(QL_THUC_TE!$L$4:$L$20000="VALID")*IF(TONG_QUAN!$E$5="Tất cả",QL_THUC_TE!$D$4:$D$20000<>"",QL_THUC_TE!$D$4:$D$20000=TONG_QUAN!$E$5)'
   actual=f'=IFERROR(SUM(FILTER(QL_THUC_TE!$K$4:$K$20000,{actualmask})),"")'
   pend=f'=IF(D{r}="","",SUMIFS(QL_DU_KIEN!${pending}$4:${pending}$2000,{crit}))'
   stopped=f'=SUMPRODUCT(N($D$4:$D$2000=B{r}),N(ISNUMBER($K$4:$K$2000)),N($K$4:$K$2000>=A{r}),N($K$4:$K$2000<=MIN(EOMONTH(A{r},0),TONG_QUAN!$E$6)),N($F$4:$F$2000<=MIN(EOMONTH(A{r},0),TONG_QUAN!$E$6)),IF(TONG_QUAN!$E$5="Tất cả",N($E$4:$E$2000<>""),N($E$4:$E$2000=TONG_QUAN!$E$5)))'
   # Summary hosted AW:BD; all same-row references need that coordinate system.
   vals=[serial(f'2026-{m:02}-01'),factory,b,a,f'=IF(AND(ISNUMBER(C{r}),ISNUMBER(D{r})),C{r}-D{r},"")',actual,pend,stopped]
   for j in range(2,8):
    vals[j]=re.sub(r'(?<![A-Z!$])\b([A-H])'+str(r)+r'\b',lambda x:col(48+ord(x[1])-64)+str(r),vals[j])
   summary.append(vals)
 q.append(put(7950,3,49,[['Month','Factory','Before','After','Reduction','Actual','Unreconciled','Stopped']]))
 q.append(put(7950,4,49,summary))
 summaryexpr='FILTER(FORECAST_V22!AW4:BD51,FORECAST_V22!AW4:AW51>=DATE(YEAR(TONG_QUAN!B6),MONTH(TONG_QUAN!B6),1),FORECAST_V22!AW4:AW51<=TONG_QUAN!E6,IF(AND(TONG_QUAN!E5="LĐPT",TONG_QUAN!B5<>"Tất cả"),FORECAST_V22!AX4:AX51=TONG_QUAN!B5,FORECAST_V22!AX4:AX51<>""))'
 trace='FILTER(HSTACK(FORECAST_V22!B4:D2000,IF(ISLOGICAL(FORECAST_V22!AB4:AD2000),IF(FORECAST_V22!AB4:AD2000,"Có tên","Vắng tên"),"Chưa xác minh"),MAP(FORECAST_V22!N4:N2000,LAMBDA(st,SWITCH(st,"IDENTITY_REVIEW","Cần đối soát định danh","REJOIN_REVIEW","Xuất hiện lại — kiểm tra đợt","INFERRED_STOP","Dừng dự báo theo bảng công","OFFICIAL_STOP","Có ngày nghỉ chính thức","PRESENT","Có tên trong bảng công","NO_ATTENDANCE_EVIDENCE","Chưa có công khớp",st))),FORECAST_V22!M4:M2000,IF(FORECAST_V22!O4:O2000="","",TRIM(REGEXEXTRACT(FORECAST_V22!O4:O2000,"^[^|]+")))),FORECAST_V22!A4:A2000<>"",FORECAST_V22!F4:F2000<=TONG_QUAN!E6,IF(AND(TONG_QUAN!E5="LĐPT",TONG_QUAN!B5<>"Tất cả"),FORECAST_V22!D4:D2000=TONG_QUAN!B5,FORECAST_V22!D4:D2000<>""),IF(TONG_QUAN!E5="Tất cả",FORECAST_V22!E4:E2000<>"",FORECAST_V22!E4:E2000=TONG_QUAN!E5),IF(DOANH_THU!E5="Tất cả",FORECAST_V22!C4:C2000<>"",ISNUMBER(SEARCH(DOANH_THU!E5,FORECAST_V22!C4:C2000))))'
 q+=wrap_revenue_ui(config['ui_ground'],summaryexpr,trace) if not config.get('installed') else []
 if not config.get('installed'):q.append(put(7002,5,2,[['Dự báo V2.2 — tháng × nhà máy']]))
 q.append(put(7002,14,1,[['V2.2: chọn bảng tháng × nhà máy hoặc truy vết. Ngày dừng là mốc loại trừ; không sửa ngày nghỉ chính thức. Chỉ nguồn COMPLETE mới suy luận.']]))
 q.append(put(7002,13,9,[[f'=HYPERLINK("#gid=7002&range=A1001:L1065","XÁC NHẬN NGUỒN V2.2 →")']]))
 for rr in [1001,1003]:q.append({'repeatCell':{'range':{'sheetId':7002,'startRowIndex':rr-1,'endRowIndex':rr,'startColumnIndex':0,'endColumnIndex':12},'cell':{'userEnteredFormat':{'backgroundColor':navy,'textFormat':{'bold':True,'foregroundColor':white},'wrapStrategy':'WRAP'}},'fields':'userEnteredFormat'}})
 for rr in ([] if config.get('installed') else [1001,1002]):q.append({'mergeCells':{'range':{'sheetId':7002,'startRowIndex':rr-1,'endRowIndex':rr,'startColumnIndex':0,'endColumnIndex':12},'mergeType':'MERGE_ALL'}})
 q.append({'repeatCell':{'range':{'sheetId':7002,'startRowIndex':1003,'endRowIndex':1003+len(sources),'startColumnIndex':5,'endColumnIndex':10},'cell':{'userEnteredFormat':{'backgroundColor':{'red':1,'green':.96,'blue':.83}}},'fields':'userEnteredFormat.backgroundColor'}})
 q.append({'repeatCell':{'range':{'sheetId':7002,'startRowIndex':1003,'endRowIndex':1003+len(sources),'startColumnIndex':0,'endColumnIndex':12},'cell':{'userEnteredFormat':{'wrapStrategy':'CLIP'}},'fields':'userEnteredFormat.wrapStrategy'}})
 q.append({'updateDimensionProperties':{'range':{'sheetId':7002,'dimension':'ROWS','startIndex':1000,'endIndex':1003+len(sources)},'properties':{'pixelSize':42},'fields':'pixelSize'}})
 # Warning-only protections preserve existing sync credentials and write access.
 for sid,r0,r1,c0,c1 in ([] if config.get('installed') else [(7950,0,2000,0,56),(7503,3,2000,6,15),(7503,3,2000,23,68),(7002,1003,1063,10,12)]):
  q.append({'addProtectedRange':{'protectedRange':{'range':{'sheetId':sid,'startRowIndex':r0,'endRowIndex':r1,'startColumnIndex':c0,'endColumnIndex':c1},'description':'V2.2 công thức dự báo — chỉnh qua pipeline đã kiểm thử','warningOnly':True}}})
 if config.get("installed"): q=[x for x in q if "addSheet" not in x]
 return q

def main():
 parser=argparse.ArgumentParser()
 parser.add_argument('--input',required=True)
 parser.add_argument('--output',required=True)
 args=parser.parse_args()
 with open(args.input) as handle: config=json.load(handle)
 with open(args.output,'w') as handle: json.dump(build_plan(config),handle,ensure_ascii=False)

if __name__=='__main__':main()
