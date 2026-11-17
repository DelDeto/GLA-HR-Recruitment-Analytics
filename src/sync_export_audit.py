"""Read-only audit of a native Sheets XLSX export; never use it for writing.

Exports cannot certify Google-specific validation/chips or writer credentials.
The runtime writer always uses bounded native CellData readback instead.
"""
import posixpath
import zipfile
import xml.etree.ElementTree as ET
from openpyxl.utils.cell import coordinate_to_tuple
from .sync_runtime import SyncBlocked

N={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
REL='{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'


def read_export(path, metadata):
    z=zipfile.ZipFile(path)
    strings=[]
    if 'xl/sharedStrings.xml' in z.namelist():
        strings=[''.join(n.itertext())for n in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('s:si',N)]
    rel={r.get('Id'):posixpath.normpath('xl/'+r.get('Target')).lstrip('/')
         for r in ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))}
    props={p['title']:p for p in metadata['sheets']}
    cells={}
    for tab in ET.fromstring(z.read('xl/workbook.xml')).findall('s:sheets/s:sheet',N):
        title=tab.get('name')
        if title not in props:raise SyncBlocked('EXPORT_METADATA_TAB_MISMATCH')
        sid=props[title]['sheetId']
        root=ET.fromstring(z.read(rel[tab.get(REL)]))
        for c in root.findall('s:sheetData/s:row/s:c',N):
            row,col=coordinate_to_tuple(c.get('r'));kind=c.get('t');v=c.find('s:v',N);v=v.text if v is not None else None
            if kind=='s' and v is not None:v=strings[int(v)]
            elif kind=='inlineStr':v=''.join(c.find('s:is',N).itertext())
            elif kind=='b':v=v=='1'
            elif kind not in ('str','e') and v is not None:
                try:v=float(v);v=int(v)if v.is_integer()else v
                except ValueError:pass
            data={};f=c.find('s:f',N)
            if f is not None and f.text is not None:
                # Google/Excel function-prefix adaptation is an export limitation.
                data['userEnteredValue']={'formulaValue':'='+f.text}
            elif v is not None and kind!='e':
                k='boolValue'if isinstance(v,bool)else'numberValue'if isinstance(v,(int,float))else'stringValue'
                data['userEnteredValue']={k:v}
            if kind=='e':data['effectiveValue']={'errorValue':{'type':v}}
            elif v is not None:
                k='boolValue'if isinstance(v,bool)else'numberValue'if isinstance(v,(int,float))else'stringValue'
                data['effectiveValue']={k:v}
            if data:cells[f'{sid}:{row-1}:{col-1}']=data
    return {'id':metadata['id'],'sheets':metadata['sheets'],'cells':cells}
