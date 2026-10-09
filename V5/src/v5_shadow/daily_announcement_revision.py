"""Execute pinned e06d revision commands only after real reviewed inputs arrive."""
from datetime import datetime,timezone
from pathlib import Path
import hashlib
import json
import subprocess
import sys
from v5_shadow.announcement_offline_reader import REVISION_APP,REVISION_PIN,sources,read_owner
from v5_shadow.daily_owner_adapters import blocked
from v5_shadow.digests import MAX_JSON_BYTES


def run_revision(request,ledger_run_id):
    create=request.get('revision_create')
    identities=request.get('review_identities')
    if not create or not identities:
        return blocked(None,['WAITING_REAL_SEMANTIC_DECISIONS_AND_INDEPENDENT_REVIEWER'])
    required=('parent_root','recovery_sha256','revision_id','parent_product_sha256','parent_receipt_sha256',
              'semantic_catalog','semantic_sha256','reviewer_output','reviewer_sha256','decisions','decisions_sha256')
    if set(create)!=set(required):raise ValueError('DAILY_REVISION_CREATE_CONTRACT')
    if set(identities)!={'parent_task_id','reader_identity','reviewer_identity'}:
        raise ValueError('DAILY_REVISION_REVIEW_IDENTITIES')
    if identities['reader_identity']==identities['reviewer_identity']:raise ValueError('DAILY_REVISION_DISTINCT_REVIEWER')
    # Missing inputs block before revision creation; original owner validates
    # their hashes, provenance, decisions and all content gates before import.
    for key in ('semantic_catalog','reviewer_output','decisions'):
        if not Path(create[key]).is_file():return blocked(None,['WAITING_REAL_'+key.upper()])
    sources(REVISION_APP,REVISION_PIN)
    def invoke(arguments):
        child=subprocess.run([sys.executable,'-I','-B',str(REVISION_APP/'ops/run_v5_decision_revision.py'),*arguments],
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=180)
        if child.returncode:raise ValueError('DAILY_REVISION_OWNER_FAILED:'+child.stderr.decode(errors='replace')[-1500:])
        if len(child.stdout)>MAX_JSON_BYTES:raise ValueError('DAILY_REVISION_RESPONSE_LIMIT')
        return json.loads(child.stdout)
    arguments=['create']
    for key in required:arguments.extend(['--'+key.replace('_','-'),str(create[key])])
    created=invoke(arguments)
    root=Path(created['revision_root']);revision_sha=created['revision_sha256']
    base=['run','--revision-root',str(root),'--revision-sha256',revision_sha]
    invoke(base+['prepare'])
    register=base+['register-handoff']
    for key,value in identities.items():register.extend(['--'+key.replace('_','-'),value])
    invoke(register);invoke(base+['verify']);invoke(base+['import']);invoke(base+['readback'])
    raw=(root/'manager_binding.v1.json').read_bytes();declared=json.loads(raw)
    binding=dict(root=str(root),binding_sha256=hashlib.sha256(raw).hexdigest(),
        target_date=declared['target_trade_date'],publication_date=declared['publication_date'],
        revision_manifest_sha256=revision_sha)
    if binding['target_date']!=request['target_date']:raise ValueError('DAILY_REVISION_TARGET')
    cutoff=datetime.now(timezone.utc).isoformat()
    first=read_owner(binding,cutoff);second=read_owner(binding,cutoff)
    if first!=second:raise ValueError('DAILY_REVISION_READBACK_CHANGED')
    sources(REVISION_APP,REVISION_PIN)
    reference=dict(ledger_run_id=ledger_run_id,binding=binding,readback_cutoff=cutoff,
        consumption=first['consumption'],natural_verified=False)
    # A reviewed revision may still contain explicit NOT_ASSESSED rows; original
    # manager channels, rather than a blanket success here, assess completeness.
    return blocked(reference,['REVISION_IMPORTED_ORIGINAL_CHANNEL_GATES_RETAINED'],readback=True)
