"""Owned queue readback only; no lock, tick, download, OCR or processing."""
import hashlib
import json
from pathlib import Path
import sys
from collections import Counter
import plistlib

plist=plistlib.loads(Path('/Users/lexi/Library/LaunchAgents/com.lexi.v35.scheduler.plist').read_bytes())
env=plist['EnvironmentVariables'];sys.path.insert(0,env['V35_APP_ROOT'])
from infrastructure.zsxq_pdf_ingestion import pending_pdf_tasks, _latest_engine_run, STATE_RELATIVE
root=Path(env['V35_DATA_ROOT']);p=root/STATE_RELATIVE
before=p.read_bytes();index=json.loads(before)
statuses=Counter()
for row in index['documents'].values():
    latest=_latest_engine_run(row)
    if latest:statuses[str(latest[1].get('status'))]+=1
pending=pending_pdf_tasks(root)
after=p.read_bytes()
result=dict(index_path=str(p),index_sha256=hashlib.sha256(after).hexdigest(),stable_during_read=before==after,document_count=len(index['documents']),latest_status_counts=dict(statuses),verified_retryable_task_count=len(pending),processing_document_count=statuses.get('PROCESSING',0),pdf_business_execution=False)
Path(__file__).with_suffix('.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False))
