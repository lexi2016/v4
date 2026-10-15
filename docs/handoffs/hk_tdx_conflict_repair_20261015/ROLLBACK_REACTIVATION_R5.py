"""Component/event exact CAS rollback, independent failures explicitly recorded."""
from pathlib import Path
import hashlib,json,sys
H=Path(__file__).resolve().parent
PUB=json.loads((H/'PUBLICATION_COMBINED_R3.json').read_bytes());PLAN=json.loads((H/'PUBLICATION_STATE_PLAN_R3.json').read_bytes())
sys.path.insert(0,PUB['api']['app_root']);sys.path.insert(0,PUB['shared']['app_root'])
from HK_REACTIVATION_CONTROL_R5 import rollback_consumer,rollback_shared_entries,restore_independently,sha
from infrastructure.preselection_pool_store import PreselectionPoolStore
from infrastructure.interprocess_lock import owned_interprocess_lock
from shared_data.store import SafeRootStore
POOL='hkconnect_d1_top100';ROLE='HK_CONNECT_D1_TOP100_0_2'

def rollback_target(target):
    data=Path(PLAN['consumer_root']);store=PreselectionPoolStore(data)
    with owned_interprocess_lock(data/'.import.lock',timeout_seconds=10,timeout_message='R5 HK rollback import lock busy'):
        pending=list((data/'preselection_pending_commits').rglob('*.json'))
        own=data/f'preselection_pending_commits/{target}/{POOL}.json'
        assert all(p==own for p in pending),'FOREIGN_PENDING_PRESERVED_NO_RECOVERY'
        path=H/f'CONSUMER_INTENT_{target}_R5.json'
        if path.exists():
            intent=json.loads(path.read_bytes());row=PLAN['targets'][target]
            assert intent['target_date']==target and intent['new_semantic_sha256']==json.loads((H/f'PUBLISHED_{target}_CONSUMER.json').read_bytes())['result']['sha256']
            assert intent['old']['manifest']==row['consumer_preexisting_manifest_sha256']
            assert intent['non_HK_manifest_sha256']==row['consumer_non_HK_manifest_sha256']
            return rollback_consumer(store,intent)
        # No durable intent means this attempt never touched live components.
        row=PLAN['targets'][target];day=data/'preselection_pools'/target
        expected=row['consumer_expected_previous']
        if expected:
            for key,p in [('artifact_raw_sha256',day/(POOL+'.json')),('receipt_raw_sha256',day/'receipts'/(POOL+'.json')),('manifest_raw_sha256',day/'manifest.json')]:assert sha(p.read_bytes())==expected[key]
        else:
            assert not (day/(POOL+'.json')).exists() and not (day/'receipts'/(POOL+'.json')).exists()
            manifest=json.loads((day/'manifest.json').read_bytes());assert POOL not in manifest
            assert sha((day/'manifest.json').read_bytes())==row['consumer_preexisting_manifest_sha256']
        assert not pending
        return dict(target=target,status='ORIGINAL_NO_INTENT_NO_MUTATION')

def rollback_source():
    store=SafeRootStore(Path(PLAN['shared_root']));path=H/'REUSE_BINDING_INTENT_R5.json'
    if not path.exists():
        with store._lock():
            latest=store._load_latest()
            assert all(latest['entries'].get(target+'/'+ROLE)==row['shared_previous_latest_entry'] for target,row in PLAN['targets'].items())
        return dict(status='ORIGINAL_NO_INTENT_NO_MUTATION')
    intent=json.loads(path.read_bytes())
    assert set(intent['old_entries'])==set(intent['new_entries'])=={d+'/'+ROLE for d in PLAN['targets']}
    for target,row in PLAN['targets'].items():
        assert intent['old_entries'][target+'/'+ROLE]==row['shared_previous_latest_entry']
    result=rollback_shared_entries(store,intent)
    if result['errors']:raise RuntimeError(json.dumps(result,sort_keys=True))
    return result

def main():
    result=restore_independently([(target,lambda target=target:rollback_target(target)) for target in ['20261015','20261016']]+[('shared_slots',rollback_source)])
    errors=[r for r in result if r['status']=='FAILED_PRESERVED_FOR_AUDIT']
    receipt=dict(status='R5_ROLLBACK_COMPONENT_ERRORS' if errors else 'R5_EXACT_OWN_HK_ROLLBACK',steps=result,
        A_components_modified=False,foreign_components_preserved=True,immutable_runs_modified=False)
    (H/'HK_REACTIVATION_ROLLBACK_RECEIPT_R5.json').write_text(json.dumps(receipt,sort_keys=True,indent=2)+'\n')
    print(json.dumps(receipt,sort_keys=True))
    if errors:raise SystemExit(2)
if __name__=='__main__':main()
