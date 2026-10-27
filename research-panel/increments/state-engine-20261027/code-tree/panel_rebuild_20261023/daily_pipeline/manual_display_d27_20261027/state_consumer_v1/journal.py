"""Fixed-root paired daily/state candidate journal; never a production/public reader."""
from pathlib import Path
import importlib.util,re,json,hashlib,os,uuid,shutil
H=Path(__file__).resolve().parent;s=importlib.util.spec_from_file_location('journal_state_engine',H/'state_engine.py');E=importlib.util.module_from_spec(s);s.loader.exec_module(E)
def sha(b):return hashlib.sha256(b).hexdigest()
def safe(path):
 if not path.is_relative_to(H/'runs'):raise ValueError('JOURNAL_ROOT')
 for x in (path,*path.parents):
  if x.is_symlink():raise ValueError('SYMLINK_REJECTED')
 return path

def write_new(path,content):
 safe(path)
 if path.exists():raise ValueError('IMMUTABLE_OBJECT_EXISTS')
 if shutil.disk_usage(H).free-len(content)<3*1024**3:raise ValueError('SPACE_FLOOR')
 path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
 with temp.open('xb')as f:f.write(content);f.flush();os.fsync(f.fileno())
 os.rename(temp,path)

class Journal:
 def __init__(self,run_id):
  if not isinstance(run_id,str)or not re.fullmatch('[A-Za-z0-9_]{1,64}',run_id):raise ValueError('FIXED_RUN_LABEL')
  self.root=safe(H/'runs'/run_id)
 def paths(self,symbol,date):
  if symbol not in E.ALLOWED_SYMBOLS or type(date)is not int:raise ValueError('JOURNAL_SYMBOL_DATE')
  E.datetime.datetime.strptime(str(date),'%Y%m%d');root=self.root/symbol
  return safe(root/'daily'/f'{date}.json'),safe(root/'state'/f'{date}.json'),safe(root/'checkpoints'/f'{date}.json')
 def day_path(self,symbol,date):return self.paths(symbol,date)[0]
 def commit(self,symbol,daily,state):
  payload=dict(state);state_hash=payload.pop('state_sha256',None)
  if sha(E.canonical(payload))!=state_hash:raise ValueError('STATE_HASH')
  date=daily['trade_date']
  if state['symbol']!=symbol or state['last_date']!=date or state['last_daily_sha256']!=sha(E.canonical(daily))or not state.get('last_transition')or state['engine_implementation_sha256']!=E.current_code_sha():raise ValueError('PAIR_STATE_DAY_BINDING')
  paths=self.paths(symbol,date);contents=[E.canonical(daily),E.canonical(state)]
  if any(p.exists()for p in paths):
   if not all(p.exists()for p in paths):raise ValueError('ORPHAN_PAIR_REQUIRES_REVIEW')
   old=self.read(symbol,date)
   if old['daily']!=daily or old['state']!=state:raise ValueError('SAME_DATE_CONFLICT')
   return {'status':'PAIR_IDENTICAL_REPLAY','date':date,'symbol':symbol}
  for p,b in zip(paths[:2],contents):write_new(p,b)
  cp={'schema':'STATE_DAY_PAIR_CANDIDATE_V1','symbol':symbol,'date':date,'daily_sha256':sha(contents[0]),'state_sha256':sha(contents[1]),'engine_sha256':E.current_code_sha(),'previous_state_sha256':state['last_transition']['previous_state_sha256'],'candidate_only':True,'research_consumption_allowed':False,'production_allowed':False}
  write_new(paths[2],E.canonical(cp));self.read(symbol,date)
  return {'status':'PAIR_CANDIDATE_WRITTEN','symbol':symbol,'date':date,'daily_sha256':cp['daily_sha256'],'state_file_sha256':cp['state_sha256']}
 def read(self,symbol,date):
  ps=self.paths(symbol,date)
  if not all(p.exists()for p in ps):raise ValueError('INCOMPLETE_PAIR_NOT_READABLE')
  raw=[p.read_bytes()for p in ps];d,st,cp=[json.loads(b)for b in raw]
  if cp['daily_sha256']!=sha(raw[0])or cp['state_sha256']!=sha(raw[1])or cp['symbol']!=symbol or cp['date']!=date or cp['engine_sha256']!=E.current_code_sha():raise ValueError('PAIR_CHECKPOINT_HASH')
  payload=dict(st);expected=payload.pop('state_sha256',None)
  if sha(E.canonical(payload))!=expected or st['symbol']!=symbol or st['last_date']!=date or d['trade_date']!=date or st['last_daily_sha256']!=sha(raw[0]):raise ValueError('STATE_DAY_RELOAD_BINDING')
  return {'status':'PAIRED_CANDIDATE_NOT_ADMITTED','research_consumption_allowed':False,'daily':d,'state':st}
