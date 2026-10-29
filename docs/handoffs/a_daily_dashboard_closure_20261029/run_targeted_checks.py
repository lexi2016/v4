"""Check candidate deltas against the exact immutable API inventory, read-only."""
from pathlib import Path
import importlib.abc
import importlib.util
import sys
import unittest

ROOT=Path(__file__).resolve().parents[3]
BASE=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/a-daily-sop-closure-20261029-r1-api/app')
FALLBACK=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/v4-daily-numeric283-chart-20261029-r3-api/app')
DELTAS={'ops.research_panel_daily_product','domains.research_daily_product','domains.research_daily_statistics','infrastructure.research_lane_source','infrastructure.zsxq_pdf_ingestion','infrastructure.zsxq_pdf_search_index','domains.related_pdf_reports','domains.related_pdf_cursor','apps.api.v4_api.runtime_router','apps.api.v4_api.research_lane_router','apps.api.v4_api.research_router','apps.api.v4_api.app'}
class CandidateInventory(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] not in ('apps','domains','infrastructure','contracts','ops','upstreams','stage_center','shared_data'):return None
  relative=Path(*fullname.split('.'))
  bases=[ROOT] if fullname in DELTAS else [BASE,FALLBACK,BASE/'upstreams',FALLBACK/'upstreams']
  for base in bases:
   file=base/relative.with_suffix('.py');init=base/relative/'__init__.py'
   if file.is_file():return importlib.util.spec_from_file_location(fullname,file)
   if init.is_file():return importlib.util.spec_from_file_location(fullname,init,submodule_search_locations=[str(init.parent)])
   if (base/relative).is_dir():
    from importlib.machinery import ModuleSpec
    spec=ModuleSpec(fullname,loader=None,is_package=True);spec.submodule_search_locations=[str(base/relative)];return spec
  return None
sys.path.insert(0,str(ROOT));sys.meta_path.insert(0,CandidateInventory())
if __name__=='__main__':
 suite=unittest.TestSuite(unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern=p) for p in ['test_daily_product_wiring.py','test_daily_task_catalog_binding.py'])
 result=unittest.TextTestRunner().run(suite);sys.exit(not result.wasSuccessful())
