"""Exercise the installed F10 consumer with real identity and an isolated index."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import plistlib

from infrastructure.research_lane_source import ResearchLaneSource
from infrastructure.research_workbench_host import ResearchWorkbenchHost

E=Path('/Users/lexi/Desktop/学习/agents调试/DOT_TO_LOCAL_QWEN_MIGRATION_V1_20261101/kb_panel_upgrade_20261101/libang_300206_20261102_r1/f10_three_completion_r1/canonical_repair_r1')
pre=json.loads((E/'ISOLATED_OWNER_PREP_R1.json').read_text());assert pre['status']=='PASS_ACTUAL_MAIN_OWNER_ISOLATED_ROOT'
api=plistlib.loads(Path('/Users/lexi/Library/LaunchAgents/com.lexi.v4.api.plist').read_bytes());env=api['EnvironmentVariables'];binding_path=Path(env['V4_WORKBENCH_HOST_BINDING'])
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
assert sha(binding_path)==env['V4_WORKBENCH_HOST_BINDING_SHA256']=='5b0c8a84bfb2ef7efe3ba5b7f0ff286c925a933c768b9d565992ac5e41edb557'
binding=json.loads(binding_path.read_text());actual=ResearchLaneSource(Path(env['V4_RESEARCH_DATA_ROOT']),a_share_daily_root=Path(env['V4_A_SHARE_DAILY_PRODUCT_ROOT']))
isolated=ResearchLaneSource(Path(env['V4_RESEARCH_DATA_ROOT']),a_share_daily_root=Path(pre['isolated_base']))
class BoundSource:
    # The existing product remains the identity/172-row authority; the copied
    # index and all F10 refs live in the isolated product root for this test.
    def _a_product_root(self):return isolated._a_product_root()
    def _a_product_reference(self,reference):return isolated._a_product_reference(reference)
    def read_a_daily_product(self,*args,**kwargs):return actual.read_a_daily_product(*args,**kwargs)
    def __getattr__(self,name):return getattr(actual,name)
host=ResearchWorkbenchHost(BoundSource(),binding);view=host._view('2026-10-30')
assert len(view['rows'])==172 and view['source_generation']=='d22220537892215832f0c01faeaadd11e282b4d65debf979152597a00d1829b5'
old=json.loads((E.parent/'THREE_F10_PUBLICATION_PLAN_R2.json').read_text())
try:isolated._a_product_reference(old['new_receipt'])
except ValueError as error:assert str(error)=='A_DAILY_PRODUCT_REFERENCE_OUTSIDE_BOUND_ROOT'
else:raise AssertionError('DEBUG_REFERENCE_NOT_REJECTED')
results={}
for code in ('002865.SZ','301048.SZ','300206.SZ'):
 value=host.f10('2026-10-30',code)
 assert value['status']=='OBSERVED' and value['symbol']==code
 assert value['stock_ref']['sha256']==pre['captured_source_sha256'][code]
 assert Path(value['receipt']['path']).is_relative_to(Path(pre['isolated_product_root']))
 assert Path(value['stock_ref']['path']).is_relative_to(Path(pre['isolated_product_root']))
 results[code]={'status':value['status'],'receipt':value['receipt'],'stock_ref':value['stock_ref'],'concept_count':len(value['f10']['concepts'])}
real=Path(env['V4_A_SHARE_DAILY_PRODUCT_ROOT'])/'daily_products/a_share'
assert sha(real/'index.json')==pre['source_index_sha256'] and sha(real/'events/latest.json')==pre['source_event_sha256']
out=E/'ISOLATED_CONSUMER_R1.json';assert not out.exists();out.write_text(json.dumps({'status':'PASS_INSTALLED_API_CONSUMER_ALL_THREE','source_summary':'actual product Source.read_a_daily_product','f10_references':'installed _a_product_reference against isolated product root','outside_root_negative':'REJECTED','product_rows':len(view['rows']),'results':results,'RESEARCH_ONLY':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False},ensure_ascii=False,sort_keys=True,indent=2)+'\n');print(json.dumps({'status':'PASS_INSTALLED_API_CONSUMER_ALL_THREE','path':str(out),'sha256':sha(out)},ensure_ascii=False),flush=True)
