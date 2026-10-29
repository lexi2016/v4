"""One existing D29 stock, original owner, isolated output only; no shared writes."""
from pathlib import Path
import hashlib,json,runpy,sys,time
ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT))
inventory=runpy.run_path(str(ROOT/'docs/handoffs/a_daily_dashboard_closure_20261029/run_real_canary.py'),run_name='candidate_source_imports')
inventory['bootstrap']['DELTAS'].add('ops.render_original_formula_projection')
from ops import research_panel_daily_product as owner
from ops import render_original_formula_projection as renderer
OUT=Path('/Users/lexi/Desktop/学习/因子工厂/research/a_daily_update_path_20261029_r1/dashboard_completion_r1/dashboard_resume_20261030/natural_owner_chart_handoff')
DATA=Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据')
start=time.monotonic();receipt={'scope':'ONE_600025_SH_ORIGINAL_OWNER_D29_ISOLATED','status':'RUNNING','shared_writes':False,'user_GUI':False,'RESEARCH_ONLY':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
try:
 context=owner.SourceContext(DATA,20261029);context.root=OUT/'canary/daily_products/a_share'
 original_init=owner.SourceContext;owner.SourceContext=lambda *args,**kwargs:context
 engine=context.engine();compute=engine.compute;calls=[]
 def counted(*args,**kwargs):calls.append('600025.SH');return compute(*args,**kwargs)
 engine.compute=counted
 render=renderer.owner_pngs
 def checked_render(items):
  assert not (context.root/'events/latest.json').exists()
  return render(items)
 try:result=owner.materialize_daily_product(data_root=DATA,target=20261029,symbols=['600025.SH'],output_root=context.root,chart_png_renderer=checked_render)
 finally:owner.SourceContext=original_init;engine.compute=compute
 manifest=json.loads(Path(result['manifest']['path']).read_text());product=json.loads(Path(result['artifact']['path']).read_text());folder=Path(result['manifest']['path']).parent/'original_charts'
 chart_receipt=json.loads((folder/'COMPLETION_RECEIPT.json').read_text());assert calls==['600025.SH'],calls
 assert product['sample_only'] is True and product['processed_count']==1
 assert chart_receipt['status']=='OWNER_CHARTS_COMPLETED',chart_receipt
 record=chart_receipt['records'][0];assert record['rows']==2150
 receipt.update(status='PASS_SINGLE_OWNER_RETAIN_RENDER',formula_compute_calls=len(calls),numeric_result=result,sample_only=True,rows=record['rows'],projection=record['projection'],html=record['html'],PNG=record['PNG'],sidecar_receipt={'path':str(folder/'COMPLETION_RECEIPT.json'),'sha256':hashlib.sha256((folder/'COMPLETION_RECEIPT.json').read_bytes()).hexdigest()},owner_product_root=str(DATA/'daily_products/a_share'),isolated_output_root=str(context.root),no_completion_published_for_sample=True,private_headless_process_closed=True)
except Exception as error:
 receipt.update(status='CANNOT_CONFIRM',error=repr(error));raise
finally:
 receipt['wall_seconds']=time.monotonic()-start;(OUT/'SINGLE_CANARY_RECEIPT.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n');print(json.dumps(receipt,ensure_ascii=False))
