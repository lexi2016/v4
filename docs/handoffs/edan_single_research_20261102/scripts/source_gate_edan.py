"""Re-run the existing full source gate against the third-stock code bytes."""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.append('/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v4-mac/lib/python3.14/site-packages')
from ops import research_panel_qfq as q

root=Path(q.__file__).resolve().parents[1]
out=Path(__file__).resolve().parent/'SOURCE_GATE_EDAN_R1.json'
prior_path=out.parent.parent/'n_hold_score_integration_20261102_r1/SOURCE_GATE_N_R2.json'
prior={'path':str(prior_path),'sha256':q.sha(prior_path)}
if out.exists():raise RuntimeError('IMMUTABLE_GATE_ALREADY_EXISTS')
old=json.loads(q._source(prior,owner='prior N source gate').read_text())
snapshot=q._source(old['snapshot'],owner='frozen snapshot')
q._source(old['relocation_ref'],owner='source relocation')
refs={name:{'path':str(root/name),'sha256':q.sha(root/name)} for name in sorted(old['source_code_refs'])}
start=time.monotonic()
loaded=q.load_snapshot(snapshot,old['target'],old['relocation_ref'])
digest=q.canonical_sha(loaded)
if digest!=old['canonical_input_sha256']:raise RuntimeError('CANONICAL_INPUT_CHANGED')
for name,ref in refs.items():
    if q.sha(root/name)!=ref['sha256']:raise RuntimeError('GATE_CODE_CHANGED:'+name)
result={**old,'prior_source_gate':prior,'source_code_refs':refs,'canonical_input_sha256':digest,
        'matches_frozen_input_sha256':True,'requested_symbols':len(loaded['symbols']),
        'finished_at':datetime.now(timezone.utc).isoformat(),'seconds':round(time.monotonic()-start,2),
        'status':'PASS_RELOCATED_SOURCE_GATE'}
out.write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
print(json.dumps({'path':str(out),'sha256':q.sha(out),'seconds':result['seconds'],'symbols':result['requested_symbols']}))
