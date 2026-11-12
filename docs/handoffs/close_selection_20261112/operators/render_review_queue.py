"""Read-only reuse of exact same-D12 original owner R19 rendering bytes.
No extra formula evaluations; fresh candidate membership comes only from this
batch's independently recomputed kernel ledger, never the prior chart index.
"""
import hashlib,json,gzip,pathlib,sys,os,time
import pandas as pd
N=pathlib.Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def save(p,x):pathlib.Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2,default=str)+'\n')
def main():
 f=json.loads((N/'RUN_FREEZE.json').read_text());os.environ.update(f['env']);sys.path.insert(0,f['env']['V4_APP_ROOT']);from ops import research_panel_chart_blocks as blocks,research_panel_daily_product as prod
 from ops.render_original_formula_projection import chart_html,owner_pngs
 q=json.loads((N/'REVIEW_QUEUE.json').read_text());parts=pathlib.Path(f['parts']);cfg=json.loads(prod.checked(f['source_config']).read_bytes());context=prod.SourceContext(f['env']['V4_RESEARCH_PANEL_A_DATA_ROOT'],20261112)
 oldroot=pathlib.Path('/Users/lexi/Desktop/学习/因子工厂/research/a_daily_update_path_20261029_r1/dashboard_completion_r1/today_full_r1/daily_products/a_share');index=json.loads((oldroot/'index.json').read_text());manifest_ref=index['dates']['20261112'];manifest=json.loads(prod.checked(manifest_ref).read_bytes());artifact=manifest['artifact'];prior=json.loads(prod.checked(artifact).read_bytes());oldcharts=pathlib.Path(manifest_ref['path']).parent/'original_charts'
 frame=pd.concat([pd.read_parquet(N/'data/CANARY_PREFIX.parquet'),pd.read_parquet(N/'data/REMAINING_PREFIX.parquet')],ignore_index=True);groups={code:g.sort_values('trade_date')for code,g in frame.groupby('ts_code',sort=False)}
 out=N/'outputs/review_charts';out.mkdir(exist_ok=True);items=[];gaps={}
 for row in q['chart_priority']:
  code=row['security_code'];dest=out/(code+'.html');ready_path=oldcharts/(code+'.ready.json')
  if not ready_path.is_file():gaps[code]='NO_EXACT_SOURCE_BOUND_OWNER_CHART';continue
  ready=json.loads(ready_path.read_text());assert ready['symbol']==code and ready['data_date']=='20261112' and ready['source_generation']==f['source_identity']['generation'] and ready['source_input_sha256']==f['source_identity']['input_sha256']
  assert ready['source_binding']['config']==f['source_config'] and ready['source_binding']['engine']==cfg['engine'] and ready['source_binding']['formula']==cfg['formula']
  g=groups[code];bars=[dict(trade_date=int(r.trade_date),open=str(r.open),high=str(r.high),low=str(r.low),close=str(r.close),vol=str(r.volume))for r in g.itertuples()]
  assert ready['source_cache']['bars_sha256']==prod.digest(bars),'CHART_EXACT_FULL_PREFIX_MISMATCH:'+code
  assert ready['source_cache']['calendar_sha256']==prod.digest(context.calendars[code[-2:]]),'CHART_CALENDAR_CONFLICT'
  renderer=ready['source_binding']['renderer'];raw=prod.checked(renderer).read_bytes();payload=json.loads(gzip.decompress(blocks.projection_bytes(ready['projection'])));dates=[int(x['trade_date'])for x in payload['formula_result']['rows']]
  assert dates==[b['trade_date']for b in bars] and max(dates)==20261112 and payload['symbol']==code
  html=chart_html(raw,payload,payload['lineage'],compress_payload=False).replace('"full_history_recomputed":true','"full_history_recomputed":false')
  if dest.exists():assert dest.read_text()==html
  else:dest.write_text(html)
  proof=json.loads((N/'engine_proofs'/(code+'.json')).read_text());item=dict(row,symbol=code,date='20261112',rows=len(dates),html=str(dest),html_sha256=sha(dest),png=str(out/(code+'.png')),original_renderer=renderer,owner_chart_ready=dict(path=str(ready_path),sha256=sha(ready_path)),projection_sha256=ready['projection']['sha256'],fresh_engine_row=proof['row'],chart_math_source_same=True,full_prefix_sha256=prod.digest(bars),formula_compute_calls_added=0,human_review='PENDING',old_chart_reader_provenance_retained=True,identity_note='same generation/bars/config/engine/formula/calendar; original rendering provenance retained separately from fresh candidate row')
  items.append(item)
 save(out/'MANIFEST.json',dict(status='D12_EXACT_PREFIX_ORIGINAL_RENDERER_REUSED',items=items,gaps=gaps,new_formula_calls=0,chart_cutoff='2026-11-12T15:00:00+08:00',fit_count=0))
 # Existing R19 owner function owns and closes its private headless browser.
 pending=[i for i in items if not pathlib.Path(i['png']).exists()];errors=owner_pngs(pending)if pending else {}
 for item in items:
  if pathlib.Path(item['png']).exists():item['png_sha256']=sha(item['png'])
 save(out/'MANIFEST.json',dict(status='READY_ORIGINAL_OWNER_CHARTS'if not errors else 'PARTIAL_RENDER',items=items,gaps=gaps,errors=errors,new_formula_calls=0,fit_count=0));save(N/'REVIEW_CHARTS_READY.json',dict(status='READY'if not errors else 'PARTIAL',manifest=str(out/'MANIFEST.json'),count=len(items),errors=errors,gaps=gaps));print(json.dumps(dict(status='REVIEW_CHARTS_READY',count=len(items),errors=errors,gaps=gaps)),flush=True)
if __name__=='__main__':main()
