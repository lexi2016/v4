"""Pinned user formula interpreter. New cloud research candidate, NOT native-TDX certified.
No eval/exec, network, model fitting or imports from downloaded scripts.
"""
from decimal import Decimal as D, localcontext
from pathlib import Path
import re,hashlib,datetime
SOURCE=Path(__file__).with_name('USER_MAIN_CHART_FORMULA_MESSAGE_EXACT_UTF8.txt')
SOURCE_SHA='d35c9a30d7133420272ee5a2014f67ce64c0c7cd5a5ef9c16b846c025e2a05ac'
TOKEN=re.compile(r"\s*(?:(\d+(?:\.\d*)?|\.\d+)|('(?:[^']*)')|([A-Za-z_\u0080-\uffff][\w\u0080-\uffff]*)|(>=|<=|:=|[+*/<>=(),:-]))")
PRECEDENCE={'OR':1,'AND':2,'=':3,'<':3,'>':3,'<=':3,'>=':3,'+':4,'-':4,'*':5,'/':5}
FUNCTIONS={'MA','EMA','SMA','REF','COUNT','BARSLAST','CROSS','HHV','LLV','MIN','IF'}
def tokens(text):
 out=[];pos=0
 while pos<len(text):
  if not text[pos:].strip():break
  m=TOKEN.match(text,pos)
  if not m:raise ValueError('UNSUPPORTED_TOKEN:'+text[pos:pos+20])
  out.append(next(x for x in m.groups() if x is not None));pos=m.end()
 return out
class Parser:
 def __init__(self,text):self.t=tokens(text);self.i=0
 def peek(self):return self.t[self.i] if self.i<len(self.t) else None
 def pop(self):
  t=self.peek()
  if t is None:raise ValueError('UNEXPECTED_END')
  self.i+=1;return t
 def expr(self,minp=0):
  t=self.pop()
  if t=='(':
   lhs=self.expr()
   if self.pop()!=')':raise ValueError('MISSING_PAREN')
  elif t in ('-','+'):lhs=('unary',t,self.expr(6))
  elif t.startswith("'"):lhs=('text',t[1:-1])
  elif t[0].isdigit() or t[0]=='.':lhs=('number',t)
  elif self.peek()=='(':
   if t not in FUNCTIONS:raise ValueError('UNSUPPORTED_FUNCTION:'+t)
   self.pop();args=[]
   if self.peek()!=')':
    while True:
     args.append(self.expr())
     if self.peek()!=',':break
     self.pop()
   if self.pop()!=')':raise ValueError('MISSING_CALL_PAREN')
   lhs=('call',t,tuple(args))
  else:lhs=('var',t)
  while self.peek() in PRECEDENCE and PRECEDENCE[self.peek()]>=minp:
   op=self.pop();lhs=('binary',op,lhs,self.expr(PRECEDENCE[op]+1))
  return lhs
 def parse(self):
  a=self.expr()
  if self.peek() is not None:raise ValueError('TRAILING_TOKENS')
  return a
def split_top(text):
 out=[];start=0;depth=0;quote=False
 for i,ch in enumerate(text):
  if ch=="'":quote=not quote
  if quote:continue
  if ch=='(':depth+=1
  elif ch==')':depth-=1
  elif ch==',' and depth==0:out.append(text[start:i].strip());start=i+1
 out.append(text[start:].strip());return out
def inventory():
 raw=SOURCE.read_bytes()
 if hashlib.sha256(raw).hexdigest()!=SOURCE_SHA:raise ValueError('SOURCE_PIN_MISMATCH')
 assignments=[];drawings=[]
 for statement in raw.decode().split(';'):
  statement=statement.strip()
  if not statement:continue
  segments=split_top(statement);main=segments[0];styles=segments[1:]
  if main.startswith(('DRAWTEXT(', 'DRAWICON(')):
   kind,tail=main.split('(',1)
   if not tail.endswith(')'):raise ValueError('DRAWING_PAREN')
   args=split_top(tail[:-1])
   if len(args)!=3:raise ValueError('DRAWING_ARITY')
   drawings.append(dict(id=len(drawings)+1,kind=kind,condition=args[0],y=args[1],payload=args[2],styles=styles))
  else:
   m=re.fullmatch(r'([^:]+)(:=|:)(.+)',main)
   if not m:raise ValueError('INVALID_ASSIGNMENT')
   assignments.append(dict(name=m[1],expression=m[3],styles=styles))
 if len(assignments)!=51 or len(drawings)!=22 or len({x['name'] for x in assignments})!=51:raise ValueError('INVENTORY_MISMATCH')
 return dict(source_sha256=SOURCE_SHA,assignments=assignments,drawings=drawings)
def normalize(bars):
 out=[];last=0
 for row in bars:
  d=row['trade_date']
  if type(d) is not int or len(str(d))!=8 or d<=last:raise ValueError('DATES_MUST_BE_UNIQUE_INCREASING')
  datetime.datetime.strptime(str(d),'%Y%m%d');last=d;r={'trade_date':d}
  for k in ['open','high','low','close','vol']:
   x=D(str(row[k]))
   if not x.is_finite():raise ValueError('NONFINITE_OHLCV')
   r[k]=x
  if r['high']<r['low'] or not r['low']<=r['open']<=r['high'] or not r['low']<=r['close']<=r['high'] or r['vol']<0:raise ValueError('INVALID_RANGE_OR_VOLUME')
  out.append(r)
 return out
def boolean(x):return None if x is None else bool(x)
def operation(op,a,b):
 if a is None or b is None:return None
 if op=='AND':return bool(a) and bool(b)
 if op=='OR':return bool(a) or bool(b)
 if op=='+':return a+b
 if op=='-':return a-b
 if op=='*':return a*b
 if op=='/':return None if b==0 else a/b
 if op=='>':return a>b
 if op=='<':return a<b
 if op=='>=':return a>=b
 if op=='<=':return a<=b
 if op=='=':return a==b
 raise ValueError('BAD_OPERATOR')
def evaluate(ast,env,n,cache):
 if ast in cache:return cache[ast]
 typ=ast[0]
 if typ=='var':
  if ast[1] not in env:raise ValueError('UNBOUND_VARIABLE:'+ast[1])
  out=env[ast[1]]
 elif typ=='number':out=[D(ast[1])]*n
 elif typ=='text':out=[ast[1]]*n
 elif typ=='unary':out=[None if x is None else -x if ast[1]=='-' else x for x in evaluate(ast[2],env,n,cache)]
 elif typ=='binary':out=[operation(ast[1],a,b) for a,b in zip(evaluate(ast[2],env,n,cache),evaluate(ast[3],env,n,cache))]
 elif typ=='call':
  name=ast[1];a=[evaluate(x,env,n,cache) for x in ast[2]];out=[];state=None;last_true=None
  arity={'MA':2,'EMA':2,'SMA':3,'REF':2,'COUNT':2,'BARSLAST':1,'CROSS':2,'HHV':2,'LLV':2,'MIN':2,'IF':3}
  if len(a)!=arity[name]:raise ValueError('FUNCTION_ARITY:'+name)
  for i in range(n):
   x=a[0][i];value=None
   if name=='IF':value=None if x is None else a[1][i] if bool(x) else a[2][i]
   elif name=='MIN':value=None if x is None or a[1][i] is None else min(x,a[1][i])
   elif name=='BARSLAST':
    if x is None:last_true=None
    elif bool(x):last_true=i
    value=None if last_true is None else D(i-last_true)
   elif name=='CROSS':value=None if i==0 else operation('AND',operation('>',x,a[1][i]),operation('<=',a[0][i-1],a[1][i-1]))
   else:
    period=a[1][i]
    if period is not None:
     if period<0 or period!=int(period):raise ValueError('INVALID_PERIOD')
     k=int(period)
     if name=='REF':value=a[0][i-k] if i>=k else None
     elif name in ('EMA','SMA'):
      if k<=0:raise ValueError('NONPOSITIVE_SMOOTH_PERIOD')
      if x is not None:
       weight=D(2)/(k+1) if name=='EMA' else a[2][i]/k if a[2][i] is not None else None
       if weight is not None:
        state=x if state is None else (D(2)*x+state*(k-1))/(k+1) if name=='EMA' else (a[2][i]*x+(k-a[2][i])*state)/k
        value=state
     else:
      if name!='COUNT' and k<=0:raise ValueError('NONPOSITIVE_WINDOW')
      window=a[0][:i+1] if k==0 else a[0][i-k+1:i+1] if i+1>=k else None
      if window is not None:
       if name=='COUNT' and k==0:
        known=[z for z in window if z is not None];value=D(sum(bool(z) for z in known)) if known else None
       elif all(z is not None for z in window):
        if name=='MA':value=sum(window)/k
        elif name=='COUNT':value=D(sum(bool(z) for z in window))
        elif name=='HHV':value=max(window)
        elif name=='LLV':value=min(window)
   out.append(value)
 else:raise ValueError('INVALID_AST')
 cache[ast]=out;return out
def expression(text,bars,variables=None,mode='prefix'):
 bars=normalize(bars);n=len(bars);env={k.upper():[r[k] for r in bars] for k in ['open','high','low','close','vol']};env.update(DRAWNULL=[None]*n,CURRBARSCOUNT=[D(1) if mode=='prefix' else D(n-i) for i in range(n)])
 if variables:
  if any(len(v)!=n for v in variables.values()):raise ValueError('VARIABLE_LENGTH')
  env.update(variables)
 with localcontext() as c:c.prec=28;return evaluate(Parser(text).parse(),env,n,{})
def compute(bars,mode='prefix'):
 if mode not in ('prefix','asof'):raise ValueError('BAD_MODE')
 if not bars:raise ValueError('EMPTY_HISTORY')
 bars=normalize(bars);n=len(bars);inv=inventory();env={k.upper():[r[k] for r in bars] for k in ['open','high','low','close','vol']};env.update(DRAWNULL=[None]*n,CURRBARSCOUNT=[D(1) if mode=='prefix' else D(n-i) for i in range(n)]);cache={};draws=[]
 with localcontext() as ctx:
  ctx.prec=28
  for a in inv['assignments']:env[a['name']]=evaluate(Parser(a['expression']).parse(),env,n,cache)
  for d in inv['drawings']:
   condition=evaluate(Parser(d['condition']).parse(),env,n,cache);y=evaluate(Parser(d['y']).parse(),env,n,cache);payload=evaluate(Parser(d['payload']).parse(),env,n,cache);draws.append((d,condition,y,payload))
 rows=[]
 for i,b in enumerate(bars):
  rows.append(dict(trade_date=b['trade_date'],ohlcv=b,values={a['name']:env[a['name']][i] for a in inv['assignments']},drawings=[dict(id=d['id'],kind=d['kind'],condition=boolean(co[i]),y=yy[i] if boolean(co[i]) is True else None,payload=pp[i],styles=d['styles']) for d,co,yy,pp in draws]))
 return dict(schema='REBUILT_EXACT_TEXT_FORMULA_CANDIDATE_V1',formula_sha256=SOURCE_SHA,mode=mode,field_count=51,drawing_count=22,native_tdx_equivalence_certified=False,training_eligible=False,trading_eligible=False,rows=rows)
def json_ready(x):
 if isinstance(x,D):return str(x)
 if isinstance(x,dict):return {k:json_ready(v) for k,v in x.items()}
 if isinstance(x,list):return [json_ready(v) for v in x]
 return x
