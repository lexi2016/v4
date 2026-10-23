"""Deterministic predicate boundaries and independent scalar primitive replay."""
import math
from datetime import datetime,timedelta
import numpy as np
import formula_kernel as k

class Reference:
    def __init__(self,raw):self.raw={a:list(map(float,b)) for a,b in raw.items()};self.n=len(raw['C']);self.memo={};self.nodes,self.alias,self.reverse=k.program()
    def named(self,name):
        if name in self.memo:return self.memo[name]
        if name in self.raw:return self.raw[name]
        if name=='CURRBARSCOUNT':return list(range(self.n,0,-1))
        self.memo[name]=self.expr(self.nodes[name]);return self.memo[name]
    def expr(self,node):
        if node.kind=='number':return [node.value]*self.n
        if node.kind=='name':return self.named(self.reverse.get(node.value,node.value))
        if node.kind=='unary':return [x*(-1 if node.value=='-' else 1) for x in self.expr(node.children[0])]
        if node.kind=='call':return self.call(node.value,[self.expr(x) for x in node.children])
        a,b=[self.expr(x) for x in node.children];out=[]
        for x,y in zip(a,b):
            valid=math.isfinite(x) and math.isfinite(y);op=node.value
            if op=='AND':z=0 if x==0 or y==0 else 1 if valid else math.nan
            elif op=='OR':z=1 if (math.isfinite(x) and x!=0) or (math.isfinite(y) and y!=0) else 0 if valid else math.nan
            elif not valid:z=math.nan
            elif op=='+':z=x+y
            elif op=='-':z=x-y
            elif op=='*':z=x*y
            elif op=='/':z=x/y if y!=0 else math.nan
            else:z=float({'=':lambda:x==y,'<':lambda:x<y,'>':lambda:x>y,'<=':lambda:x<=y,'>=':lambda:x>=y}[op]())
            out.append(z)
        return out
    def call(self,name,args):
        a=args[0];n=self.n;out=[math.nan]*n
        if name in ('MIN','MAX'):return [(min(x,y) if name=='MIN' else max(x,y)) if math.isfinite(x) and math.isfinite(y) else math.nan for x,y in zip(a,args[1])]
        if name=='IF':return [math.nan if not math.isfinite(flag) else x if flag!=0 else y for flag,x,y in zip(a,args[1],args[2])]
        if name=='REF':
            for i,v in enumerate(args[1]):
                if math.isfinite(v) and v>=0 and int(v)==v and v<=i:out[i]=a[i-int(v)]
        elif name=='CROSS':
            out[0]=0
            for i in range(1,n):
                x,y,z,w=a[i],args[1][i],a[i-1],args[1][i-1]
                if all(math.isfinite(v) for v in (x,y,z,w)):out[i]=float(x>y and z<=w)
        elif name=='BARSLAST':
            distance=None
            for i,x in enumerate(a):
                if not math.isfinite(x):distance=None
                elif x!=0:distance=0
                elif distance is not None:distance+=1
                if distance is not None:out[i]=distance
        elif name=='COUNT':
            for i,width in enumerate(args[1]):
                if not math.isfinite(width) or width<0 or int(width)!=width:continue
                count=i+1 if width==0 else int(width)
                if count>i+1:continue
                segment=a[i-count+1:i+1]
                if all(math.isfinite(x) for x in segment):out[i]=sum(x!=0 for x in segment)
        elif name in ('EMA','SMA'):
            period=int(args[1][0]);weight=2/(period+1) if name=='EMA' else args[2][0]/period;state=None;unknown=False
            for i,x in enumerate(a):
                if not math.isfinite(x):unknown=unknown or state is not None or name=='EMA';continue
                if unknown:continue
                state=x if state is None else weight*x+(1-weight)*state;out[i]=state
        else:
            width=int(args[1][0])
            for i in range(width-1,n):
                segment=a[i-width+1:i+1]
                if all(math.isfinite(x) for x in segment):out[i]={'MA':lambda:sum(segment)/width,'HHV':lambda:max(segment),'LLV':lambda:min(segment)}[name]()
        return out

def assert_values(a,b):np.testing.assert_allclose(a,b,rtol=1e-11,atol=1e-10,equal_nan=True)
def dates(n):return [(datetime(2026,10,22)-timedelta(days=n-i-1)).strftime('%Y%m%d') for i in range(n)]
def synthetic_streams():
    t=np.arange(720,dtype=float)
    streams=[]
    for trend in [0.012,-0.008,0.0]:
        close=30+trend*t+1.2*np.sin(t/5)+.7*np.sin(t/17)
        volume=100000*(1+.3*np.sin(t/3));volume[::29]*=2.4
        # Predeclared jumps/pullbacks exercise first breaks and following-day observations.
        for j in range(150,700,50):
            close[j:]+=2.5;volume[j]*=3
            close[j+1]+=.2 if j%100==50 else -.2;volume[j+1]=volume[j]*(.95 if j%100==50 else .7)
        streams.append({'C':close,'H':close+.25,'L':close-.3,'VOL':volume})
    # A fixed bearish oscillation has successive crossings while DEA remains below zero.
    close=100-.08*t+np.sin(t/5)
    streams.append({'C':close,'H':close+.25,'L':close-.3,'VOL':np.ones(len(t))*100000})
    return streams

def boundaries():
    checks=[];e=k.Engine({'C':np.ones(160)*10,'H':np.ones(160)*11,'L':np.ones(160)*9,'VOL':np.ones(160)*100})
    # Test the actual source AST with controlled indicator values; no replacement predicate.
    def setval(name,value):e.memo[name]=np.full(160,value,dtype=float)
    setval('BBI',12);setval('白线',11);setval('黄线',10);setval('J',13)
    assert e.expr(e.nodes['B1'])[-1]==1;checks.append('B1_J_13_INCLUSIVE')
    setval('白线',12);assert e.expr(e.nodes['B1'])[-1]==0;checks.append('B1_EQUAL_LINE_REJECTED')
    setval('白线',11);setval('J',0);assert e.expr(e.nodes['B1'])[-1]==1;checks.append('B1_ZERO_J_VALID_NO_SCORE_OR_CLOSE_GATE')
    for value,want in [(.6,1),(.9,1),(.59999,0),(.90001,0)]:
        setval('VOLR',value);setval('昨日放量',1);setval('昨日涨幅',5);assert e.expr(e.nodes['四分之三量'])[-1]==want
    checks.append('THREE_QUARTER_VOLUME_INCLUSIVE_06_09')
    setval('长期',75);setval('短期',25);assert e.expr(e.nodes['单针下20'])[-1]==1;checks.append('NEEDLE_75_25_INCLUSIVE')
    setval('今日涨幅',1);setval('昨日突破前高',1);setval('真突破',1)
    e.memo['昨日突破前高'][-8:-1]=0
    assert e.expr(e.nodes['突破接十字星'])[-1]==1;checks.append('BREAKOUT_DOJI_NO_EXTRA_BODY_GATE')
    a=np.zeros(160);a[[10,20,22]]=1;period=np.full(160,0.0);period[23:]=4
    result=e.call('COUNT',[a,period]);assert result[22]==3 and result[23]==2;checks.append('DYNAMIC_COUNT_ZERO_FULL_PREFIX_AND_LAST_N')
    assert np.isnan(e.call('BARSLAST',[np.zeros(160)])).all();checks.append('BARSLAST_NO_ANCHOR_UNKNOWN')
    cross=e.call('CROSS',[np.array([0,1]+[1]*158,dtype=float),np.zeros(160)]);assert cross[1]==1 and cross[0]==0;checks.append('CROSS_STRICT_CURRENT_PREVIOUS_EQUAL_ALLOWED')
    # M2+ accepts the third crossing; M2- retains outer dynamic-count equality event semantics.
    setval('金叉',1);setval('DEA',1);setval('零上金次',3);assert e.expr(e.nodes['零上二金'])[-1]==1;checks.append('M2_PLUS_GE2_NOT_EXACTLY2')
    setval('DEA',-1);e.memo['零下金次']=np.ones(160);e.memo['零下金次'][-1]=2
    assert e.expr(e.nodes['零下二金'])[-1]==1;e.memo['零下金次'][-2]=2;assert e.expr(e.nodes['零下二金'])[-1]==0;checks.append('M2_MINUS_OUTER_COUNT_EQUALITY_NOT_SIMPLIFIED')
    env=k.brick_functions();native=env['detect_fanbao'];original=env['calculate_brick_value']
    try:
        env['calculate_brick_value']=lambda rows:{14:2.,13:0.,12:3.}[len(rows)]
        assert not native([None]*14)
        env['calculate_brick_value']=lambda rows:{14:2.01,13:0.,12:3.}[len(rows)]
        assert native([None]*14);checks.append('NATIVE_BRICK_TWO_THIRDS_EQUAL_FALSE_ABOVE_TRUE')
    finally:env['calculate_brick_value']=original
    return checks

def run(samples):
    primitive_checks=boundaries();comparison=[];found={};multiple=False
    streams=synthetic_streams()
    for index,raw in enumerate(streams):
        engine=k.Engine(raw);reference=Reference(raw)
        for name in list(k.TRACE_NAMES)+[x for x in k.RULES.values() if x!='BRICK_FANBAO']:
            assert_values(engine.named(name),reference.named(name))
        comparison.append(dict(kind='FIXED_SYNTHETIC_PRIMITIVE_TRACE',stream=index,rows=len(raw['C'])))
        for rule_id,name in k.RULES.items():
            if rule_id=='BRICK_FANBAO':continue
            hit=np.flatnonzero(engine.named(name)==1)
            # The source expression already enforces its own valid prerequisites.
            # MA114 belongs to yellow-line rules, not to the MACD-only M2 routes.
            if len(hit) and rule_id not in found:
                end=int(hit[0])+1;prefix={key:value[:end] for key,value in raw.items()};row=k.evaluate_stock('600000.SH',dates(end),prefix)
                assert rule_id in row['hit_rules'];found[rule_id]=dict(stream=index,history_rows=end,hit_rules=row['hit_rules'],candidate=row['candidate']);multiple|=len(row['hit_rules'])>1
        if 'BRICK_FANBAO' not in found:
            for end in range(14,100):
                prefix={key:value[:end] for key,value in raw.items()};row=k.evaluate_stock('600000.SH',dates(end),prefix)
                if 'BRICK_FANBAO' in row['hit_rules']:found['BRICK_FANBAO']=dict(stream=index,history_rows=end,hit_rules=row['hit_rules'],candidate=row['candidate']);break
    # Deterministic, explicitly designed single-needle shape (not a market parameter search).
    close=np.array([10.]*130+[22.,21.,20.]);raw={'C':close,'H':close+.2,'L':np.concatenate([np.ones(130)*9.8,[21.8,20.8,19.8]]),'VOL':np.ones(len(close))*100000}
    needle=k.evaluate_stock('600000.SH',dates(len(close)),raw)
    if 'SINGLE_NEEDLE' in needle['hit_rules']:found['SINGLE_NEEDLE']=dict(stream='EXPLICIT_NEEDLE_SHAPE',history_rows=len(close),hit_rules=needle['hit_rules'],candidate=needle['candidate'])
    assert set(found)==set(k.RULES),'MISSING_ROUTE_TRUE_FIXTURE:'+str(set(k.RULES)-set(found))
    assert multiple,'NO_MULTI_LABEL_FIXTURE'
    real=[]
    for sample in samples:
        raw={name:np.asarray(values,dtype=float) for name,values in sample['raw'].items()};row,engine=k.evaluate_stock(sample['code'],sample['dates'],raw,return_engine=True);reference=Reference(raw)
        for name in list(k.TRACE_NAMES)+[x for x in k.RULES.values() if x!='BRICK_FANBAO']:assert_values(engine.named(name),reference.named(name))
        again=k.evaluate_stock(sample['code'],sample['dates'],raw);assert row==again
        future_dates=sample['dates']+['20261023'];future_raw={name:np.append(values,999999.) for name,values in raw.items()}
        mask=np.array([d<='20261022' for d in future_dates]);bounded=k.evaluate_stock(sample['code'],[d for d in future_dates if d<='20261022'],{name:values[mask] for name,values in future_raw.items()});assert row==bounded
        try:k.evaluate_stock(sample['code'],future_dates,future_raw)
        except AssertionError:pass
        else:raise AssertionError('FUTURE_PREFIX_ACCEPTED')
        short=k.evaluate_stock(sample['code'],sample['dates'][-14:],{name:values[-14:] for name,values in raw.items()})
        assert next(x for x in short['rules'] if x['rule_id']=='BRICK_FANBAO')['value'] is not None
        assert next(x for x in short['rules'] if x['rule_id']=='B1')['value'] is None or short['candidate'] in ('YES','UNKNOWN','NO')
        no_volume={name:values.copy() for name,values in raw.items()};no_volume['VOL'][-1]=np.nan
        partial=k.evaluate_stock(sample['code'],sample['dates'],no_volume)
        assert next(x for x in partial['rules'] if x['rule_id']=='B1')['value']==next(x for x in row['rules'] if x['rule_id']=='B1')['value']
        real.append(dict(code=sample['code'],history_rows=len(sample['dates']),history_start=sample['dates'][0],history_end=sample['dates'][-1],hit_rules=row['hit_rules'],state=row['execution_status'],independent_scalar_trace_parity=True))
    return dict(status='WRITER_CANARY_CHECKS_PASS_PENDING_INDEPENDENT_REVIEW',primitive_boundary_checks=primitive_checks,true_fixtures=found,multi_label_retained=True,real_samples=real,independent_scalar_comparison=comparison,implementation_status='FORMULA_FILE_REPLICA_NOT_LIVE_PLATFORM_PARITY')

if __name__=='__main__':
    import json,sys
    def deny(event,args):
        if event.startswith(('socket.','sqlite3.connect','subprocess.Popen')):raise RuntimeError('FORBIDDEN_PROVIDER')
    sys.addaudithook(deny)
    samples=json.loads(__import__('pathlib').Path(sys.argv[1]).read_text())
    print(json.dumps(run(samples),ensure_ascii=False,allow_nan=False))
