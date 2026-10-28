"""Explicit, frozen R19 profile for the existing single-stock history endpoint.

Never reads the default panel, creates transports, computes indicators, or
projects R19 values into the original user_v1 signal namespace.
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from hashlib import sha256
import importlib.util
import json
import math
from pathlib import Path

PROFILE = 'R19_FROZEN_151_20261027'
DATE = '20261027'
ADMISSION = 'r19_frozen151_research_admission.json'
ALLOWED_ROOT = Path('/Users/lexi/Desktop/学习/因子工厂/research/tdx_panel_parity_20261028_r1/r19_copy/OUTSIDE151_R19')
COMPARISON_PATH = Path('/Users/lexi/Desktop/学习/因子工厂/research/tdx_panel_parity_20261028_r1/RESULTS151.json')
PINS = {
 'outside151/r16/research_outputs/outside151_independent_research_registry_20261028/entries/002249.SZ/20261027/ENTRY.json':'32748ad7089976a942e0519fb30224b54c50bac54e0d5563d2bffa68dc6de78c',
 'launch_panel.py':'b12f38517ccaaf89e51ddaa86b44e389b26d3ff5985ff2f5a4752b70458d98bf',
 'DELIVERY_INDEX.json':'58ca304376d714adae3ebed91002cf92f1e8d6384185feed11031a1575c1abb3',
 'FILE_SHA256.json':'ccfd9ff5fd4efdd3ec679b16a5409e7e72b2c4ea35389d132b0b15e0ed09b65c',
 'outside151/r19_work/research_reader/research_portal.py':'4c095f67c2f61370408cc5f4b81a12ac0a9599dea84e4e4fe3f325f3458cc01e',
 'outside151/r19_work/research_reader/research_reader.py':'768d604e2ff5d58f012ec28d3410adfb54f8dc62bfd465eacd26ad56991c5231',
 'outside151/r18_work/research_reader/research_portal.py':'403513bd22988e928aa1d0b16597a1e40569d4536bb9d13ab26efeeee23fb9e7',
 'outside151/r18_work/research_reader/research_reader.py':'ce79cd27eb25d10a0eb15e7de316fa6bc731fae4caff809006cbbd49122622e4',
 'proofs/FINAL_CONSUMER_ACCEPTANCE.json':'a4aeb2f731372dd1376d00b5bdb61559a8040966931dc913263a1b180c1d4933',
}
FORMULA_SHA = 'd35c9a30d7133420272ee5a2014f67ce64c0c7cd5a5ef9c16b846c025e2a05ac'
FLAGS = {'research_only':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
SOP_URL = 'https://drive.google.com/file/d/1mv_nUkpX1bUKNCFD8JIBKMOYiNQfb-_R/view?usp=drivesdk'

def require(ok, reason):
 if not ok:raise ValueError(reason)

def safe(path):
 path=Path(path)
 require(path.is_absolute() and '..' not in path.parts and not any(x.is_symlink() for x in (path,*path.parents)), 'R19_UNSAFE_PATH')
 return path

def unique(pairs):
 d={}
 for k,v in pairs:
  require(k not in d,'R19_DUPLICATE_JSON_KEY');d[k]=v
 return d

def decode(raw):return json.loads(raw,object_pairs_hook=unique)
def sh(raw):return sha256(raw).hexdigest()
def pinned(path,digest):
 raw=safe(path).read_bytes();require(sh(raw)==digest,'R19_SOURCE_SHA_DRIFT:'+str(path));return raw

def module(path,name):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def validate_admission(raw):
 a=decode(raw)
 require(a.get('schema')=='v4.r19_frozen151_research_admission.v1' and a.get('profile_id')==PROFILE and a.get('target_date')==DATE,'R19_ADMISSION_IDENTITY')
 require(a.get('status')=='SOURCE_REVIEWED_RESEARCH_ONLY' and a.get('package_root')==str(ALLOWED_ROOT),'R19_ADMISSION_ROOT_OR_STATUS')
 require(all(a.get(k) is v for k,v in FLAGS.items()),'R19_ADMISSION_FLAGS')
 require(a.get('adapter_sha256')==sh(Path(__file__).read_bytes()),'R19_ADAPTER_SHA_DRIFT')
 require(a.get('source_code_pins')==PINS and a.get('formula_source_sha256')==FORMULA_SHA,'R19_ADMISSION_CODE_IDENTITY')
 require(isinstance(a.get('scope'),list) and len(a['scope'])==len(set(a['scope']))==151,'R19_EXACT151_ADMISSION')
 for relative,digest in PINS.items():pinned(ALLOWED_ROOT/relative,digest)
 c=a.get('comparison',{})
 require(c.get('path')==str(COMPARISON_PATH) and c.get('formal_parity')=='CANNOT_CONFIRM','R19_COMPARISON_BINDING')
 pinned(COMPARISON_PATH,c['sha256'])
 return a

@lru_cache(maxsize=2)
def load_frozen(raw):
 a=validate_admission(raw)
 launcher=module(ALLOWED_ROOT/'launch_panel.py','v4_r19_frozen_transport')
 meta,manifest,members,planned=launcher.verify_delivery()
 # Existing original launcher-generated transports must already exist. The API never writes them.
 for x in planned:require(safe(x['path']).read_bytes()==x['raw'],'R19_TRANSPORT_MISSING_OR_CHANGED')
 require(a['transport']=={'path':str(planned[-1]['path']),'sha256':planned[-1]['sha256']},'R19_TRANSPORT_BINDING')
 reader=module(ALLOWED_ROOT/'outside151/r19_work/research_reader/research_portal.py','v4_r19_frozen_portal')
 portal=reader.ResearchPortal(planned[-1]['path'],planned[-1]['sha256'])
 require(set(a['scope'])==portal.scope,'R19_SCOPE_MISMATCH')
 comparison=decode(pinned(COMPARISON_PATH,a['comparison']['sha256']))
 require(comparison.get('target_date')==DATE and comparison.get('group_signal_date')=='CANNOT_CONFIRM','R19_COMPARISON_DATE')
 rows={x['symbol']:x for x in comparison['results']}
 require(len(rows)==151 and set(rows)==portal.scope,'R19_COMPARISON_SCOPE')
 return portal,rows

def numeric(value):
 if value is None:return None
 try:
  x=Decimal(str(value));y=float(x)
  return y if x.is_finite() and math.isfinite(y) else None
 except (ValueError,TypeError,InvalidOperation,OverflowError):return None

def read_profile(shared_data_root,code,start,end,response):
 out={**response,'formula_version':PROFILE,'profile_id':PROFILE,'signal_namespace':'R19_51_VALUES_22_DRAWINGS_NO_USER_V1_PROJECTION','columns':[], 'rows':[], 'cannot_confirm':[],**FLAGS}
 try:
  require(end==DATE,'R19_FROZEN_TARGET_REQUIRES_END_20261027')
  require(shared_data_root is not None,'R19_SHARED_ROOT_NOT_CONFIGURED')
  admission_path=safe(Path(shared_data_root)/'runtime/cache/data_layer_daily_formula_increment_update_v1'/ADMISSION)
  raw=admission_path.read_bytes();require(len(raw)<=200000,'R19_ADMISSION_TOO_LARGE')
  a=validate_admission(raw)
  require(code in a['scope'],'R19_SYMBOL_OUTSIDE_EXACT151')
  portal,comparison=load_frozen(raw)
  answer=portal.query(code,DATE,0)
  actual=answer.get('rows',[])
  cfg=portal.configs.get(code) or portal.old.configs.get(code)
  if cfg:
   input_sha=cfg[1]['qfq']['sha256']
  elif code=='002249.SZ':
   entry=decode((ALLOWED_ROOT/'outside151/r16/research_outputs/outside151_independent_research_registry_20261028/entries/002249.SZ/20261027/ENTRY.json').read_bytes())
   require(entry['core']['symbol']==code and entry['core']['date']==DATE,'R19_LEGACY_INPUT_IDENTITY')
   input_sha=entry['core']['artifacts']['qfq']['sha256']
  else:
   input_sha=portal.old.dispositions[code]['evidence']['sha256']
  out.update(identity={'generation_id':answer['registry_sha256'],'input_sha256':input_sha,
      'manifest_sha256':sh(raw),'artifact_sha256':answer.get('formula_sha256',a['source_code_pins']['proofs/FINAL_CONSUMER_ACCEPTANCE.json']),
      'formula_source_sha256':FORMULA_SHA,'asof_date':20261027,'verification_basis':'EXACT_R19_REGISTERED_RESEARCH_READER; NO_ORIGINAL23_SIGNAL_PROJECTION',
      'historical_PIT':False,'maximum_claim':'DIRECTION_ONLY','source_vendor':answer.get('source_vendor'),'source_kind':answer.get('source_kind'),
      'price_coordinate_type':answer.get('price_coordinate_type'),'qualification_zh':answer.get('qualification_zh'),
      'historical_source_limitations':answer.get('historical_source_limitations'),'volume_unit_certified':False,'native_tdx_equivalence_certified':False,
      'r19_registry_sha256':answer['registry_sha256'],'admission_sha256':sh(raw)})
  out['r19_research']={'target_date':DATE,'sop_url':SOP_URL,'field_count':answer.get('field_count',0),'drawing_count':answer.get('drawing_count',0),
      'last_row':None,'comparison':comparison[code],'comparison_note':'D27本地历史公式与D28文件mtime的捕获分组作观察；分组信号日、当前正文及执行全集未确认，未列入分组不证明通达信拒绝。',
      'reason_zh':answer.get('reason_zh'),'official_cause_overlay':answer.get('official_cause_overlay'),'amount_status':'NOT_EXPOSED_BY_R19_READER'}
  if not actual:
   require(answer.get('reason')=='NO_TARGET_BAR','R19_UNEXPECTED_EMPTY_DISPOSITION')
   return {**out,'status':'EMPTY_EXACT_RANGE','cannot_confirm':[answer.get('reason_zh') or 'R19目标日无真实行情，未回填其他日期。']}
  out['identity']['declared_history_first_date']=str(actual[0]['trade_date'])
  out['r19_research']['coverage_note']='声明历史起点 '+str(actual[0]['trade_date'])+'；仅返回请求范围内真实已存行，未填造起点以前的数据。'
  selected=[r for r in actual if start<=str(r['trade_date'])<=end]
  lines={'BBI':'BBI','zge_white_line':'白线','zge_yellow_line':'黄线','ma60':'MA60','J':'J','macd_dif':'DIF','macd_dea':'DEA'}
  rows=[]
  for r in selected:
   row={'ts_code':code,'trade_date':str(r['trade_date']),'market_type':'A_SHARE','name':code,'amount':None}
   row.update({k:numeric(r['ohlcv'].get(k)) for k in ('open','high','low','close')})
   row['volume']=numeric(r['ohlcv'].get('vol'))
   row.update({target:numeric(r['values'].get(source)) for target,source in lines.items()})
   rows.append(row)
  require(rows and rows[-1]['trade_date']==DATE,'R19_TARGET_ROW_MISSING')
  out['r19_research']['last_row']=actual[-1]
  return {**out,'status':'READY','rows':rows,'columns':list(rows[0])}
 except (OSError,ValueError,KeyError,TypeError,AttributeError,RuntimeError) as error:
  return {**out,'status':'CANNOT_CONFIRM','rows':[],'cannot_confirm':[str(error) or type(error).__name__]}
