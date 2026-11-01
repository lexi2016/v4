"""Format existing QFQ authority values for the established single-stock view."""
import gzip
import json
import math
from pathlib import Path
import pyarrow.parquet as pq
from ops import research_panel_qfq as q

r=Path(__file__).resolve().parent
base=r.parent/'n_hold_score_integration_20261102_r1/301048_SZ_N_BINDING_9bf8022c1206fea7.json'
b=json.loads(base.read_text());v=json.loads(gzip.decompress(q._source(b['assets']['kb'],owner='accepted field inventory').read_bytes()))
fields=v['fields'];inv=b['field_inventory'];names=[x['name'] for x in fields]
old_names=['B1','B2','B3','primary_buy_signal','secondary_buy_signal','sell_signal','user_v1_B1','user_v1_B2','user_v1_B3','user_v1_level1_buy_signal','user_v1_level2_buy_signal','user_v1_sell_signal_daily','user_v1_sell_signal_display_asof']
result=json.loads((r/'EDAN_PREFIX_INTERIM_R1.json').read_text())
table=pq.read_table(q._source(result['outputs']['selector'],owner='EDAN selector'))
sidecar=pq.read_table(q._source(result['gap_sidecar'],owner='EDAN diagnostics')).to_pylist()
source=table.select(['trade_date','open','high','low','close','volume','zge_white_line','zge_yellow_line',*names,*old_names,
                     *inv['hold_score_fields'],*inv['supplemental_fields'],*inv['action_fields'],*inv['yidong_fields'],*inv['confirmed_gap_fields']]).to_pylist()
assert len(source)==len(sidecar)==3767
def clean(x):return None if isinstance(x,float) and not math.isfinite(x) else x
rows=[]
for i,(row,d) in enumerate(zip(source,sidecar)):
    assert d['ts_code']=='300206.SZ' and int(d['trade_date'])==int(row['trade_date'])
    vol=row['volume'];prev=source[i-1]['volume'] if i else None;prev5=[x['volume'] for x in source[max(0,i-5):i]]
    mean=sum(prev5)/5 if len(prev5)==5 and all(x is not None and x>0 for x in prev5) else None
    group=lambda keys:{k:clean(row[k]) for k in keys}
    rows.append({'trade_date':int(row['trade_date']), 'kb':group(names), 'original':group(old_names),
                 'hold_score':group(inv['hold_score_fields']), 'supplemental':group(inv['supplemental_fields']),
                 'action':group(inv['action_fields']), 'yidong':group(inv['yidong_fields']),
                 'confirmed_kb_fields':group(inv['confirmed_gap_fields']),
                 'confirmed_kb_diagnostics':json.loads(d['diagnostics_json']),
                 'confirmed_kb_reused':{'bowl_white':clean(row['zge_white_line']),'bowl_yellow':clean(row['zge_yellow_line'])},
                 'diagnostics':{'volume_vs_previous':vol/prev if vol is not None and prev and prev>0 else None,
                                'volume_vs_previous_5_mean':vol/mean if vol is not None and mean else None}})
obj={'fields':fields,'field_inventory':inv,'rows':rows}
raw=json.dumps(obj,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
p=r/'EDAN_VIEW_ROWS_R1.json.gz'
assert not p.exists();p.write_bytes(gzip.compress(raw,mtime=0))
print(json.dumps({'rows':len(rows),'decoded_bytes':len(raw),'compressed_bytes':p.stat().st_size,'sha256':q.sha(p)}))
