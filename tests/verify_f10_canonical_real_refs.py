"""Read newly materialized refs with the installed API's unchanged path gate."""
from pathlib import Path
import hashlib,json,plistlib
from infrastructure.research_lane_source import ResearchLaneSource
E=Path('/Users/lexi/Desktop/学习/agents调试/DOT_TO_LOCAL_QWEN_MIGRATION_V1_20261101/kb_panel_upgrade_20261101/libang_300206_20261102_r1/f10_three_completion_r1/canonical_repair_r1');p=E/'CANONICAL_PUBLICATION_PLAN_R1.json'
sha=lambda x:hashlib.sha256(Path(x).read_bytes()).hexdigest();assert sha(p)=='6ed382056b1d2a43d93c7329271aff20ea3753e68b322f4c8a511c1624191518';plan=json.loads(p.read_text())
env=plistlib.loads(Path('/Users/lexi/Library/LaunchAgents/com.lexi.v4.api.plist').read_bytes())['EnvironmentVariables']
s=ResearchLaneSource(Path(env['V4_RESEARCH_DATA_ROOT']),a_share_daily_root=Path(env['V4_A_SHARE_DAILY_PRODUCT_ROOT']))
receipt=s._a_product_reference(plan['new_receipt']);checkpoint=s._a_product_reference(receipt['checkpoint']);result={}
for code,ref in checkpoint['items'].items():
 value=s._a_product_reference(ref);assert value['symbol']==code and value['status']=='OBSERVED' and value['historical_PIT'] is False
 result[code]={'status':value['status'],'sha256':ref['sha256'],'path':ref['path']}
assert set(result)=={'002865.SZ','301048.SZ','300206.SZ'}
assert sha(plan['index_before']['path'])==plan['index_before']['sha256'] and sha(plan['event_before']['path'])==plan['event_before']['sha256']
out=E/'CANONICAL_REAL_REFERENCE_VERIFY_R1.json';assert not out.exists();out.write_text(json.dumps({'status':'PASS_INSTALLED_API_GATE_CANONICAL_REFERENCES','receipt':plan['new_receipt'],'checkpoint':receipt['checkpoint'],'results':result,'index_event_still_before':True,'RESEARCH_ONLY':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False},ensure_ascii=False,sort_keys=True,indent=2)+'\n');print(json.dumps({'path':str(out),'sha256':sha(out),'status':'PASS_INSTALLED_API_GATE_CANONICAL_REFERENCES'},ensure_ascii=False))
