"""Reuse the frozen Par native detector body with persisted prefix primitives.

Replaces only the full-series computation, validity scan and output-loop scope.
Full raw/intermediate histories remain present for original detector invocations.
No revised detector formula, no display-value state inference and no data fetch.
"""
import argparse,ast,base64,functools,hashlib,importlib.util,json,subprocess,sys
from pathlib import Path
from native_state import decode,encode,digest

ADAPTER_SHA='751da7c1e9525244af51d165c6d2975a445c9ced097ec206b545b12632bb8a0c'


def run(par,state):
    request=dict(par=str(par),state=base64.b64encode(encode(state)).decode('ascii'))
    process=subprocess.run([sys.executable,'-B',str(Path(__file__).resolve()),'--worker'],input=json.dumps(request),text=True,capture_output=True,timeout=600)
    if process.returncode:raise RuntimeError(process.stderr[-5000:])
    return json.loads(process.stdout)


def worker():
    request=json.load(sys.stdin);par=Path(request['par']).resolve();state=decode(base64.b64decode(request['state'],validate=True))
    rows=state['raw_prefix']
    if not rows or state['count']!=len(rows) or state['last_date']!=rows[-1]['trade_date']:raise ValueError('STATE_PREFIX_BOUNDARY')
    path=par/'handoff/unified_candidate_20261102/native_adapter.py';data=path.read_bytes()
    if hashlib.sha256(data).hexdigest()!=ADAPTER_SHA:raise ValueError('ADAPTER_SOURCE_PIN')
    sys.path.insert(0,str(path.parent));spec=importlib.util.spec_from_file_location('frozen_par_native_adapter',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    seq=state['sequences'];names=dict(calculate_kdj='kdj',calculate_zg_white='white',calculate_dg_yellow='yellow',calculate_brick_value='brick',detect_double_line_cross='crosses',detect_brick_trend='trend')
    audit=dict(prefix_math_calls=0,historical_primitive_rows_recomputed=0,primitive_rows_appended=0,raw_rows_retained=len(rows),fallbacks={})
    def cached_series(bars,core):
        n=len(bars)
        return {target:seq[source][:n] for target,source in names.items()}
    def stored_validity(rows_,symbol):
        if symbol!=state['symbol'] or digest(rows_)!=digest(rows):raise ValueError('STATE_PREFIX_IDENTITY')
        return state['validity_history']
    original_bound=module.bound_lookup
    def counted_bound(name,original,bars,values):
        @functools.wraps(original)
        def uncached(prefix,*args,**kwargs):
            record=audit['fallbacks'].setdefault(name,dict(calls=0,max_rows=0));record['calls']+=1;record['max_rows']=max(record['max_rows'],len(prefix))
            # Original sliced-window KDJ (e.g.19 bars) is a bounded independent
            # series with a different seed; never substitute global prefix KD.
            if len(prefix)>max(120,len(rows)//2):raise ValueError('UNPROVEN_UNBOUNDED_PRIMITIVE_FALLBACK:'+name)
            return original(prefix,*args,**kwargs)
        return original_bound(name,uncached,bars,values)
    tree=ast.parse(data);fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='worker')
    changes=dict(request=0,series=0,validity=0,loop=0,output=0)
    class Transform(ast.NodeTransformer):
        def visit_Call(self,node):
            text=ast.unparse(node.func)
            if text=='json.load':
                changes['request']+=1;return ast.Name(id='_request',ctx=ast.Load())
            if text=='prefix_math.series':node.func=ast.Name(id='_cached_series',ctx=ast.Load());changes['series']+=1
            if text=='prefix_validity':node.func=ast.Name(id='_stored_validity',ctx=ast.Load());changes['validity']+=1
            if text=='print':
                payload=node.args[0].args[0]
                if not isinstance(payload,ast.Dict):raise ValueError('OUTPUT_AST')
                payload.keys.extend([ast.Constant('brick_values'),ast.Constant('recovery_diagnostic')])
                payload.values.extend([ast.parse("[seq['calculate_brick_value'][i] if i>=11 and validity[i][0] and validity[i][2] else None for i in range(len(rows))]",mode='eval').body,ast.Name(id='_audit',ctx=ast.Load())]);changes['output']+=1
            return self.generic_visit(node)
        def visit_For(self,node):
            if ast.unparse(node.target)=='n' and ast.unparse(node.iter)=='range(1, len(rows) + 1)':node.iter=ast.parse('(len(rows),)',mode='eval').body;changes['loop']+=1
            return self.generic_visit(node)
    fn=Transform().visit(fn)
    if changes!={k:1 for k in changes}:raise ValueError('SOURCE_TRANSFORM_COUNTS:'+str(changes))
    namespace={**vars(module),'_request':dict(rows=rows),'_cached_series':cached_series,'_stored_validity':stored_validity,'_audit':audit,'bound_lookup':counted_bound}
    code=ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[]));exec(compile(code,'<pinned-native-worker-state-reuse>','exec'),namespace);namespace['worker']()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--worker',action='store_true');a=p.parse_args()
    if not a.worker:raise SystemExit('Use run(par,state) from the isolated recovery validation harness')
    worker()
