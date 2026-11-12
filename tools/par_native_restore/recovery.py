"""Isolated Par109 recovery using exact pinned original composition and steps.

One original full-prefix initialization is allowed. Later days reuse native
binary64 accumulators and original foundation/N state. Original detector bodies
receive complete raw/history sequences; no truncation/dependency claim is made.
"""
import ast,copy,hashlib,importlib.util,inspect,json,sys
from pathlib import Path
from native_state import new_state,append,digest,NATIVE_CORE_SHA,encode,decode
from native_current import run as native_current

LATEST_SHA='4acf301445ce3c63fc0a3116e76a24bc9f7410474aa50de990ddc8cc350a25cd'
DEPENDENCIES_SHA='55ea05365621b45e374c4b68a61ab9a60e2af05e5b28244403de699cf6f455dc'


def file_sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


class Kernel:
    def __init__(self,par,latest,dependencies):
        self.par=Path(par).resolve();latest=Path(latest).resolve();dependencies=Path(dependencies).resolve()
        if file_sha(latest)!=LATEST_SHA or file_sha(dependencies)!=DEPENDENCIES_SHA:raise ValueError('ORIGINAL_LATEST_DEPENDENCY_PINS')
        self.dependencies=json.loads(dependencies.read_bytes())['dependencies']
        for ref in self.dependencies:
            p=self.par/ref['path']
            if p.stat().st_size!=ref['bytes'] or file_sha(p)!=ref['sha256']:raise ValueError('SOURCE_DEPENDENCY:'+ref['path'])
        unified=self.par/'handoff/unified_candidate_20261102';sys.path.insert(0,str(unified))
        for name in ('core','native_adapter','producer'):
            if name in sys.modules and Path(sys.modules[name].__file__).resolve()!=unified/(name+'.py'):raise ValueError('MODULE_IDENTITY_COLLISION:'+name)
        import producer
        self.producer=producer;self.modules,_=producer.module_candidates()
        source=ast.parse(latest.read_bytes());ns=dict(ast=ast,copy=copy,hashlib=hashlib,inspect=inspect,json=json,pathlib=__import__('pathlib'))
        names={'replace_once','foundation_step','score_step','numeric'}
        declarations=[n for n in source.body if isinstance(n,ast.FunctionDef) and n.name in names]
        if len(declarations)!=4:raise ValueError('LATEST_DECLARATION_CLOSURE')
        exec(compile(ast.Module(body=declarations,type_ignores=[]),str(latest),'exec'),ns);self.steps=ns
        self.pins={'producer.py':file_sha(unified/'producer.py'),'native_adapter.py':file_sha(unified/'native_adapter.py'),'foundation':file_sha(Path(self.modules['foundation'].__file__)),'score':file_sha(Path(self.modules['score'].__file__))}
        tree=ast.parse(inspect.getsource(producer.compute));loop=next(n for n in tree.body[0].body if isinstance(n,ast.For) and ast.unparse(n.target)=='(i, (r, n, f, s, k))')
        body=copy.deepcopy(loop.body);body[-1]=ast.Return(value=ast.Name(id='result',ctx=ast.Load()))
        fn=ast.FunctionDef(name='_compose_current',args=ast.arguments(posonlyargs=[],args=[ast.arg(arg=x) for x in ('i','r','n','f','s','k','events','schema','modules')],kwonlyargs=[],kw_defaults=[],defaults=[]),body=body,decorator_list=[])
        namespace=dict(vars(producer));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<original109-composition-only>','exec'),namespace)
        self.compose=namespace['_compose_current'];self.schema=json.loads((unified/'FIELD_SCHEMA_109.json').read_bytes())
        self.code_binding=dict(latest_sha256=LATEST_SHA,dependencies_sha256=DEPENDENCIES_SHA,original_pins=self.pins,recovery_implementation_sha256={name:file_sha(Path(__file__).with_name(name)) for name in ('recovery.py','native_state.py','native_current.py')})

    def initialize(self,rows,context,source_binding):
        """Run original full-prefix once; capture internal locals, never outputs->state."""
        p=self.producer;modules=self.modules;num=self.steps['numeric'](rows);native=p.native_adapter.run(num)
        captured={};foundation_code=modules['foundation'].project_history.__code__;score_code=modules['score']._iter_structures.__code__
        def profile(frame,event,arg):
            if event=='return' and frame.f_code is foundation_code:
                loc=frame.f_locals
                captured['foundation']=dict(count=len(rows),last_date=rows[-1]['event_date'],ef=loc['ef'],es=loc['es'],ed=loc['ed'],poison=loc['poison'],dif_tail=copy.deepcopy(loc['dif'][-60:]),dea_tail=copy.deepcopy(loc['dea'][-2:]))
            if event=='return' and frame.f_code is score_code and frame.f_locals.get('index')==len(rows)-1 and 'validity' in frame.f_locals:
                loc=frame.f_locals
                captured['n_score']=dict(count=len(rows),last_date=rows[-1]['event_date'],swings=copy.deepcopy(loc['swings']),ambiguous=copy.deepcopy(loc['ambiguous']),invalid=copy.deepcopy(loc['invalid']),post_ambiguity=copy.deepcopy(loc['post_ambiguity']),validity_tail=copy.deepcopy(loc['validity'][-10:]))
        old_profile=sys.getprofile()
        try:
            sys.setprofile(profile);original=p.compute(rows,context,modules,native=native)
        finally:sys.setprofile(old_profile)
        if set(captured)!={'foundation','n_score'}:raise ValueError('ORIGINAL_INTERNAL_STATE_CAPTURE')
        binding={**source_binding,'native_core_sha256':NATIVE_CORE_SHA,'initialized_numeric_prefix_sha256':digest(num)}
        numeric_state=new_state(context['symbol'],binding)
        for r in num:append(numeric_state,r,initialization=True)
        state=dict(schema='par.all109.native_recovery.candidate.v1',product_kind='NEW_RECOVERY_PRODUCT_NOT_HISTORIC_ORIGINAL',symbol=context['symbol'],count=len(rows),asof=rows[-1]['event_date'],context=copy.deepcopy(context),source_binding=copy.deepcopy(source_binding),code_binding=self.code_binding,original_rows=copy.deepcopy(rows),native_state=numeric_state,
          component109=dict(schema='ORIGINAL109_LATEST_COMPONENT_STATE_V1',symbol=context['symbol'],count=len(rows),last_date=rows[-1]['event_date'],original_pins=dict(self.pins),**captured,native_latest=copy.deepcopy(native['rows'][-1]),native_prefix_required=True,source_prefix_copied=True),
          latest109=original[-1],detector_dependency_closed=False,all109_compatibility_certified=False,
          counters=dict(original_full_prefix_initializations=1,native_full_prefix_initializations=1,daily_rows=0,historical_primitive_rows_recomputed_daily=0),
          RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
        return original[-1],state

    def step(self,state,row):
        if state['schema']!='par.all109.native_recovery.candidate.v1' or state['code_binding']!=self.code_binding:raise ValueError('RECOVERY_CODE_BINDING')
        if row['symbol']!=state['symbol'] or row['event_date']<=state['asof']:raise ValueError('ROW_IDENTITY_DATE')
        # Clone via binary codec to preserve rollback and binary64 payloads.
        state=decode(encode(state));rows=state['original_rows'];rows.append(copy.deepcopy(row));context={**state['context'],'asof':row['event_date']}
        self.producer.core.validate_rows(rows,context)
        new_numeric=self.steps['numeric']([row])[0];append(state['native_state'],new_numeric);num=state['native_state']['raw_prefix']
        native=native_current(self.par,state['native_state']);audit=native['recovery_diagnostic']
        if native['guard_violations'] or len(native['rows'])!=1 or native['rows'][0]['event_date']!=row['event_date']:raise ValueError('NATIVE_CURRENT_IDENTITY')
        n=native['rows'][0];prior=state['component109'];modules=self.modules
        f,fs=self.steps['foundation_step'](modules['foundation'],num,prior['foundation'])
        components=[dict(event_date=r['event_date']) for r in rows];components[-1].update(n['kb_components'])
        s,ss=self.steps['score_step'](modules['score'],rows,{**context,'components':components,'components_admitted':True},prior['n_score'])
        nf=n['fields'];reuse=dict(event_date=row['event_date'],brick_value=nf['kb_brick_value']['value'],fanbao_original=nf['kb_fanbao']['value'],fanbao_original_status=nf['kb_fanbao']['status'],rebuild_repaired=n['rebuild_repaired'],rebuild_status='SOURCE_THREE_EDIT_REPAIRED',bowl_status=nf['kb_in_bowl']['status'])
        valid=state['native_state']['validity']['input_prefix']
        if valid!=n['event']['input_valid']:raise ValueError('INPUT_VALIDITY_MISMATCH')
        k=modules['kb8'].project_prefix(len(rows),row['event_date'],native['brick_values'],reuse,n['event']['raw'],modules['kb8_rule_sha'],input_reason=None if valid else 'INVALID_INPUT',symbol=state['symbol'])
        events=[None]*(len(rows)-1)+[n['event']]
        result=self.compose(len(rows)-1,row,n,f,s,k,events,self.schema,modules)
        state.update(count=len(rows),asof=row['event_date'],context=context,component109=dict(schema='ORIGINAL109_LATEST_COMPONENT_STATE_V1',symbol=state['symbol'],count=len(rows),last_date=row['event_date'],original_pins=dict(self.pins),foundation=fs,n_score=ss,native_latest=copy.deepcopy(n),native_prefix_required=True,source_prefix_copied=True))
        state['latest109']=result;state['counters']['daily_rows']+=1
        return result,state,audit
