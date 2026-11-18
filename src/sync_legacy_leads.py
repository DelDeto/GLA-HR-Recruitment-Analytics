"""Retain nonstandard Sales rows for review; never invent intake/group facts."""
import unicodedata,re
from .sync_source_audit import phone


def label(value):
    text=unicodedata.normalize('NFD',str(value or'').upper().replace('Đ','D'))
    return ''.join(c for c in text if c.isalnum()and not unicodedata.combining(c))


def review(sources,options,leads,date_parser,as_of,factory_parser=None):
    known={(r['date'],r.get('phone'))for r in leads if r.get('phone')}
    rows=[];receipts=[];counts={'already_counted':0,'outside_period':0,'unknown_date':0,'needs_review':0}
    for source in sources:
        if source['file_id']not in {options['source_roles'].get(k)for k in ('sale_le','sale_thao')}:continue
        for tab in source['tabs']:
            spec=options.get('tab_contracts',{}).get(source['file_id'],{}).get(str(tab['id']),{})
            if spec.get('parser')!='LEGACY_SALES_AUDIT':continue
            header=dict(next((cs for r,cs in tab['rows']if r==spec['header_row']),[]))
            def col(names):return next((c for c,x in header.items()if label(x)in names),None)
            dc=col({'DATE','NGAY','THOIGIAN'});nc=col({'NAME','FULLNAME','FACEBOOKNAME','TENFB','TEN','HOVATEN'});pc=col({'CONTACT','SDT','SODIENTHOAI'})
            for row,values in tab['rows']:
                if row<=spec['header_row']:continue
                values=dict(values);pn=phone(values.get(pc));name=values.get(nc)
                if not pn and not name:continue
                d=date_parser(values.get(dc))if dc is not None else None;day=d.isoformat()if d else None
                if day and not '2026-01-01'<=day<=as_of:counts['outside_period']+=1;continue
                if day and pn and options.get('legacy_intake_confirmed'):
                    text=' '.join(str(x)for x in values.values()).upper()
                    ascii_text=''.join(c for c in unicodedata.normalize('NFD',text)if not unicodedata.combining(c))
                    group=('IDL SV'if re.search(r'\bTTS\b|\bIDL[ -]*SV\b|THUC TAP|SINH VIEN',ascii_text)
                        else'IDL Fresher'if'FRESHER'in ascii_text else'IDL'if re.search(r'\bIDL\b',ascii_text)
                        else options.get('legacy_default_group','CHƯA PHÂN NHÓM'))
                    fac=factory_parser(tab['name'])if factory_parser else'CHƯA GÁN'
                    receipts.append({'date':day,'group':group,'factory':fac,'phone':pn,'identity':pn,'name':str(name or''),
                        'source':f"https://docs.google.com/spreadsheets/d/{source['file_id']}/edit#gid={tab['id']}&range=A{row+1}",
                        'method':'GLA xác nhận: tab số lạnh/nóng/chăm lại là Lead mới; khử trùng ngày/nhóm/định danh/nhà máy LĐPT'})
                    if(day,pn)in known:counts['already_counted']+=1
                    continue
                if day and pn and(day,pn)in known:counts['already_counted']+=1;continue
                state='unknown_date'if not day else'needs_review';counts[state]+=1
                rows.append({'file_id':source['file_id'],'tab_id':tab['id'],'row':row+1,
                    'date':day,'phone':pn or None,'name':name,'state':state,
                    'reason':'NO_VERIFIED_INTAKE_GROUP_OR_BASELINE_MATCH','included_in_lead_count':False})
    return {'counts':counts,'quarantine':rows,'receipts':receipts}


def merge_receipts(leads,receipts):
    """Preserve factory identity for LĐPT; student classification wins per day."""
    students={(r['date'],r['phone'])for r in leads+receipts if r['group']=='IDL SV'and r.get('phone')}
    merged={};duplicates=0
    for r in leads+receipts:
        if(r['date'],r.get('phone'))in students and r['group']!='IDL SV':continue
        key=(r['date'],r['group'],r['identity'],r['factory']if r['group']=='LĐPT'else'')
        if key in merged:
            duplicates+=1;continue
        merged[key]=r
    return list(merged.values()),duplicates
