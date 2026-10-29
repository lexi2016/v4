"""Root registers this bounded real prefix replay before execution. No live writes."""
from pathlib import Path
import hashlib
import json
import resource
import sys
import time
import runpy

HERE=Path(__file__).resolve().parent
bootstrap=runpy.run_path(str(HERE/'run_targeted_checks.py'),run_name='candidate_read_only_imports')
# Main owns formula/adjustment dependencies; the API consumes immutable readers.
bootstrap['CandidateInventory'].__module__
main=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/a-daily-sop-closure-20261029-r1-main/app')
class MainSourceFallback(bootstrap['CandidateInventory']):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] in ('ops','contracts','infrastructure','domains') and fullname not in bootstrap['DELTAS']:
   import importlib.util
   p=main/Path(*fullname.split('.')).with_suffix('.py')
   if p.is_file():return importlib.util.spec_from_file_location(fullname,p)
   init=main/Path(*fullname.split('.'))/'__init__.py'
   if init.is_file():return importlib.util.spec_from_file_location(fullname,init,submodule_search_locations=[str(init.parent)])
  return None
sys.meta_path.insert(0,MainSourceFallback())
from ops import research_panel_daily_product as product

if __name__=='__main__':
 binding=Path(sys.argv[1]);pins=json.loads(binding.read_text());out=Path(sys.argv[2]).resolve()
 if out.exists():raise ValueError('CANARY_OUTPUT_MUST_BE_NEW')
 for item in [*pins['pointers'],pins['receipt'],pins['snapshot'],pins['quarantine']]:product.checked(item)
 for reference in pins['reference_rows'].values():product.checked(reference)
 panel=Path(pins['selector']['path']);assert all(getattr(panel.stat(),k)==v for k,v in pins['selector']['stat'].items())
 started=time.perf_counter();context=product.SourceContext(pins['data_root'],pins['target']);context.root=out/'isolated_daily_products';assert context.generation==pins['generation'];results=[]
 for symbol in pins['symbols']:
  bars,_=context.read(symbol);dates=[b['trade_date'] for b in bars if b['trade_date']<context.target][-pins['history_tail_sessions']:];t=time.perf_counter();row,cache,path=product.compute_stock(context,symbol,history_dates=dates);elapsed=time.perf_counter()-t
  assert row['qualification']['status']=='CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH',row['qualification'];assert row['statistics']['status']=='DESCRIPTIVE_STATS_COMPUTED';assert set(cache['evaluations'])==set(map(str,[context.target,*dates]))
  assert product.canonical(row)+b'\n'==Path(pins['reference_rows'][symbol]['path']).read_bytes(),'IO_FIX_CHANGED_FULL_BUSINESS_ROW:'+symbol
  product.save(path,cache);product.save(out/(symbol+'.json'),row)
  result=dict(symbol=symbol,prefix_rows=len(bars),history_evaluations=len(dates),seconds=elapsed,qualification=row['qualification']['status'],current_groups={g:row['evaluation']['groups'][g]['status'] for g in product.GROUPS},coverage=row['historical_coverage'],price_distribution=row['statistics']['price_distribution'],history_start=bars[0]['trade_date'],history_end=bars[-1]['trade_date'],raw_source_pins=row['qualification']['verified_raw_sources'])
  results.append(result);product.save(out/'PROGRESS.json',dict(completed=len(results),total=len(pins['symbols']),last=result));print(json.dumps(dict(symbol=symbol,seconds=elapsed,prefix_rows=len(bars)),ensure_ascii=False),flush=True)
 context.unchanged();result=dict(status='PASS_IO_ONLY_EXACT_PARITY',source_generation=context.generation,input_sha256=context.identity['input_sha256'],results=results,wall_seconds=time.perf_counter()-started,peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,full_history_bootstrap=False,historical_PIT=False,maximum_claim='DIRECTION_ONLY',**product.FLAGS);product.save(out/'RESULT.json',result)
