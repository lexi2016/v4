"""Source-file formula replica with explicit unknown semantics; no platform parity claim."""
from __future__ import annotations
import ast,hashlib,importlib.util,math,re
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
FORMULA=Path('/Users/lexi/Desktop/学习/agents调试/Z哥方法论/个股学习/b123_four_cases_20261021/futu_source/ACTIVE_MA_USER_20261021.txt')
PARSER=Path('/Users/lexi/Desktop/学习/因子工厂/worktrees/mac_tdx_month_compare_20261021/research/mac_tdx_month_compare_20261021/formula_replay_v1/original_formula.py')
UPSTREAM=HERE.parent/'upstream/modules/indicators'
RULES={'B1':'B1','B2':'B2','B3':'B3','BREAKOUT':'突破','BREAKOUT_DOJI':'突破接十字星','M2_MINUS':'零下二金','M2_PLUS':'零上二金','SINGLE_NEEDLE':'单针下20','THREE_QUARTER_YIN':'四分之三阴量线','BRICK_FANBAO':'BRICK_FANBAO'}
RISKS=['破前低','黄线下','飞1','飞2','死叉','卖点','昨日守线']
TRACE_NAMES=['BBI','白线','黄线','J','今日涨幅','昨日涨幅','昨日放量','VOLR','真突破','近20日高点','破前高','昨日突破前高','四分之三量','短期','长期','DIF','DEA','金叉','零下金次','零上金次']
_CACHE=None

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def canonical_sha(x):return hashlib.sha256(__import__('json').dumps(x,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def scalar(x):return float(x) if np.isfinite(x) else None
def kleene(a,b,op):
    valid=np.isfinite(a)&np.isfinite(b)
    if op=='AND':return np.where((a==0)|(b==0),0,np.where(valid,1,np.nan))
    return np.where((np.isfinite(a)&(a!=0))|(np.isfinite(b)&(b!=0)),1,np.where(valid,0,np.nan))

def program():
    global _CACHE
    if _CACHE is not None:return _CACHE
    assert sha(FORMULA)=='924ab78f0adb0ee0705e41d7824282f40ec275a97da532ffee5b61e29d2925e6'
    spec=importlib.util.spec_from_file_location('broad_source_parser',PARSER);m=importlib.util.module_from_spec(spec);__import__('sys').modules[spec.name]=m;spec.loader.exec_module(m)
    expressions={}
    for statement in FORMULA.read_text(encoding='utf-8-sig').split(';'):
        match=re.match(r'^\s*([\w]+)\s*(?::=|:)\s*(.*)$',statement,re.S)
        if not match:continue
        name,expression=match.groups();depth=0;end=len(expression)
        for i,ch in enumerate(expression):
            depth+=int(ch=='(')-int(ch==')')
            if ch==',' and depth==0:end=i;break
        expressions[name]=expression[:end].strip()
    aliases={name:'V'+str(i) for i,name in enumerate(expressions)}
    aliases.update(CLOSE='C',HIGH='H',LOW='L',VOL='VOL',CURRBARSCOUNT='CURRBARSCOUNT')
    compiled={}
    for name,expression in expressions.items():
        if 'DRAWNULL' in expression:continue
        translated=re.sub(r'[^\W\d]\w*',lambda x:aliases.get(x.group(),x.group()),expression)
        parser=m.Parser(translated);node=parser.expression();assert parser.peek() is None,(name,translated)
        compiled[name]=node
    reverse={v:k for k,v in aliases.items() if k in compiled}
    _CACHE=(compiled,aliases,reverse);return _CACHE

class Engine:
    def __init__(self,raw):
        self.n=len(raw['C']);self.raw={k:np.asarray(v,dtype=float).copy() for k,v in raw.items()};self.memo={};self.nodes,self.alias,self.reverse=program()
        assert all(len(x)==self.n for x in self.raw.values())
    def arr(self,x):return np.full(self.n,x,dtype=float) if np.isscalar(x) else np.asarray(x,dtype=float)
    def named(self,name):
        if name in self.memo:return self.memo[name]
        if name in self.raw:return self.raw[name]
        if name=='CURRBARSCOUNT':return np.arange(self.n,0,-1,dtype=float)
        self.memo[name]=self.expr(self.nodes[name]);return self.memo[name]
    def expr(self,node):
        if node.kind=='number':return self.arr(node.value)
        if node.kind=='name':return self.named(self.reverse.get(node.value,node.value))
        if node.kind=='unary':return self.expr(node.children[0])*(-1 if node.value=='-' else 1)
        if node.kind=='call':return self.call(node.value,[self.expr(x) for x in node.children])
        a,b=[self.expr(x) for x in node.children];op=node.value
        if op in ('AND','OR'):return kleene(a,b,op)
        if op in ('=','<','>','<=','>='):
            cmp={'=':np.equal,'<':np.less,'>':np.greater,'<=':np.less_equal,'>=':np.greater_equal}[op]
            return np.where(np.isfinite(a)&np.isfinite(b),cmp(a,b).astype(float),np.nan)
        with np.errstate(divide='ignore',invalid='ignore',over='ignore'):
            if op=='+':out=a+b
            elif op=='-':out=a-b
            elif op=='*':out=a*b
            elif op=='/':out=np.divide(a,b,out=np.full(self.n,np.nan),where=np.isfinite(b)&(b!=0))
            else:raise ValueError(op)
        out[~np.isfinite(out)]=np.nan;return out
    def call(self,name,args):
        a=args[0];n=self.n
        if name in ('MIN','MAX'):return (np.minimum if name=='MIN' else np.maximum)(a,args[1])
        if name=='IF':return np.where(np.isfinite(a),np.where(a!=0,args[1],args[2]),np.nan)
        if name=='REF':
            offsets=args[1];out=np.full(n,np.nan)
            for i,v in enumerate(offsets):
                if np.isfinite(v) and v>=0 and v==int(v) and v<=i:out[i]=a[i-int(v)]
            return out
        if name=='BARSLAST':
            out=np.full(n,np.nan);last=None
            for i,x in enumerate(a):
                if not np.isfinite(x):last=None
                elif x!=0:last=i
                if last is not None:out[i]=i-last
            return out
        if name=='CROSS':
            out=np.full(n,np.nan);out[0]=0
            if n>1:
                b=args[1];valid=np.isfinite(a[1:])&np.isfinite(b[1:])&np.isfinite(a[:-1])&np.isfinite(b[:-1])
                out[1:]=np.where(valid,((a[1:]>b[1:])&(a[:-1]<=b[:-1])).astype(float),np.nan)
            return out
        if name=='COUNT':
            out=np.full(n,np.nan);periods=args[1]
            for i,p in enumerate(periods):
                if not np.isfinite(p) or p<0 or p!=int(p):continue
                width=i+1 if p==0 else int(p)
                if width>i+1:continue
                window=a[i-width+1:i+1]
                if np.isfinite(window).all():out[i]=np.count_nonzero(window)
            return out
        p=args[1]
        assert np.isfinite(p).all() and np.all(p==p[0]) and p[0]>0 and p[0]==int(p[0]),name
        period=int(p[0])
        if name in ('EMA','SMA'):
            alpha=2/(period+1) if name=='EMA' else float(args[2][0])/period
            out=np.full(n,np.nan);previous=None;poisoned=False
            for i,value in enumerate(a):
                if not np.isfinite(value):
                    if previous is not None or name=='EMA':poisoned=True
                    continue
                if poisoned:continue
                previous=value if previous is None else alpha*value+(1-alpha)*previous;out[i]=previous
            return out
        rolling=pd.Series(a).rolling(period,min_periods=period)
        return getattr(rolling,{'MA':'mean','HHV':'max','LLV':'min'}[name])().to_numpy()

@lru_cache(maxsize=1)
def brick_functions():
    env={'DailyData':SimpleNamespace,'calculate_ma':None,'calculate_slope':None,'calculate_zg_white':None}
    for path,names in [(UPSTREAM/'core.py',['calculate_sma_series']),(UPSTREAM/'price_patterns/brick.py',['calculate_brick_value']),(UPSTREAM/'price_patterns/screener_helper.py',['detect_fanbao'])]:
        tree=ast.parse(path.read_text());selected=[x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name in names];assert len(selected)==len(names)
        exec(compile(ast.Module(body=selected,type_ignores=[]),str(path),'exec'),env)
    return env

def evaluate_stock(code,dates,raw,signal_date='20261022',return_engine=False):
    assert dates and dates==sorted(set(dates)) and dates[-1]==signal_date and max(dates)<=signal_date
    columns={k:np.asarray(raw[k],dtype=float).copy() for k in ['C','H','L','VOL']}
    for k,a in columns.items():
        a[~np.isfinite(a)]=np.nan
        a[a<0 if k=='VOL' else a<=0]=np.nan
    c,h,l=[columns[k] for k in ['C','H','L']]
    bad=np.isfinite(c)&np.isfinite(h)&np.isfinite(l)&((h<c)|(l>c)|(h<l))
    for key in ['C','H','L']:columns[key][bad]=np.nan
    engine=Engine(columns);rules=[]
    for rule_id,name in RULES.items():
        if rule_id=='BRICK_FANBAO':
            if len(dates)<14:state=None;reason='BRICK_REQUIRES_14_VALID_BARS';detail={}
            elif not all(np.isfinite(columns[k]).all() for k in ['C','H','L']):state=None;reason='BRICK_FULL_PREFIX_HLC_UNAVAILABLE';detail={}
            else:
                env=brick_functions();bars=[SimpleNamespace(close=x,high=y,low=z) for x,y,z in zip(c,h,l)]
                state=bool(env['detect_fanbao'](bars));reason=None
                values=[env['calculate_brick_value'](bars[:len(bars)-offset]) for offset in [2,1,0]]
                detail=dict(brick_before=values[0],brick_yesterday=values[1],brick_today=values[2],threshold=values[1]+(values[0]-values[1])*2/3)
        else:
            value=engine.named(name)[-1];state=bool(value!=0) if np.isfinite(value) else None;reason=None if state is not None else 'REQUIRED_HISTORY_OR_NUMERIC_VALUE_UNAVAILABLE';detail={}
        rules.append(dict(rule_id=rule_id,source_name=name,status='TRIGGERED' if state is True else 'NOT_TRIGGERED' if state is False else 'DATA_UNAVAILABLE',value=state,reason=reason,evidence=detail))
    hits=[r['rule_id'] for r in rules if r['value'] is True];unknown=[r['rule_id'] for r in rules if r['value'] is None]
    result=dict(code=code,signal_date=signal_date,history_start=dates[0],history_end=dates[-1],history_rows=len(dates),rules=rules,hit_rules=hits,unknown_rules=unknown,candidate='YES' if hits else 'UNKNOWN' if unknown else 'NO',execution_status='COMPLETE' if not unknown else 'FAILED' if len(unknown)==10 else 'PARTIAL',raw_invalid_counts={k:int(np.count_nonzero(~np.isfinite(v))) for k,v in columns.items()},indicators={name:scalar(engine.named(name)[-1]) for name in TRACE_NAMES},risks={name:scalar(engine.named(name)[-1]) for name in RISKS},implementation_status='FORMULA_FILE_REPLICA_NOT_LIVE_PLATFORM_PARITY')
    return (result,engine) if return_engine else result
