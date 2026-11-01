"""Reuse the SHA-pinned original formula engine on the admitted prefix."""
from pathlib import Path
import gzip
import importlib.util
import json
import time
import pyarrow.parquet as pq
from ops import research_panel_qfq as q
from ops import render_original_formula_projection as renderer

r=Path(__file__).resolve().parent
old=json.loads((r/'EDAN_PREFIX_INTERIM_R1.json').read_text())
cfg=json.loads(Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/workbench-daily-chain-20261031-r6-main/app/docs/handoffs/a_daily_dashboard_closure_20261029/SOURCE_CONFIG.json').read_text())
for key in ('admission_helper','engine','formula'):
    assert q.sha(cfg[key]['path'])==cfg[key]['sha256']
assert cfg['engine']['sha256']==renderer.ENGINE_SHA and cfg['formula']['sha256']==renderer.FORMULA_SHA
assert q.sha(renderer.OWNER_RENDERER['path'])==renderer.RENDERER_SHA
spec=importlib.util.spec_from_file_location('single_edan_admission',cfg['admission_helper']['path'])
admission=importlib.util.module_from_spec(spec);spec.loader.exec_module(admission)
f=json.loads((r.parent/'FROZEN_BASELINE.json').read_text())['roles']['selector']['contract']
receipt=json.loads(Path(f['generation_manifest_path']).read_text())
quarantine=json.loads(Path(f['quarantine_manifest_path']).read_text())
a=admission.verify_symbol_admission('300206.SZ','20261030',f,receipt,quarantine,f['generation_id'],Path(f['quarantine_manifest_path']))
assert a['status']=='CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH',a
ap=r/'EDAN_SOURCE_ADMISSION_R1.json'
assert not ap.exists();ap.write_text(json.dumps(a,ensure_ascii=False,indent=2)+'\n')
spec=importlib.util.spec_from_file_location('single_edan_original_engine',cfg['engine']['path'])
engine=importlib.util.module_from_spec(spec);spec.loader.exec_module(engine)
source=old['outputs']['selector'];table=pq.read_table(q._source(source,owner='EDAN interim selector'),columns=['trade_date','open','high','low','close','volume']).to_pandas()
bars=[{'trade_date':int(x.trade_date),'open':str(x.open),'high':str(x.high),'low':str(x.low),'close':str(x.close),'vol':str(x.volume)} for x in table.itertuples(index=False)]
assert len(bars)==3767 and bars[-1]['trade_date']==20261030
started=time.monotonic();print('CHART_ENGINE_START',len(bars),flush=True)
result=engine.json_ready(engine.compute(bars,mode='prefix'));inv=engine.inventory()
assert result['formula_sha256']==renderer.FORMULA_SHA and (result['field_count'],result['drawing_count'],len(result['rows']))==(51,22,len(bars))
for row,bar in zip(result['rows'],bars):
    assert row['trade_date']==bar['trade_date'] and len(row['values'])==51 and len(row['drawings'])==22
source_meta={'generation_id':old['source_generation'],'source_input_sha256':old['identity']['input_sha256'],
             'price_basis':'QFQ_ASOF','volume_basis':'QFQ_EVENT_VOLUME',
             'adjustment_convention':json.loads(Path(old['snapshot']['path']).read_text())['convention']}
lineage={'selector_candidate':source,'snapshot':old['snapshot'],'source_gate':old['prior_source_gate'],
         'engine':cfg['engine'],'formula':cfg['formula'],'renderer':renderer.OWNER_RENDERER,
         'scope':'SINGLE_STOCK_RESEARCH_OUTSIDE_CANDIDATE_POOL','observation_date':'2026-11-02',
         'admission':{'path':str(ap),'sha256':q.sha(ap)}}
projection={'schema':'v4.d35c.single_stock_research_projection.v1','symbol':'300206.SZ','data_date':'20261030',
            'authority':'SINGLE_STOCK_RENDERING_ONLY','historical_PIT':False,'source':source_meta,
            'source_cache':{'selector_candidate_sha256':source['sha256'],'rows':len(bars)},
            'inventory':inv,'formula_result':result,'unsupported_drawings':[],
            'renderer_semantics':'UNCHANGED_R19_DISPLAY; NOT_NATIVE_TDX_EQUIVALENCE_CERTIFIED',
            'lineage':lineage,**q.FLAGS}
raw=json.dumps(projection,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()+b'\n'
packed=gzip.compress(raw,mtime=0);p=r/'EDAN_ORIGINAL_PROJECTION_R1.json.gz'
assert not p.exists();p.write_bytes(packed)
print('EDAN_CHART_PROJECTION_PREPARED',q.sha(p),'seconds',round(time.monotonic()-started,2),flush=True)
