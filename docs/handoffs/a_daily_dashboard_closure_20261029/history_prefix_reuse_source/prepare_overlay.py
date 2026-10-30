"""Bounded C6 overlay generation from the accepted C5 producer, no live writes."""
from pathlib import Path
import ast,difflib,hashlib,json,subprocess,tempfile
ROOT=Path(__file__).resolve().parents[4];HERE=Path(__file__).resolve().parent
C5=ROOT/'docs/handoffs/a_daily_dashboard_closure_20261029/a_daily_1540_source';inventory=json.loads((C5/'OVERLAY_INVENTORY.json').read_text());name='ops/research_panel_daily_product.py';patch=(C5/'CANDIDATE_OVERLAY.patch').read_text();start=patch.index('--- a/'+name+'\n');end=patch.find('\n--- a/',start+1);segment=patch[start:] if end<0 else patch[start:end+1]
base=subprocess.run(['git','show',inventory['C4_commit']+':'+name],cwd=ROOT,check=True,capture_output=True).stdout
with tempfile.TemporaryDirectory(prefix='v4-c6-prepare-') as td:
 t=Path(td)/name;t.parent.mkdir();t.write_bytes(base);subprocess.run(['git','apply','-'],cwd=td,input=segment.encode(),capture_output=True,check=True);before=t.read_text()
assert hashlib.sha256(before.encode()).hexdigest()=='5104a091009f8dc7257a5f8ede7354a242be92bac03027e4d367485fbdb5334f'
text=before.replace('def source_inputs(context,symbol,bars,asof,qualification,*,retain=None):','def source_inputs(context,symbol,bars,asof,qualification,*,retain=None,prefix_reuse=None):',1)
old=" engine=context.engine();result=engine.compute(bars,'prefix');\n if retain is not None:retain(result)\n rows=result['rows'];last=rows[-1];"
new=''' engine=context.engine()
 if prefix_reuse is None:
  result=engine.compute(bars,'prefix')
  if retain is not None:retain(result)
  rows=result['rows']
 else:
  fields=('B1','B2','B3','突破','突破接十字星','零上二金','零下二金','一级买点','二级买点')
  if retain is not None or prefix_reuse.get('fields')!=fields:raise ValueError('CANNOT_CONFIRM_PREFIX_REUSE_CONSUMED_FIELDS')
  pins={'engine':'ae4243ec9582055fb6f2ee796978ad20e17f9dee7a56388063cbdbcb56ef0d1c','formula':'d35c9a30d7133420272ee5a2014f67ce64c0c7cd5a5ef9c16b846c025e2a05ac','tri_state_core':'e5bbeed5cfa665ef863f0cacb0bb6b13a17ebe957c1429eaaa8dea0acaf44a35','census':'75ed99318a149f2b57cbedd42618e5d5910d60ae2dd11f7fcb159c3fb3a6f2ef'}
  if any(context.config[k]['sha256']!=value or context.cached_sha(Path(context.config[k]['path']))!=value for k,value in pins.items()):raise ValueError('CANNOT_CONFIRM_PREFIX_CAUSALITY_PINS')
  if context.cached_sha(Path(context.config_ref['path']))!=context.config_ref['sha256']:raise ValueError('CANNOT_CONFIRM_PREFIX_CONFIG_DRIFT')
  if (prefix_reuse.get('symbol')!=symbol or prefix_reuse.get('generation')!=context.generation
      or prefix_reuse.get('identity')!=digest(context.identity) or prefix_reuse.get('config')!=digest(context.config)
      or prefix_reuse.get('config_ref')!=digest(context.config_ref) or prefix_reuse.get('qualification')!=digest(qualification) or prefix_reuse.get('target')!=context.target
      or not bars or bars[-1]['trade_date']!=int(asof) or int(asof)>context.target
      or tuple(b['trade_date'] for b in bars)!=prefix_reuse['dates'][:len(bars)]
      or digest(bars)!=prefix_reuse['prefix_sha256'].get(int(asof))):raise ValueError('CANNOT_CONFIRM_PREFIX_REUSE_IDENTITY_OR_PREFIX_DRIFT')
  proof_key=tuple((k,context.config[k]['path'],v) for k,v in pins.items())
  if getattr(context,'_history_prefix_causal_proof',None)!=proof_key:
   assignments={a['name']:engine.Parser(a['expression']).parse() for a in engine.inventory()['assignments']};proved=set();visiting=set()
   def visit(node):
    kind=node[0]
    if kind=='var':
     variable=node[1]
     if variable in {'OPEN','HIGH','LOW','CLOSE','VOL','DRAWNULL'}:return
     if variable not in assignments or variable in visiting:raise ValueError('CANNOT_CONFIRM_PREFIX_NONCAUSAL_VARIABLE:'+variable)
     if variable not in proved:
      visiting.add(variable);visit(assignments[variable]);visiting.remove(variable);proved.add(variable)
    elif kind=='call':
     if node[1] not in {'MA','EMA','SMA','REF','COUNT','BARSLAST','CROSS','HHV','LLV'}:raise ValueError('CANNOT_CONFIRM_PREFIX_NONCAUSAL_FUNCTION:'+node[1])
     for argument in node[2]:visit(argument)
    elif kind=='binary':visit(node[2]);visit(node[3])
    elif kind=='unary':visit(node[2])
    elif kind not in {'number','text'}:raise ValueError('CANNOT_CONFIRM_PREFIX_AST_UNKNOWN')
   for field in fields:visit(('var',field))
   context._history_prefix_causal_proof=proof_key
  rows=list(prefix_reuse['rows'][:len(bars)])
 last=rows[-1];'''
assert old in text;text=text.replace(old,new,1)
text=text.replace('def compute_stock(context,symbol,*,evaluate=None,history_dates=(),chart_capture=None):','def compute_stock(context,symbol,*,evaluate=None,history_dates=(),chart_capture=None,reuse_history_prefix=False):',1)
text=text.replace(' evaluate=evaluate or evaluate_daily_product;bars,name=context.read(symbol);',' history_dates=tuple(history_dates)\n evaluate=evaluate or evaluate_daily_product;bars,name=context.read(symbol);',1)
text=text.replace("({'retain':captured.append} if chart_capture is not None else {})", "({'retain':captured.append} if chart_capture is not None or (reuse_history_prefix and history_dates) else {})",1)
old=''' # Current admission authorizes this full prefix; each historical formula is
 # recomputed on its own slice. This is descriptive replay, never historical PIT.
 for day in history_dates:'''
new=''' # Explicit reuse is opt-in. Census/G4/qualification still use each cutoff;
 # only proven causal formula fields may come from the exact same full start.
 prefix_reuse=None
 if reuse_history_prefix and history_dates and q['status']=='CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH':
  from types import MappingProxyType
  if not captured:raise ValueError('CANNOT_CONFIRM_PREFIX_FULL_RESULT_MISSING')
  result=captured[0];fields=('B1','B2','B3','突破','突破接十字星','零上二金','零下二金','一级买点','二级买点');dates=tuple(b['trade_date'] for b in bars)
  if (result.get('mode')!='prefix' or result.get('formula_sha256')!=context.config['formula']['sha256'] or result.get('field_count')!=51 or result.get('drawing_count')!=22
      or tuple(r['trade_date'] for r in result['rows'])!=dates):raise ValueError('CANNOT_CONFIRM_PREFIX_FULL_RESULT_IDENTITY')
  chain=hashlib.sha256(b'[');prefix_hashes={}
  for index,bar in enumerate(bars):
   if index:chain.update(b',')
   chain.update(canonical(bar));point=chain.copy();point.update(b']');prefix_hashes[bar['trade_date']]=point.hexdigest()
  frozen_rows=tuple(MappingProxyType(dict(trade_date=r['trade_date'],ohlcv=MappingProxyType(dict(r['ohlcv'])),values=MappingProxyType({field:r['values'][field] for field in fields}))) for r in result['rows'])
  prefix_reuse=MappingProxyType(dict(symbol=symbol,generation=context.generation,identity=digest(context.identity),config=digest(context.config),config_ref=digest(context.config_ref),qualification=digest(q),target=context.target,fields=fields,dates=dates,prefix_sha256=MappingProxyType(prefix_hashes),rows=frozen_rows))
 for day in history_dates:'''
assert old in text;text=text.replace(old,new,1)
text=text.replace('inputs=source_inputs(context,symbol,prefix,day,q) if q[',"inputs=source_inputs(context,symbol,prefix,day,q,**({'prefix_reuse':prefix_reuse} if prefix_reuse is not None else {})) if q[",1)
# Only the two frozen functions may differ; C5 cache-only guards stay byte-identical.
a=ast.parse(before);b=ast.parse(text);oldnodes={getattr(n,'name',str(i)):ast.dump(n) for i,n in enumerate(a.body)};newnodes={getattr(n,'name',str(i)):ast.dump(n) for i,n in enumerate(b.body)};changed=[k for k in oldnodes if oldnodes[k]!=newnodes[k]];assert set(changed)=={'source_inputs','compute_stock'},changed
patch=''.join(difflib.unified_diff(before.splitlines(True),text.splitlines(True),fromfile='a/'+name,tofile='b/'+name));(HERE/'C6_OVERLAY.patch').write_text(patch)
(HERE/'OVERLAY_INVENTORY.json').write_text(json.dumps({'status':'SYNTHETIC_ONLY_CANDIDATE','base_git':'b2c4cbfd2bd06cac8e49e56b60d83edbda544e44','C4_commit':inventory['C4_commit'],'C5_producer_sha256':hashlib.sha256(before.encode()).hexdigest(),'C5_overlay_path':str((C5/'CANDIDATE_OVERLAY.patch').relative_to(ROOT)),'C5_overlay_sha256':hashlib.sha256((C5/'CANDIDATE_OVERLAY.patch').read_bytes()).hexdigest(),'C6_producer_sha256':hashlib.sha256(text.encode()).hexdigest(),'changed_functions':changed,'cache_only_guard_occurrences':text.count('CACHE_ONLY_NO_RECOMPUTE'),'patch_sha256':hashlib.sha256(patch.encode()).hexdigest(),'actual_product_source_edited':False},indent=2)+'\n')
print('Prepared two-function C6 overlay after accepted C5; no actual producer/live source edited.')
