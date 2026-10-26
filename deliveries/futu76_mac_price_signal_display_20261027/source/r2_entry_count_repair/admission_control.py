"""Root-only exact one-file admission CAS/rollback under the original QFQ lock.

Writer never invokes apply/rollback on the live root. API release switching uses
the original api_release_integration shared lock and external Root controller.
"""
from pathlib import Path
import hashlib
import json
import sys

B=Path(__file__).resolve().parent
R1=B.parent
W=Path('/Users/lexi/.codex/worktrees/futu76-mac-integration-20261026/v4_app')
sys.path.insert(0,str(W))
from ops import research_panel_qfq as q
from ops import api_release_integration as a
a.MODULE_CONTRACT_PATH=R1/'control/api_module_contracts.json'
STATE=Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据')
TARGET=STATE/'runtime/cache/data_layer_daily_formula_increment_update_v1/futu_direct_qfq76_admission.json'
P=Path('/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist')
CANDIDATE=R1/'full/candidate_manifest.json'
JOURNAL=B/'control/ROOT_ADMISSION_JOURNAL.json'


def ref(p):return dict(path=str(p),sha256=q.sha(Path(p)))
def raw_sha(raw):return None if raw is None else hashlib.sha256(raw).hexdigest()


def payload(review_path):
    review_path=Path(review_path)
    review=json.loads(review_path.read_text())
    candidate=json.loads(CANDIDATE.read_text())
    if (review.get('verdict')!='PASS_FUTU76_ENTRY_COUNT_R2_INCREMENTAL'
            or review.get('candidate_manifest_sha256')!=q.sha(CANDIDATE)
            or review.get('package_manifest_sha256')!=json.loads((B/'control/PACKAGE_RESULT.json').read_text())['manifest_sha256']
            or not review.get('reviewer_id') or len(candidate['symbols'])!=76):
        raise RuntimeError('REAL_INCREMENTAL_REVIEW_REQUIRED')
    original_ref=json.loads((B/'R1_REUSE_BINDING.json').read_text())['review/INDEPENDENT_FINAL_REVIEW_R1.json']
    original=json.loads(q._source(original_ref,owner='unchanged-api-and-data-review').read_text())
    if (original.get('verdict')!='PASS_FUTU76_MAC_PRICE_SIGNAL_DISPLAY_CANDIDATE'
            or original.get('candidate_manifest_sha256')!=q.sha(CANDIDATE)):
        raise RuntimeError('UNCHANGED_DATA_API_REVIEW_IDENTITY_REQUIRED')
    q._source(candidate['artifact'],owner='exact76-admission')
    return dict(schema='futu_direct_qfq76_admission_v1',candidate=ref(CANDIDATE),
        independent_review=original_ref,incremental_control_review=ref(review_path))


def apply(review_path, *, expected_before_sha256=None):
    value=payload(review_path)
    package=json.loads((B/'control/PACKAGE_RESULT.json').read_text())
    active=a.read_active_release(P)
    expected_active_manifest=q.sha(B/'control/release-manifest.materialized.json')
    if (active['release_manifest_sha256']!=expected_active_manifest
            or q.sha(Path(active['app_root'])/'apps/api/v35_api/a_share_panel_history.py')!=package['api_source_sha256']):
        raise RuntimeError('REVIEWED_API_SOURCE_MUST_BE_ACTIVE_BEFORE_ADMISSION')
    lock=TARGET.with_name('qfq_publish.lock')
    if not lock.is_file() or TARGET.is_symlink() or JOURNAL.exists():
        raise RuntimeError('LOCK_MISSING_OR_TARGET_SYMLINK_OR_JOURNAL_EXISTS')
    with q.publication_lock(STATE):
        before=TARGET.read_bytes() if TARGET.exists() else None
        if raw_sha(before)!=expected_before_sha256:
            raise RuntimeError('ADMISSION_PREIMAGE_CAS_CONFLICT')
        # Current task begins from absence; any previous binding needs a new
        # explicitly scoped Root decision rather than silently superseding it.
        if before is not None:
            raise RuntimeError('EXISTING_ADMISSION_NOT_OWNED_BY_THIS_TASK')
        encoded=(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
        journal=dict(status='PREPARED',target=str(TARGET),before_sha256=None,before_exists=False,
            after_sha256=raw_sha(encoded),admission=value,api_manifest_sha256=active['release_manifest_sha256'])
        q._json(JOURNAL,journal)
        q._write(TARGET,encoded)
        if TARGET.read_bytes()!=encoded:
            raise RuntimeError('ADMISSION_POST_WRITE_READBACK_CONFLICT')
        q._json(JOURNAL,{**journal,'status':'COMMITTED'})
    return dict(status='COMMITTED',target=str(TARGET),sha256=raw_sha(encoded))


def rollback():
    journal=json.loads(JOURNAL.read_text())
    if (journal.get('target')!=str(TARGET) or journal.get('before_exists') is not False
            or journal.get('status') not in {'PREPARED','COMMITTED'} or TARGET.is_symlink()):
        raise RuntimeError('ADMISSION_ROLLBACK_IDENTITY_CONFLICT')
    with q.publication_lock(STATE):
        current=TARGET.read_bytes() if TARGET.exists() else None
        if raw_sha(current)!=journal['after_sha256']:
            raise RuntimeError('ADMISSION_ROLLBACK_THIRD_PARTY_CAS_CONFLICT')
        TARGET.unlink()
        # fsync the owning directory using the same durability convention as
        # the original publisher. No other file is deleted or restored.
        import os
        fd=os.open(TARGET.parent,os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)
        q._json(JOURNAL,{**journal,'status':'ROLLED_BACK'})
    return dict(status='ROLLED_BACK',target=str(TARGET))


if __name__=='__main__':
    if sys.argv[1]=='apply':result=apply(sys.argv[2])
    elif sys.argv[1]=='rollback':result=rollback()
    else:raise RuntimeError('EXPLICIT_ROOT_APPLY_OR_ROLLBACK_ONLY')
    print(json.dumps(result,sort_keys=True))
