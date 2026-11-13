"""Read-only direct Meta recheck; all business results encrypted before artifact upload."""
import argparse,base64,hashlib,json,os,secrets
from datetime import date,datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from cryptography.hazmat.primitives import serialization,hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from src.meta_sync import Settings,MetaClient
from src.meta_history import collect,month_windows

def main():
 p=argparse.ArgumentParser();p.add_argument('--start-date',required=True);p.add_argument('--end-date',required=True);p.add_argument('--account-hashes',required=True);p.add_argument('--expected-sheet-hash',required=True);p.add_argument('--dry-run',action='store_true');a=p.parse_args();a.days=8;a.dry_run=True
 s=Settings.from_env(a);wanted=set(a.account_hashes.split(','));accounts=[x for x in s.accounts if hashlib.sha256(x.encode()).hexdigest()in wanted]
 assert len(accounts)==len(wanted)
 assert hashlib.sha256(s.spreadsheet_id.encode()).hexdigest()==a.expected_sheet_hash
 begin=date.fromisoformat(a.start_date);end=date.fromisoformat(a.end_date);assert begin<=end<=datetime.now(ZoneInfo('Asia/Ho_Chi_Minh')).date()
 meta=MetaClient(s.access_token,s.api_version);now=datetime.now(ZoneInfo('Asia/Ho_Chi_Minh')).strftime('%Y-%m-%d %H:%M:%S')
 rows,scopes,names=collect(meta,accounts,begin,end,now);check=[]
 for account in accounts:
  for lo,hi in month_windows(begin,end):
   result=meta._request(f'act_{account}/insights',{'fields':'spend,date_start,date_stop','level':'account','time_range':json.dumps({'since':lo.isoformat(),'until':hi.isoformat()}),'limit':100})
   assert isinstance(result.get('data'),list)and not result.get('paging',{}).get('next')
   check.append({'account':account,'from':lo.isoformat(),'to':hi.isoformat(),'account_spend':sum(float(r['spend'])for r in result['data'])})
 data=json.dumps({'rows':rows,'scopes':scopes,'accounts':names,'account_checks':check,'fetched_at':now},ensure_ascii=False).encode();key=secrets.token_bytes(32);nonce=secrets.token_bytes(12)
 public=serialization.load_pem_public_key(Path('audit-public.pem').read_bytes());wrapped=public.encrypt(key,padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),algorithm=hashes.SHA256(),label=None))
 envelope={'key':base64.b64encode(wrapped).decode(),'nonce':base64.b64encode(nonce).decode(),'ciphertext':base64.b64encode(AESGCM(key).encrypt(nonce,data,b'META_READ_ONLY_AUDIT_V1')).decode()};Path('audit-result.encrypted.json').write_text(json.dumps(envelope));print('Read-only audit encrypted successfully; no Google writes.')
if __name__=='__main__':
 try:main()
 except Exception:
  print('Read-only audit failed; no business values or credentials logged.');raise SystemExit(1)
