"""Compose only the reviewed producer/rule bytes for the registered one-stock run."""
from pathlib import Path
import hashlib,json,subprocess,tempfile
ROOT=Path(__file__).resolve().parents[4];HERE=Path(__file__).resolve().parent
name='ops/research_panel_daily_product.py';c6=ROOT/'docs/handoffs/a_daily_dashboard_closure_20261029/history_prefix_reuse_source';v=json.loads((c6/'OVERLAY_INVENTORY.json').read_text());c5patch=ROOT/v['C5_overlay_path'];text=c5patch.read_text();start=text.index('--- a/'+name+'\n');end=text.find('\n--- a/',start+1);segment=text[start:] if end<0 else text[start:end+1]
output=HERE/'composed_source';p=output/name;p.parent.mkdir(parents=True,exist_ok=True)
if p.exists():raise FileExistsError('composed source already exists; preserve bytes')
p.write_bytes(subprocess.run(['git','show',v['C4_commit']+':'+name],cwd=ROOT,check=True,capture_output=True).stdout)
subprocess.run(['git','apply','-'],cwd=output,input=segment.encode(),check=True,capture_output=True)
assert hashlib.sha256(p.read_bytes()).hexdigest()==v['C5_producer_sha256']
subprocess.run(['git','apply',str(c6/'C6_OVERLAY.patch')],cwd=output,check=True,capture_output=True);assert hashlib.sha256(p.read_bytes()).hexdigest()==v['C6_producer_sha256']
for name in ['domains/research_daily_product.py','domains/research_daily_statistics.py']:
 q=output/name;q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(subprocess.run(['git','show','e6df789828ef064a9114e27962f99d2575711e7f:'+name],cwd=ROOT,check=True,capture_output=True).stdout)
print(json.dumps({'composed_source':str(output),'producer_sha256':v['C6_producer_sha256']}))
