"""Read full vendor rosters for presence, without changing fee calculations.

No filter on positive hours or fee eligibility is permitted here. Unknown
schemas/years fail closed and cannot produce a COMPLETE month.
"""
from __future__ import annotations
import calendar
import hashlib
import re
import unicodedata
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
import openpyxl


def norm(value):
    text = unicodedata.normalize('NFD', str(value or '')).replace('đ', 'd').replace('Đ', 'D')
    return re.sub(r'\s+', ' ', ''.join(c for c in text if not unicodedata.combining(c))).strip().upper()


def code(value):
    s = norm(value).replace(' ', '')
    return s if re.fullmatch(r'[A-Z]+\d{3,}', s) else ''


def dates(value):
    out = set()
    if isinstance(value, datetime): value = value.date()
    if isinstance(value, date):
        out.add(value)
        if value.day <= 12 and value.day != value.month:
            out.add(date(value.year, value.day, value.month))
        return out
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if 20000101 <= value <= 20991231:
            return {datetime.strptime(str(int(value)), '%Y%m%d').date()}
        if 40000 < value < 70000:
            return dates(date(1899, 12, 30) + timedelta(days=int(value)))
    for fmt in ('%Y-%m-%d', '%Y-%m-%d %H:%M:%S', '%d/%m/%Y', '%m/%d/%Y', '%d/%m/%y', '%m/%d/%y'):
        try: out.add(datetime.strptime(str(value or '').strip(), fmt).date())
        except ValueError: pass
    return out


def exact_date(value):
    if isinstance(value, datetime): return value.date()
    if isinstance(value, date): return value
    if isinstance(value, (int, float)):
        if 20000101 <= value <= 20991231:
            return datetime.strptime(str(int(value)), '%Y%m%d').date()
        if 40000 < value < 70000: return date(1899, 12, 30) + timedelta(days=int(value))
    for fmt in ('%Y-%m-%d', '%Y-%m-%d %H:%M:%S', '%m/%d/%Y', '%m/%d/%y'):
        try: return datetime.strptime(str(value or '').strip(), fmt).date()
        except ValueError: pass
    return None


def consecutive(raw):
    choices = [dates(x) for x in raw]
    paths = []
    for first in choices[0] if choices else []:
        seq = [first + timedelta(days=i) for i in range(len(raw))]
        if all(d in options for d, options in zip(seq, choices)): paths.append(seq)
    if len(paths) != 1: raise ValueError('Ambiguous date sequence')
    return paths[0]


def read_sources(files, as_of):
    records, manifests, errors = [], [], []
    for file in files:
        path = Path(file['path'])
        fingerprint = hashlib.sha256(path.read_bytes()).hexdigest()
        factory = next((f for token, f in [('PEGATRON','Pegatron'),('FUKANG','Fukang'),
                       ('FEVC','FEVC'),('USI','USI'),('LGE','LG Electronic'),('QUANTA','Quanta')]
                       if token in norm(file['name'])), None)
        if not factory: raise ValueError('Unmapped factory file')
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        for sh in wb:
            rows = list(sh.values)
            try:
                if factory == 'Pegatron':
                    h = {norm(v):i for i,v in enumerate(rows[0]) if v is not None}
                    ic = next(h[k] for k in ('MA NHAN','MA NHAN VIEN') if k in h)
                    nc = 4 if 'GIO CONG' in h or 'NGUON' in h else 3
                    dc = h['NGAY']; jc = None
                    entries = [(i,r,[exact_date(r[dc])]) for i,r in enumerate(rows[1:],2)]
                elif factory == 'USI':
                    cols = [i for i,v in enumerate(rows[0]) if i >= 8 and dates(v)]
                    if not cols or cols != list(range(cols[0],cols[-1]+1)): raise ValueError('Shifted dates')
                    ds = consecutive([rows[0][i] for i in cols])
                    ic,nc,jc = 1,2,4
                    # Entire row belongs to every month in the verified header,
                    # even when all the employee's hours are blank or zero.
                    entries = [(i,r,ds) for i,r in enumerate(rows[1:],2)]
                elif factory == 'Quanta':
                    di = next((i for i,r in enumerate(rows[:6]) if sum(isinstance(v,(int,float)) and 20000101<=v<=20991231 for v in r)>10),None)
                    if di is None:
                        if '202511' in str(rows[:3]): continue
                        raise ValueError('Missing YYYYMMDD header')
                    ds = [exact_date(v) for v in rows[di] if isinstance(v,(int,float)) and 20000101<=v<=20991231]
                    if sh.title.strip() == 'tháng 1': ic,nc,jc=0,1,3
                    else:
                        h=rows[di-1];ic=h.index('工号');nc=h.index('姓名');jc=next(i for i,v in enumerate(h) if norm(v)=='NGAY VAO')
                    entries=[(i,r,ds)for i,r in enumerate(rows[di+1:],di+2)]
                else:
                    ic,nc,jc = (1,2,3) if factory=='Fukang' else (2,3,5) if factory=='FEVC' else (0,1,5)
                    mm=re.search(r'(?:T|THANG)\s*(\d{1,2})',norm(sh.title))
                    if not mm: raise ValueError('Missing period')
                    month=int(mm[1]);years={int(x) for x in re.findall(r'\b20\d{2}\b',sh.title)}
                    if not years:
                        joins=[exact_date(r[jc]) for r in rows if len(r)>jc and exact_date(r[jc])]
                        possible=[y for y in range(as_of.year-1,as_of.year+1) if joins and date(y,month,calendar.monthrange(y,month)[1])>=max(joins) and date(y,month,1)<=as_of]
                        years=set(possible)
                    if len(years)!=1: raise ValueError('Unverified period year')
                    ds=[date(next(iter(years)),month,1)]
                    entries=[(i,r,ds)for i,r in enumerate(rows,1)]
                months=set(); count=0
                for ri,r,ds in entries:
                    valid=[d.replace(day=1) for d in ds if d and d.year==as_of.year and d<=as_of]
                    months.update(valid)
                    if len(r)<=max(ic,nc) or not code(r[ic]) or not str(r[nc] or '').strip():continue
                    for month in set(valid):
                        records.append(dict(factory=factory,month=month.isoformat(),id=code(r[ic]),name=str(r[nc]).strip(),
                            join_choices=sorted(d.isoformat() for d in dates(r[jc])) if jc is not None else [],
                            source=f"https://drive.google.com/file/d/{file['id']}/view#sheet={sh.title}&row={ri}",fingerprint=fingerprint))
                        count+=1
                for month in months:
                    manifests.append(dict(factory=factory,month=month.isoformat(),file_id=file['id'],sheet=sh.title,fingerprint=fingerprint,imported=True,rows=count))
            except (ValueError,KeyError,StopIteration,IndexError) as exc:
                errors.append(dict(factory=factory,file_id=file['id'],sheet=sh.title,error=str(exc)))
        wb.close()
    # Reimport and duplicate daily attendance records cannot multiply presence.
    unique={tuple((r[k] if not isinstance(r[k],list) else tuple(r[k])) for k in ('factory','month','id','name','join_choices','source')):r for r in records}
    return list(unique.values()), manifests, errors


def match_presence(roster, records, manifests):
    """Resolve only unique ID/episode or evidenced name/join matches.

    Missing roster IDs require an exact unique name+join source match and a
    unique source ID. Potential homonyms block inference instead of absence.
    """
    by_key=defaultdict(list)
    for p in roster: by_key[p['key']].append(p)
    resolved={}; issues=defaultdict(set); evidence=defaultdict(set); anchored=defaultdict(set)
    for r in records:
        by_id=[p for p in roster if p['factory']==r['factory'] and p['id'] and p['id']==r['id']]
        hits=by_id
        if len(hits)>1: hits=[p for p in hits if p['join'] in r['join_choices']]
        if not by_id:
            hits=[p for p in roster if p['factory']==r['factory'] and norm(p['name'])==norm(r['name']) and p['join'] in r['join_choices']]
        if len(hits)==1 and norm(hits[0]['name'])==norm(r['name']):
            p=hits[0]
            if r['month'][:7] < p['join'][:7]:
                continue
            resolved[(p['key'],r['month'])]=True;anchored[p['key']].add(r['id']);evidence[(p['key'],r['month'])].add(r['source'])
        else:
            potential=by_id or [p for p in roster if p['factory']==r['factory'] and norm(p['name'])==norm(r['name'])]
            for p in potential: issues[p['key']].add(r['month'])
    available={(m['factory'],m['month'])for m in manifests if m['imported']}
    output=[]
    for p in roster:
        unique_id=bool(p['id']) and len({q['key']for q in roster if q['factory']==p['factory'] and q['id']==p['id']})==1
        identity_ok=(unique_id or len(anchored[p['key']])==1) and len(by_key[p['key']])==1 and not issues[p['key']]
        presence={}
        for month in sorted({m for f,m in available if f==p['factory']}):
            presence[month]=True if resolved.get((p['key'],month)) else False if identity_ok else None
        output.append(dict(**p,identity_ok=identity_ok,presence=presence,evidence={m:' | '.join(sorted(v))for (key,m),v in evidence.items()if key==p['key']}))
    return output
