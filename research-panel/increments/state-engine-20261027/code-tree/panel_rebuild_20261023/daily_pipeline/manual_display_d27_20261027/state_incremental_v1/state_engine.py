"""Isolated exact one-day AST state engine candidate; no market I/O or old-history compute calls."""
from pathlib import Path
from decimal import Decimal as D,localcontext,Context,ROUND_HALF_EVEN
import importlib.util,json,hashlib,copy,datetime
H=Path(__file__).resolve().parent;PROJECT=H.parents[2]
ENGINE_SHA='ae4243ec9582055fb6f2ee796978ad20e17f9dee7a56388063cbdbcb56ef0d1c'
p=PROJECT/'formula/formula_engine.py'
if hashlib.sha256(p.read_bytes()).hexdigest()!=ENGINE_SHA:raise ValueError('ORIGINAL_ENGINE_HASH')
s=importlib.util.spec_from_file_location('original_formula_parser_only',p);F=importlib.util.module_from_spec(s);s.loader.exec_module(F)
VERSION='EXACT_DAILY_STATE_CANDIDATE_V2'
DECIMAL_CONTEXT=Context(prec=28,rounding=ROUND_HALF_EVEN)
DECIMAL_CONTRACT={'precision':28,'rounding':'ROUND_HALF_EVEN','Emin':-999999,'Emax':999999,'capitals':1,'clamp':0,'traps':['InvalidOperation','DivisionByZero','Overflow']}
CALENDAR_SHA='227e07683c91fe5bc6077f506daea0a3c2836d431f4c2767841147429053bc30'

def scalar(x):
 if x is None or type(x)is bool:return x
 if not isinstance(x,(str,int,float,D)):raise ValueError('NUMERIC_SCALAR_TYPE')
 try:y=D(str(x))
 except Exception:raise ValueError('NUMERIC_SCALAR_PARSE')
 if not y.is_finite():raise ValueError('NONFINITE_SCALAR')
 return y

def key(ast):return hashlib.sha256(json.dumps(ast,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
def canonical(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def encode(x):
 if isinstance(x,D):return str(x)
 if isinstance(x,dict):return {k:encode(v)for k,v in x.items()}
 if isinstance(x,(list,tuple)):return [encode(v)for v in x]
 return x

class Evaluator:
 def __init__(self,index,nodes,seed_values=None,bootstrap=False):self.index=index;self.nodes=nodes;self.cache={};self.seed_values=seed_values or {};self.bootstrap=bootstrap
 def evaluate(self,ast,env):
  ident=key(ast)
  if ident in self.cache:return self.cache[ident]
  typ=ast[0]
  if typ=='var':
   if ast[1]not in env:raise ValueError('UNBOUND_VARIABLE:'+ast[1])
   out=env[ast[1]]
  elif typ=='number':out=D(ast[1])
  elif typ=='text':out=ast[1]
  elif typ=='unary':
   x=self.evaluate(ast[2],env);out=None if x is None else -x if ast[1]=='-'else x
  elif typ=='binary':out=F.operation(ast[1],self.evaluate(ast[2],env),self.evaluate(ast[3],env))
  elif typ=='call':out=self.call(ast,[self.evaluate(a,env)for a in ast[2]])
  else:raise ValueError('UNSUPPORTED_AST')
  self.cache[ident]=out;return out
 def call(self,ast,args):
  name=ast[1];x=args[0];ident=key(ast)
  if name=='IF':return None if x is None else args[1]if bool(x)else args[2]
  if name=='MIN':return None if x is None or args[1]is None else min(x,args[1])
  node=self.nodes.setdefault(ident,{'kind':name})
  if node['kind']!=name:raise ValueError('STATE_NODE_KIND')
  if name=='BARSLAST':
   node.setdefault('last_true',None)
   if x is None:node['last_true']=None
   elif bool(x):node['last_true']=self.index
   last=node.get('last_true');return None if last is None else D(self.index-last)
  if name=='CROSS':
   previous=node.get('previous');node['previous']=encode(args)
   if self.index==0 or previous is None:return None
   a,b=[scalar(v)for v in previous];return F.operation('AND',F.operation('>',x,args[1]),F.operation('<=',a,b))
  period=args[1]
  if period is not None and (isinstance(period,bool)or period<0 or period!=int(period)):raise ValueError('INVALID_PERIOD')
  k=None if period is None else int(period)
  if name in ('EMA','SMA'):
   node.setdefault('value',None)
   if ident in self.seed_values:
    emitted=self.seed_values[ident]
    if emitted is not None:node['value']=str(emitted)
    return emitted
   state=scalar(node.get('value'));value=None
   if k is not None:
    if k<=0:raise ValueError('NONPOSITIVE_SMOOTH_PERIOD')
    if x is not None:
     weight=D(2)/(k+1) if name=='EMA'else args[2]/k if args[2]is not None else None
     if weight is not None:
      state=x if state is None else (D(2)*x+state*(k-1))/(k+1)if name=='EMA'else(args[2]*x+(k-args[2])*state)/k
      value=state
   node['value']=None if state is None else str(state);return value
  dynamic=ast[2][1][0]!='number'
  if name=='REF':
   if dynamic:
    if k is None:node['anchor']=None;node['anchor_index']=None;return None
    if k==0:node['anchor']=encode(x);node['anchor_index']=self.index;return x
    if node.get('anchor_index')!=self.index-k:raise ValueError('DYNAMIC_REF_ANCHOR_MISSING')
    return scalar(node.get('anchor'))
   buffer=[scalar(v)for v in node.get('buffer',[])]+[x]
   node['buffer']=encode(buffer[-(k+1):])if k is not None else encode(buffer)
   return buffer[-k-1]if k is not None and len(buffer)>=k+1 else None
  if name=='COUNT':
   node['known']=node.get('known',0)+int(x is not None);node['true']=node.get('true',0)+int(x is not None and bool(x))
   if dynamic:
    old_age=node.get('age');node['age']=k
    if k is None:node['since_true']=0;node['since_null']=0;return None
    if k==0:node['since_true']=0;node['since_null']=0;return D(node['true'])if node['known']else None
    if old_age is None or k!=old_age+1:raise ValueError('DYNAMIC_COUNT_STATE_GAP')
    node['since_true']=node.get('since_true',0)+int(x is not None and bool(x));node['since_null']=node.get('since_null',0)+int(x is None)
    return None if node['since_null']else D(node['since_true'])
   if k==0:return D(node['true'])if node['known']else None
  if name not in ('MA','COUNT','HHV','LLV'):raise ValueError('UNSUPPORTED_STATE_FUNCTION:'+name)
  if k is None:return None
  if k<=0:raise ValueError('NONPOSITIVE_WINDOW')
  buf=[scalar(v)for v in node.get('buffer',[])]+[x];buf=buf[-k:];node['buffer']=encode(buf)
  if self.bootstrap and name in ('MA','HHV','LLV'):return None  # restore input windows, not old indicator values
  if len(buf)<k or any(v is None for v in buf):return None
  if name=='MA':return sum(buf)/k
  if name=='COUNT':return D(sum(bool(v)for v in buf))
  return max(buf)if name=='HHV'else min(buf)

ALLOWED_SYMBOLS={'002608.SZ','000700.SZ','600698.SH','600785.SH','301686.SZ','301655.SZ'}

def inventory():
 inv=F.inventory();assignments=[(x,F.Parser(x['expression']).parse())for x in inv['assignments']];drawings=[(x,tuple(F.Parser(x[k]).parse()for k in ('condition','y','payload')))for x in inv['drawings']];calls={}
 def walk(ast):
  if ast[0]=='call':
   for a in ast[2]:walk(a)
   calls.setdefault(key(ast),ast)
  elif ast[0]=='binary':walk(ast[2]);walk(ast[3])
  elif ast[0]=='unary':walk(ast[2])
 for _,a in assignments:walk(a)
 for _,aa in drawings:
  for a in aa:walk(a)
 visible={key(a):x['name']for x,a in assignments if a[0]=='call'and a[1]in('EMA','SMA')};hidden={k for k,a in calls.items()if a[1]in('EMA','SMA')and k not in visible};stateful={k:a for k,a in calls.items()if a[1]not in('MIN','IF')}
 if len(visible)!=4 or len(hidden)!=3:raise ValueError('EXPECTED_SMOOTH_STATE_INVENTORY')
 return inv,assignments,drawings,stateful,visible,hidden

def validate_nodes(nodes,calls,count,hidden):
 if type(count)is not int or count<1 or set(nodes)!=set(calls):raise ValueError('STATE_COUNT_OR_NODE_SET')
 def number(v,nullable=True):
  if v is None and nullable:return
  if not isinstance(v,str)or not isinstance(scalar(v),D):raise ValueError('STATE_DECIMAL_STRING')
 def integer(v,upper,nullable=False):
  if v is None and nullable:return
  if type(v)is not int or not 0<=v<=upper:raise ValueError('STATE_COUNTER_OR_POSITION')
 for ident,ast in calls.items():
  n=nodes[ident];kind=ast[1];dynamic=len(ast[2])>1 and ast[2][1][0]!='number'
  fields={'kind'}
  if kind in ('EMA','SMA'):fields|={'value'}
  elif kind=='BARSLAST':fields|={'last_true'}
  elif kind=='CROSS':fields|={'previous'}
  elif kind=='REF':fields|={'anchor','anchor_index'}if dynamic else {'buffer'}
  elif kind=='COUNT':fields|={'known','true','age','since_true','since_null'}if dynamic else {'known','true','buffer'}
  else:fields|={'buffer'}
  if not isinstance(n,dict)or set(n)!=fields or n['kind']!=kind:raise ValueError('STATE_NODE_REQUIRED_SCHEMA')
  if kind in ('EMA','SMA'):number(n['value'],ident not in hidden)
  if kind=='BARSLAST':integer(n['last_true'],count-1,True)
  if kind=='CROSS':
   if not isinstance(n['previous'],list)or len(n['previous'])!=2:raise ValueError('STATE_CROSS_PAIR')
   for v in n['previous']:number(v)
  if 'buffer'in n:
   k=int(D(ast[2][1][1]));expected=min(count,k+1 if kind=='REF'else k)
   if not isinstance(n['buffer'],list)or len(n['buffer'])!=expected:raise ValueError('STATE_BUFFER_LENGTH')
   for v in n['buffer']:
    if kind=='COUNT':
     if v is not None and type(v)is not bool:raise ValueError('STATE_COUNT_BOOLEAN')
    else:number(v)
  if kind=='REF'and dynamic:
   integer(n['anchor_index'],count-1,True);number(n['anchor'])
   if (n['anchor']is None)!=(n['anchor_index']is None):raise ValueError('STATE_ANCHOR_PAIR')
  if kind=='COUNT':
   integer(n['known'],count);integer(n['true'],n['known'])
   if dynamic:
    integer(n['age'],count-1,True);age=n['age']or 0
    integer(n['since_true'],age);integer(n['since_null'],age)
    if n['since_true']+n['since_null']>age:raise ValueError('STATE_COUNT_WINDOW_SUM')

def current_code_sha():return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
def binding_check(symbol,binding):
 required={'symbol','purpose','price_coordinate','event_sha256','policy_sha256','source_formula_sha256','volume_contract_sha256','bootstrap_prefix_sha256','date_contract'}
 if set(binding)!=required or binding['symbol']!=symbol or symbol not in ALLOWED_SYMBOLS:raise ValueError('SIX_STOCK_BINDING_SCOPE')
 if binding['purpose']!='SIX_STOCK_CACHED_HOLDOUT_ALGORITHM_ONLY' or binding['price_coordinate']!='FIXED_VINTAGE_QFQ_NONPIT':raise ValueError('RESEARCH_PURPOSE_COORDINATE')
 for k in ('event_sha256','policy_sha256','source_formula_sha256','volume_contract_sha256','bootstrap_prefix_sha256'):
  if not isinstance(binding[k],str)or not __import__('re').fullmatch('[0-9a-f]{64}',binding[k]):raise ValueError('BINDING_HASH_SCHEMA')
 d=binding['date_contract'];kind=d.get('kind')
 if kind not in ('CACHED_ADJACENT_SEQUENCE_ONLY_NOT_CALENDAR_ADMITTED','VERIFIED_CALENDAR_RESEARCH_CANDIDATE'):raise ValueError('DATE_CONTRACT_KIND')
 dates=d.get('open_dates')
 if not isinstance(dates,list)or not dates or any(type(x)is not int for x in dates)or any(a>=b for a,b in zip(dates,dates[1:])):raise ValueError('DATE_CONTRACT_ORDER')
 for x in dates:datetime.datetime.strptime(str(x),'%Y%m%d')
 if kind=='VERIFIED_CALENDAR_RESEARCH_CANDIDATE':
  if set(d)!={'kind','open_dates','coverage_start','coverage_end','calendar_sha256'}or not isinstance(d['calendar_sha256'],str)or not __import__('re').fullmatch('[0-9a-f]{64}',d['calendar_sha256']):raise ValueError('CALENDAR_BINDING_SCHEMA')
  cp=PROJECT/'daily_pipeline/CALENDAR_20261023_1231_VERIFIED_V2.json';raw=cp.read_bytes()
  if hashlib.sha256(raw).hexdigest()!=CALENDAR_SHA or d['calendar_sha256']!=CALENDAR_SHA:raise ValueError('CALENDAR_AUTHORITY_HASH')
  cal=json.loads(raw)
  if dates!=[int(x)for x in cal['open_dates']]or d['coverage_start']!=cal['coverage_start']or d['coverage_end']!=cal['coverage_end']:raise ValueError('CALENDAR_AUTHORITY_CONTENT')
 elif set(d)!={'kind','open_dates'}:raise ValueError('CACHED_SEQUENCE_SCHEMA')

def seal(state):
 out=encode(state);out.pop('state_sha256',None);out['state_sha256']=hashlib.sha256(canonical(out)).hexdigest();return out

def source_env(row):
 env={k.upper():scalar(row['ohlcv'][k])for k in ('open','high','low','close','vol')};env.update({k:scalar(v)for k,v in row['values'].items()});env.update(DRAWNULL=None,CURRBARSCOUNT=D(1));return env

def bootstrap(symbol,daily_rows,asof,binding):
 """Restore existing daily outputs; calculate only the three missing EMA sequences once."""
 binding_check(symbol,binding)
 if not daily_rows or daily_rows[-1]['trade_date']!=asof or hashlib.sha256(canonical(daily_rows)).hexdigest()!=binding['bootstrap_prefix_sha256']:raise ValueError('EXACT_PREFIX_CUTOFF_HASH')
 inv,assignments,drawings,calls,visible,hidden=inventory();names={x['name']for x,_ in assignments};nodes={};dates=[r['trade_date']for r in daily_rows]
 if any(a>=b for a,b in zip(dates,dates[1:])):raise ValueError('PREFIX_DATE_ORDER')
 if asof not in binding['date_contract']['open_dates']:raise ValueError('CUTOFF_OUTSIDE_DATE_CONTRACT')
 with localcontext(DECIMAL_CONTEXT)as ctx:
  ctx.prec=28
  for i,row in enumerate(daily_rows):
   if set(row['values'])!=names or len(row['drawings'])!=22 or row['ohlcv']['trade_date']!=row['trade_date']:raise ValueError('EXISTING_DAILY_SCHEMA')
   F.normalize([row['ohlcv']]);env=source_env(row);seed={k:env[name]for k,name in visible.items()};ev=Evaluator(i,nodes,seed,bootstrap=True)
   for ast in calls.values():ev.evaluate(ast,env)
 validate_nodes(nodes,calls,len(daily_rows),hidden)
 state={'schema':VERSION,'decimal_contract':DECIMAL_CONTRACT,'symbol':symbol,'engine_implementation_sha256':current_code_sha(),'original_engine_sha256':ENGINE_SHA,'formula_sha256':F.SOURCE_SHA,'binding':copy.deepcopy(binding),'binding_sha256':hashlib.sha256(canonical(binding)).hexdigest(),'count':len(daily_rows),'first_date':daily_rows[0]['trade_date'],'last_date':asof,'nodes':nodes,'last_daily_sha256':hashlib.sha256(canonical(daily_rows[-1])).hexdigest(),'history_lineage_sha256':binding['bootstrap_prefix_sha256'],'bootstrap':{'only_hidden_smoothers_computed':3,'hidden_smoother_updates':3*len(daily_rows),'visible_smoothers_restored':4,'barslast_restored':4,'count_states_restored':7,'historical_named51_outputs_recomputed':0,'original_compute_calls':0},'PIT':False,'production_allowed':False,'training_eligible':False,'status':'SIX_STOCK_STATE_CANDIDATE_NOT_ADMITTED'}
 return seal(state)

def step(state,bar,binding):
 """Evaluate exactly one incoming day; never loads or evaluates old indicator rows."""
 s=copy.deepcopy(state);given=s.pop('state_sha256',None)
 if hashlib.sha256(canonical(s)).hexdigest()!=given:raise ValueError('STATE_INTEGRITY_HASH')
 if s.get('decimal_contract')!=DECIMAL_CONTRACT:raise ValueError('STATE_DECIMAL_CONTRACT')
 if s['schema']!=VERSION or s['engine_implementation_sha256']!=current_code_sha()or s['original_engine_sha256']!=ENGINE_SHA or s['formula_sha256']!=F.SOURCE_SHA:raise ValueError('STATE_VERSION')
 binding_check(s['symbol'],binding)
 if s['binding']!=binding or s['binding_sha256']!=hashlib.sha256(canonical(binding)).hexdigest():raise ValueError('SOURCE_EVENT_POLICY_BINDING_CHANGED')
 dates=binding['date_contract']['open_dates'];last=s['last_date'];target=bar['trade_date']
 if last not in dates or dates.index(last)+1>=len(dates)or dates[dates.index(last)+1]!=target:raise ValueError('NEXT_DATE_GAP_OR_REPLAY')
 inv,assignments,drawings,calls,visible,hidden=inventory()
 validate_nodes(s['nodes'],calls,s['count'],hidden)
 q=F.normalize([bar])[0];env={k.upper():q[k]for k in ('open','high','low','close','vol')};env.update(DRAWNULL=None,CURRBARSCOUNT=D(1));ev=Evaluator(s['count'],s['nodes']);draw=[]
 with localcontext(DECIMAL_CONTEXT)as ctx:
  ctx.prec=28
  for x,ast in assignments:env[x['name']]=ev.evaluate(ast,env)
  for x,ast in drawings:
   cond,y,payload=[ev.evaluate(a,env)for a in ast];c=F.boolean(cond);draw.append({'id':x['id'],'kind':x['kind'],'condition':c,'y':y if c is True else None,'payload':payload,'styles':x['styles']})
 row=encode({'trade_date':target,'ohlcv':q,'values':{x['name']:env[x['name']]for x,_ in assignments},'drawings':draw});s['last_date']=target;s['count']+=1;s['last_daily_sha256']=hashlib.sha256(canonical(row)).hexdigest();s['history_lineage_sha256']=hashlib.sha256(canonical({'previous':state['history_lineage_sha256'],'new_daily_sha256':s['last_daily_sha256']})).hexdigest();s['last_transition']={'previous_state_sha256':given,'old_history_rows_recomputed':0,'original_compute_calls':0,'new_indicator_rows':1};return row,seal(s)
