"""One controlled Drive read per source file; XLSX and all native tabs.

Parser layouts are supplied by the verified private business adapters. A full
byte/tab scan is not semantic validation and never grants COMPLETE approval.
"""
from __future__ import annotations
import hashlib
import io
import json
import math
from datetime import date, datetime
from urllib.parse import quote
import openpyxl
from .sync_runtime import SyncBlocked, digest, request

SHEETS = 'https://sheets.googleapis.com/v4/spreadsheets/'
DRIVE = 'https://www.googleapis.com/drive/v3/files'


def scalar(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        raise SyncBlocked('NONFINITE_SOURCE_VALUE')
    if isinstance(value,float)and value.is_integer():return int(value)
    return value


class GoogleTransport:
    def __init__(self, session, state=None):
        self.session = session
        self.state = state

    @classmethod
    def from_env(cls, state=None):
        import os
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2.service_account import Credentials
        raw = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON')
        credential_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
        if not raw and not credential_path:
            raise SyncBlocked('GOOGLE_SERVICE_ACCOUNT_JSON_MISSING')
        try:
            scopes = [
                'https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive.readonly']
            if raw:
                cred = Credentials.from_service_account_info(json.loads(raw), scopes=scopes)
            else:
                cred = Credentials.from_service_account_file(credential_path, scopes=scopes)
        except (OSError, ValueError, KeyError):
            raise SyncBlocked('GOOGLE_CREDENTIAL_INVALID') from None
        return cls(AuthorizedSession(cred), state)

    def json(self, method, url, **kwargs):
        return request(self.session, method, url, **kwargs).json()

    def file_info(self, file_id):
        return self.json('GET', DRIVE + '/' + quote(file_id, safe=''), params={
            'fields': 'id,name,mimeType,modifiedTime,version,trashed,capabilities(canEdit,canDownload)', 'supportsAllDrives': 'true'})

    def list_folder(self, folder):
        out, token, seen = [], None, set()
        while True:
            data = self.json('GET', DRIVE, params={
                'q': "'" + folder.replace("'", "\\'") + "' in parents and trashed=false",
                'fields': 'nextPageToken,incompleteSearch,files(id,name,mimeType)',
                'pageSize': 1000, 'pageToken': token, 'supportsAllDrives': 'true',
                'includeItemsFromAllDrives': 'true'})
            if data.get('incompleteSearch'):
                raise SyncBlocked('DRIVE_INCOMPLETE_LISTING')
            out.extend(data.get('files', []))
            token = data.get('nextPageToken')
            if not token:
                return out
            if token in seen:
                raise SyncBlocked('DRIVE_CURSOR_LOOP')
            seen.add(token)

    def snapshot(self, spreadsheet_id):
        meta = self.json('GET', SHEETS + spreadsheet_id, params={'fields': 'spreadsheetId,sheets.properties'})
        cells = {}; ranges = []; budget = 0
        def collect():
            if not ranges: return
            block = self.json('GET', SHEETS + spreadsheet_id, params={
                'ranges': list(ranges), 'includeGridData': 'true',
                'fields': 'sheets(properties(sheetId),data(startRow,startColumn,rowData(values(userEnteredValue,effectiveValue,note))))'})
            known = {s['properties']['sheetId'] for s in meta['sheets']}
            for sheet in block.get('sheets', []):
                sid = sheet.get('properties', {}).get('sheetId')
                if sid not in known: raise SyncBlocked('NATIVE_SNAPSHOT_SHEET_ID_UNVERIFIED')
                for data in sheet.get('data', []):
                    for i, row in enumerate(data.get('rowData', [])):
                        for j, cell in enumerate(row.get('values', [])):
                            if cell:
                                key = f"{sid}:{data.get('startRow',0)+i}:{data.get('startColumn',0)+j}"
                                cells[key] = cell
        # Every native range remains <=50,000 cells. Group up to 200,000
        # requested cells per call to avoid one quota-consuming call per tab.
        # All effective errors, hidden tabs and authored values are retained.
        for sh in meta['sheets']:
            p = sh['properties']; grid = p['gridProperties']; title = p['title'].replace("'", "''")
            width = grid['columnCount']; step = max(1, 50000 // width)
            for start in range(0, grid['rowCount'], step):
                from openpyxl.utils import get_column_letter
                end = min(start + step, grid['rowCount'])
                size = (end-start)*width
                if ranges and (budget+size>200000 or len(ranges)>=8):
                    collect(); ranges=[]; budget=0
                ranges.append(f"'{title}'!A{start+1}:{get_column_letter(width)}{end}")
                budget += size
        collect()
        return {'id': spreadsheet_id, 'sheets': [s['properties'] for s in meta['sheets']], 'cells': cells}

    def write(self, spreadsheet_id, requests):
        self.json('POST', SHEETS + spreadsheet_id + ':batchUpdate', json={'requests': requests})

    def read_cells(self, spreadsheet_id, snapshot, keys):
        """Bound changed-table readback; a full formula scan still runs at end."""
        from openpyxl.utils import get_column_letter
        boxes={}
        for k in keys:
            sid,r,c=map(int,k.split(':'))
            old=boxes.setdefault(sid,[r,r,c,c])
            old[0]=min(old[0],r);old[1]=max(old[1],r);old[2]=min(old[2],c);old[3]=max(old[3],c)
        cells={k:{} for k in keys}
        for sid,(r0,r1,c0,c1) in boxes.items():
            title=next(s['title'] for s in snapshot['sheets'] if s['sheetId']==sid).replace("'","''")
            step=max(1,50000//(c1-c0+1))
            for lo in range(r0,r1+1,step):
                hi=min(r1+1,lo+step)
                data=self.json('GET',SHEETS+spreadsheet_id,params={
                    'ranges':f"'{title}'!{get_column_letter(c0+1)}{lo+1}:{get_column_letter(c1+1)}{hi}",
                    'includeGridData':'true','fields':'sheets(data(startRow,startColumn,rowData(values(userEnteredValue,effectiveValue,note))))'})
                for sh in data.get('sheets',[]):
                    for block in sh.get('data',[]):
                        for i,row in enumerate(block.get('rowData',[])):
                            for j,cell in enumerate(row.get('values',[])):
                                k=f"{sid}:{block.get('startRow',0)+i}:{block.get('startColumn',0)+j}"
                                if k in cells:cells[k]=cell
        return cells

    def source(self, file_id):
        before = self.file_info(file_id)
        if before.get('trashed'):
            raise SyncBlocked('SOURCE_TRASHED')
        mime = before['mimeType']; blob_path = None
        if mime == 'application/vnd.google-apps.spreadsheet':
            native = self.snapshot(file_id)
            tabs = []
            for sh in native['sheets']:
                rows, errors = {}, []
                for key, cell in native['cells'].items():
                    sid, r, c = map(int, key.split(':'))
                    if sid != sh['sheetId']:
                        continue
                    value = cell.get('effectiveValue', {})
                    if 'errorValue' in value:
                        errors.append({'row':r,'column':c,'type':value['errorValue'].get('type','UNKNOWN')})
                        continue
                    rows.setdefault(r, {})[c] = scalar(next(iter(value.values()), None))
                tab={'id': sh['sheetId'], 'name': sh['title'], 'hidden': sh.get('hidden', False),
                     'rows': [[r, sorted(cols.items())] for r, cols in sorted(rows.items())]}
                if errors:tab['formula_errors']=errors
                tabs.append(tab)
            fingerprint = digest(tabs)
        elif mime == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':
            raw = request(self.session, 'GET', DRIVE + '/' + quote(file_id, safe=''),
                          params={'alt': 'media', 'supportsAllDrives': 'true'}).content
            fingerprint = hashlib.sha256(raw).hexdigest()
            if self.state is not None:
                blob_path = str(self.state.save_blob(fingerprint + '.xlsx', raw))
            book = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
            tabs = [{'id': s.title, 'name': s.title, 'hidden': s.sheet_state != 'visible',
                     'rows': [[i, [[j, scalar(v)] for j, v in enumerate(row) if v is not None]]
                              for i, row in enumerate(s.values) if any(v is not None for v in row)]}
                    for s in book]
            book.close()
        else:
            raise SyncBlocked('UNSUPPORTED_SOURCE_MIME')
        after = self.file_info(file_id)
        if any(before.get(k) != after.get(k) for k in ('version', 'modifiedTime', 'mimeType')):
            raise SyncBlocked('SOURCE_CHANGED_DURING_READ')
        result = {'file_id': file_id, 'fingerprint': fingerprint, 'metadata': before, 'tabs': tabs}
        if blob_path: result['blob_path'] = blob_path
        return result


def collect_once(transport, folders, files):
    """Deduplicate roots/files, traverse folders, retain errors as explicit state."""
    ids, seen_folders, pending = set(files), set(), list(folders)
    errors = []
    while pending:
        folder = pending.pop()
        if folder in seen_folders:
            continue
        seen_folders.add(folder)
        try:
            for item in transport.list_folder(folder):
                if item['mimeType'] == 'application/vnd.google-apps.folder':
                    pending.append(item['id'])
                else:
                    ids.add(item['id'])
        except SyncBlocked as exc:
            errors.append({'source': digest(folder), 'reason': str(exc)})
    sources = []
    for file_id in sorted(ids):
        try:
            sources.append(transport.source(file_id))
        except Exception as exc:
            reason = str(exc) if isinstance(exc, SyncBlocked) else 'SOURCE_PARSE_FAILED'
            errors.append({'source': digest(file_id), 'reason': reason})
    return {'sources': sources, 'errors': errors, 'listed_files': len(ids),
            'parsed_files': len(sources), 'listed_tabs': sum(len(s['tabs']) for s in sources),
            'transport_scan_complete': bool(ids) and not errors and len(sources) == len(ids)}
