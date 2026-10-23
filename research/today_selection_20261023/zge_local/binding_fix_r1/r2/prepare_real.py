"""Read three fixed owner-panel prefixes and freeze expected canonical window hashes."""
import sys
sys.dont_write_bytecode=True
import hashlib,json,math
from pathlib import Path

cp=Path(sys.argv[1]);c=json.loads(cp.read_text());out=Path(c['output_directory']);out.mkdir(parents=True,exist_ok=True)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def digest(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def save(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def stat(p):
 s=p.stat();return dict(inode=s.st_ino,mtime_ns=s.st_mtime_ns,size_bytes=s.st_size)
for p,h in c['frozen_source_bindings'].items():assert sha(p)==h,'SOURCE_DRIFT:'+p
bp=Path(c['mac_binding_path']);assert sha(bp)==c['input_sha256'];b=json.loads(bp.read_text());panel=Path(b['selector']['target_path']);assert stat(panel)==b['selector']['target_stat']
def fence(event,args):
 if event.startswith(('socket.','sqlite3.connect','subprocess.Popen','os.system')):raise RuntimeError('FORBIDDEN_PROVIDER')
sys.addaudithook(fence)
import pyarrow.dataset as ds
codes=['600000.SH','000001.SZ','920000.BJ'];columns=['ts_code','trade_date','open','high','low','close','volume','amount','pct_chg']
predicate=ds.field('ts_code').isin(codes)&(ds.field('trade_date')>='20260101')&(ds.field('trade_date')<='20261022')
raw={code:[] for code in codes};total=0
for batch in ds.dataset(str(panel),format='parquet').scanner(columns=columns,filter=predicate,batch_size=65536,use_threads=False).to_batches():
 total+=batch.num_rows;assert total<10000,'ROW_BOUND'
 for row in batch.to_pylist():raw[row['ts_code']].append(row)
windows={};records=[]
for code in codes:
 prefix=sorted(raw[code],key=lambda x:x['trade_date']);assert prefix and prefix[-1]['trade_date']=='20261022','MISSING_OR_STALE:'+code
 assert len({x['trade_date'] for x in prefix})==len(prefix),'DUPLICATE:'+code
 selected=prefix[-120:];assert len(selected)==120,'SHORT_WINDOW:'+code
 canonical=[]
 for row in selected:
  x={'ts_code':code,'trade_date':row['trade_date']}
  for target,source in [('open','open'),('high','high'),('low','low'),('close','close'),('vol','volume'),('amount','amount'),('pct_chg','pct_chg')]:
   assert row[source] is not None and math.isfinite(row[source]),'REAL_REQUIRED_FIELD:'+code+':'+source
   x[target]=float(row[source])
  assert 0<x['low']<=min(x['open'],x['close'])<=max(x['open'],x['close'])<=x['high'] and x['vol']>=0 and x['amount']>=0
  canonical.append(x)
 windows[code]=canonical;records.append(dict(ts_code=code,signal_asof='20261022',selection_date='20261023',sha256=digest(canonical),row_count=len(canonical),first_date=canonical[0]['trade_date'],last_date=canonical[-1]['trade_date'],observed_prefix_rows=len(prefix)))
assert stat(panel)==b['selector']['target_stat'],'PANEL_CHANGED'
manifest=dict(schema='RESONANCE_BOUND_INPUT_WINDOWS_V1',source_identity=dict(kind='REUSED_OWNER_INPUT_BINDING',path=str(bp),sha256=sha(bp)),source_panel=dict(path=str(panel),sha256=b['selector']['expected_sha256'],stat=b['selector']['target_stat']),signal_asof='20261022',selection_date='20261023',price_basis='RAW_UNADJUSTED',units=dict(price='CNY',volume='SHARES',amount='CNY',pct_chg='PERCENT_POINTS'),canonical_columns=['ts_code','trade_date','open','high','low','close','vol','amount','pct_chg'],producer_source_sha256=sha(__file__),producer_execution_id=c['execution_id'],read_columns=columns,windows=records)
save(out/'LOCAL_SAMPLE_WINDOWS.json',windows);save(out/'REAL_INPUT_MANIFEST.json',manifest)
receipt=dict(status='REAL_INPUT_WINDOWS_FROZEN_BEFORE_DETECTOR',symbols=3,rows=360,manifest_path=str(out/'REAL_INPUT_MANIFEST.json'),manifest_sha256=sha(out/'REAL_INPUT_MANIFEST.json'),sample_path=str(out/'LOCAL_SAMPLE_WINDOWS.json'),sample_sha256=sha(out/'LOCAL_SAMPLE_WINDOWS.json'),records=records,panel_stat_unchanged=True,formula_evaluations=0,network_calls=0,sqlite_connections=0)
save(out/'PROFILE_RECEIPT.json',receipt);print(json.dumps(receipt,ensure_ascii=False))
