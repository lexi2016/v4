"""Release-only durable intents and exact component/event rollback.

The accepted store public validators and write implementations are unchanged.
The local subclass records an intent while their existing import lock is held.
"""
from pathlib import Path
import hashlib,json,os
from infrastructure.preselection_pool_store import PreselectionPoolStore
from infrastructure.data_store import _canonical_bytes,_sha256
from infrastructure.interprocess_lock import owned_interprocess_lock

POOL='hkconnect_d1_top100'
ROLE='HK_CONNECT_D1_TOP100_0_2'
sha=lambda raw:hashlib.sha256(raw).hexdigest()

def durable_intent(path,value):
    """Exclusive complete file, fsynced before any live mutation."""
    raw=_canonical_bytes(value)
    with open(path,'xb') as stream:
        stream.write(raw);stream.flush();os.fsync(stream.fileno())
    directory=os.open(path.parent,os.O_RDONLY)
    try:os.fsync(directory)
    finally:os.close(directory)
    return sha(raw)

class IntentPoolStore(PreselectionPoolStore):
    def configure_intents(self,directory,targets):
        self.intent_directory=Path(directory);self.intent_targets=targets
        return self

    def _record_intent(self,target,payload,receipt,old_manifest,*,snapshot=None):
        assert payload['pool_id']==POOL and payload['market']=='HK'
        row=self.intent_targets[target]
        artifact_rel,receipt_rel=self._relative(target,POOL)
        manifest_rel=f'preselection_pools/{target}/manifest.json'
        new_digest=_sha256(payload)
        assert new_digest==row['new_consumer_sha256'],'INTENT_NEW_PAYLOAD_PIN'
        old_manifest_raw=self._io.read_bytes(manifest_rel)
        assert sha(old_manifest_raw)==row['consumer_preexisting_manifest_sha256'],'INTENT_MANIFEST_PREIMAGE'
        assert sha(_canonical_bytes({k:v for k,v in old_manifest.items() if k!=POOL}))==row['consumer_non_HK_manifest_sha256'],'INTENT_NON_HK_PREIMAGE'
        if snapshot is not None:
            expected=row['consumer_expected_previous']
            assert expected and all(snapshot[k]==v for k,v in expected.items()),'INTENT_FULL_OLD_CAS'
            assert snapshot['artifact']['pool_id']==POOL and snapshot['artifact']['market']=='HK'
            self._archive_recovery_revision(target,POOL,snapshot['artifact_sha256'],snapshot['artifact'],snapshot['receipt'])
            old_components=dict(artifact=snapshot['artifact_raw_sha256'],receipt=snapshot['receipt_raw_sha256'],manifest=snapshot['manifest_raw_sha256'])
            old_digest=snapshot['artifact_sha256']
        else:
            assert row['consumer_expected_previous'] is None and POOL not in old_manifest,'INTENT_CREATE_SCOPE'
            for rel in [artifact_rel,receipt_rel]:
                try:self._io.read_bytes(rel)
                except FileNotFoundError:pass
                else:raise ValueError('INTENT_CREATE_RACE_OR_PARTIAL')
            old_components=dict(artifact=None,receipt=None,manifest=sha(old_manifest_raw));old_digest=None
        # Standard revision paths, not another raw-data backup/floor.
        self._archive_recovery_revision(target,POOL,new_digest,payload,receipt)
        new_manifest=dict(old_manifest);new_manifest[POOL]=new_digest
        pending=self._pending_commit(snapshot,payload=payload,receipt=receipt,manifest=new_manifest) if snapshot is not None else None
        intent=dict(schema_version='hk_reactivation_component_intent.v5',target_date=target,pool_id=POOL,
            old=old_components,new=dict(artifact=sha(_canonical_bytes(payload)),receipt=sha(_canonical_bytes(receipt)),manifest=sha(_canonical_bytes(new_manifest))),
            old_semantic_sha256=old_digest,new_semantic_sha256=new_digest,
            old_manifest_entry=old_manifest.get(POOL),new_manifest_entry=new_digest,
            non_HK_manifest_sha256=row['consumer_non_HK_manifest_sha256'],
            relative=dict(artifact=artifact_rel,receipt=receipt_rel,manifest=manifest_rel),
            pending_relative=f'preselection_pending_commits/{target}/{POOL}.json',
            pending_sha256=sha(_canonical_bytes(pending)) if pending else None,
            source_run_id=payload['source_run_id'],source_sha256=payload['source_sha256'])
        durable_intent(self.intent_directory/f'CONSUMER_INTENT_{target}_R5.json',intent)

    def _commit_main_snapshot(self,snapshot,*,payload,receipt,manifest):
        # Called by accepted refresh inside its existing import lock, after all
        # proof/source/row/full-preimage checks, immediately before its journal.
        target=str(payload['trade_date'])
        assert manifest==dict(snapshot['manifest'],**{POOL:_sha256(payload)})
        self._record_intent(target,payload,receipt,snapshot['manifest'],snapshot=snapshot)
        return super()._commit_main_snapshot(snapshot,payload=payload,receipt=receipt,manifest=manifest)

    def _materialize_unlocked(self,payload):
        # Public materialize already holds the same import lock. Require true
        # absence here as well; never accept even a same-payload racing create.
        target=str(payload['trade_date']);assert payload['pool_id']==POOL
        assert self.intent_targets[target]['consumer_expected_previous'] is None
        manifest_rel=f'preselection_pools/{target}/manifest.json'
        old_manifest=self._read(manifest_rel)
        artifact_rel,receipt_rel=self._relative(target,POOL)
        receipt=self._receipt(trade_date=target,pool_id=POOL,artifact_path=artifact_rel,
            artifact_sha256=_sha256(payload),payload=payload)
        self._record_intent(target,payload,receipt,old_manifest)
        return super()._materialize_unlocked(payload)

def _raw(store,relative):
    try:return store._io.read_bytes(relative)
    except FileNotFoundError:return None

def _revision(store,target,digest):
    prefix=f'preselection_revisions/{target}/{POOL}/{digest}'
    payload=store._read(prefix+'.json');record=store._read(prefix+'.receipt.json')
    assert _sha256(payload)==digest and record['artifact_sha256']==digest,'REVISION_PIN'
    receipt=record['main_receipt']
    assert receipt==store._receipt(trade_date=target,pool_id=POOL,
        artifact_path=f'preselection_pools/{target}/{POOL}.json',artifact_sha256=digest,payload=payload),'REVISION_RECEIPT'
    return dict(artifact=_canonical_bytes(payload),receipt=_canonical_bytes(receipt))

def rollback_consumer(store,intent):
    """Caller holds import lock; classify every component before touching any."""
    target=intent['target_date'];assert intent['pool_id']==POOL
    assert set(intent['relative'])=={'artifact','receipt','manifest'}
    assert intent['relative']==dict(artifact=f'preselection_pools/{target}/{POOL}.json',
        receipt=f'preselection_pools/{target}/receipts/{POOL}.json',manifest=f'preselection_pools/{target}/manifest.json')
    current={k:_raw(store,rel) for k,rel in intent['relative'].items()}
    before={k:sha(raw) if raw is not None else None for k,raw in current.items()}
    for key,value in before.items():
        assert value in [intent['old'][key],intent['new'][key]],'FOREIGN_COMPONENT:'+key
    assert current['manifest'] is not None
    manifest=json.loads(current['manifest'])
    non_hk={k:v for k,v in manifest.items() if k!=POOL}
    assert sha(_canonical_bytes(non_hk))==intent['non_HK_manifest_sha256'],'FOREIGN_NON_HK_MANIFEST'
    pending=_raw(store,intent['pending_relative'])
    if pending is not None:
        assert intent['pending_sha256'] and sha(pending)==intent['pending_sha256'],'FOREIGN_HK_PENDING'
    desired={}
    if intent['old_semantic_sha256'] is not None:
        desired.update(_revision(store,target,intent['old_semantic_sha256']))
    else:desired.update(artifact=None,receipt=None)
    old_manifest=dict(non_hk)
    if intent['old_manifest_entry'] is not None:old_manifest[POOL]=intent['old_manifest_entry']
    desired['manifest']=_canonical_bytes(old_manifest)
    assert all((sha(raw) if raw is not None else None)==intent['old'][key] for key,raw in desired.items()),'OLD_POSTIMAGE_NOT_PROVEN'
    # Verify the new immutable revision before treating its components as ours.
    new_revision=_revision(store,target,intent['new_semantic_sha256'])
    assert all(sha(raw)==intent['new'][key] for key,raw in new_revision.items()),'NEW_POSTIMAGE_NOT_PROVEN'
    for key in ['manifest','receipt','artifact']:
        raw=current[key];wanted=desired[key];relative=intent['relative'][key]
        if raw==wanted:continue
        if wanted is None:
            assert raw is not None and sha(raw)==intent['new'][key]
            store._io.unlink_if_same(relative,raw)
        else:store._io.write_bytes(relative,wanted)
    if pending is not None:
        assert _raw(store,intent['pending_relative'])==pending
        store._io.unlink_if_same(intent['pending_relative'],pending)
    after={k:sha(raw) if (raw:=_raw(store,rel)) is not None else None for k,rel in intent['relative'].items()}
    assert after==intent['old']
    return dict(target=target,status='EXACT_COMPONENTS_RESTORED',before=before,after=after,own_pending_removed=pending is not None,non_HK_unchanged=True)

def rollback_shared_entries(store,intent):
    results=[];errors=[]
    with store._lock():
        latest=store._load_latest();entries=dict(latest['entries'])
        for key,old in intent['old_entries'].items():
            current=entries.get(key);post=intent['new_entries'][key]
            if current==old:results.append(dict(slot=key,status='ALREADY_ORIGINAL'));continue
            if current!=post:
                errors.append(dict(slot=key,error='FOREIGN_FULL_POINTER_EVENT'));continue
            if old is None:entries.pop(key)
            else:entries[key]=old
            results.append(dict(slot=key,status='EXACT_OWN_EVENT_RESTORED'))
        if entries!=latest['entries']:
            store._write_json(store.latest_path,{**latest,'entries':entries})
    return dict(results=results,errors=errors)

def restore_independently(actions):
    """Do not let one failed safe rollback block other independent restores."""
    results=[]
    for name,callback in actions:
        try:
            detail=callback();results.append(dict(step=name,status='RESTORED_OR_ALREADY_ORIGINAL',detail=detail))
        except BaseException as error:
            results.append(dict(step=name,status='FAILED_PRESERVED_FOR_AUDIT',error_type=type(error).__name__,error=str(error)))
    return results
