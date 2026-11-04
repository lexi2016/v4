"""Inspect identities and row group footer statistics without reading values."""
import json, sys
from pathlib import Path
import pyarrow.parquet as pq

out=Path(sys.argv[1]); meta=json.loads(Path(sys.argv[2]).read_text()); path=meta['selector']['target']
pf=pq.ParquetFile(path); schema=pf.schema_arrow; col=schema.get_field_index('ts_code'); market=schema.get_field_index('market_type')
groups=[]
for i in range(pf.num_row_groups):
 r=pf.metadata.row_group(i)
 def stats(idx):
  s=r.column(idx).statistics
  return [s.min,s.max] if s and s.has_min_max else None
 groups.append({'id':i,'rows':r.num_rows,'symbol':stats(col),'market':stats(market)})
result={'path':path,'rows':pf.metadata.num_rows,'row_groups':pf.num_row_groups,'schema':str(schema),'groups':groups}
out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'groups':len(groups),'first':groups[:4],'last':groups[-2:],'missing_symbol_stats':sum(g['symbol'] is None for g in groups),'mixed_symbol_groups':sum(g['symbol'] and g['symbol'][0]!=g['symbol'][1] for g in groups)}))
