"""Repin deployed cap16/history9 Stage only after a new Main is actually live.

No helper/business code change, activation or producer call. Source is derived
from frozen a060 Stage builder; exact deployed-r2 before identities are required.
"""
from pathlib import Path
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
import plistlib
import shutil
import sys

W = Path('/Users/lexi/.codex/worktrees/stage-witness-owner-20261112/v4_app')
from_root = str(W)
if from_root not in sys.path: sys.path.insert(0, from_root)
from ops.api_release_integration import inventory_tree, inventory_digest


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def ref(p): return dict(path=str(p), sha256=sha(p))
def load(p): return json.loads(Path(p).read_bytes())
def save(p, value):
    p = Path(p); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n')
    return ref(p)
def require(value, error):
    if not value: raise RuntimeError(error)


def prepare(root, expected_main_manifest_sha256):
    root = Path(root)
    require(root.is_absolute() and not root.exists(), 'NEW_ABSOLUTE_CANDIDATE_REQUIRED')
    main_live = Path.home() / 'Library/LaunchAgents/com.lexi.v4.scheduler.plist'
    stage_live = Path.home() / 'Library/LaunchAgents/com.lexi.stage-center.scheduler.plist'
    main_raw, stage_raw = main_live.read_bytes(), stage_live.read_bytes()
    main, stage = plistlib.loads(main_raw), plistlib.loads(stage_raw)
    me, se = main['EnvironmentVariables'], stage['EnvironmentVariables']
    require(me['V4_RELEASE_MANIFEST_SHA256'] == expected_main_manifest_sha256, 'MAIN_IDENTITY_NOT_CONTROLLER_EXPECTED')
    main_manifest = Path(me['V4_RELEASE_MANIFEST_PATH'])
    require(sha(main_manifest) == expected_main_manifest_sha256, 'MAIN_MANIFEST_SHA_DRIFT')
    old_stage = Path(se['V4_APP_ROOT']); old_seal = Path(se['V4_RELEASE_MANIFEST_PATH'])
    require(sha(old_seal) == se['V4_RELEASE_MANIFEST_SHA256'], 'STAGE_MANIFEST_SHA_DRIFT')
    require(se['V4_RELEASE_MANIFEST_SHA256'] == '5ffcf399b35ee9e9f5c919ee0c8b39fb1f758f85f17cd3319a85b6e904e2ce5b', 'EXPECTED_DEPLOYED_R2_STAGE_MANIFEST')
    old_manifest = load(old_seal); entries = old_manifest['application_inventory']['entries']
    require(inventory_digest(entries) == old_manifest['application_inventory']['aggregate_sha256'], 'STAGE_INVENTORY_AGGREGATE_DRIFT')
    require(sha(stage_live) == 'f81076e8df57ac7e6bdc8be4b21026753ffcc0563878fa5d1e0f04959f4483a8', 'EXPECTED_DEPLOYED_R2_STAGE_PLIST')
    require(sha(old_stage / 'stage_center_tick_config.json') == '5412ad76b67dbe85b89349ee046eb80d09b917cb74a4b84066c023306d781cc2', 'EXPECTED_DEPLOYED_R2_CONFIG')
    old_config = load(old_stage / 'stage_center_tick_config.json')
    helper_before = old_stage / 'infrastructure/manager_input_attestation.py'
    require(sha(helper_before) == '63408260062e5f32430a00990ef716d81b103b3090cf93374b4cc6112fdf5b17', 'DEPLOYED_CAP16_HELPER_DRIFT')
    require(old_config['research_owner_binding']['manifest_sha256'] == '176b35a86b3e8587f3343b3d960aeed2b5c8584fccbeeafda2767092c909aa0a', 'EXPECTED_PREVIOUS_CURRENT_176B')
    require(expected_main_manifest_sha256 != old_config['research_owner_binding']['manifest_sha256'], 'NEW_MAIN_NOT_ACTUALLY_ACTIVATED_YET')
    app = root / 'stage/app'; app.mkdir(parents=True)
    for ent in entries:
        src = old_stage / ent['path']; dst = app / ent['path']; dst.parent.mkdir(parents=True, exist_ok=True)
        require(not src.is_symlink() and ent['kind'] == 'file' and sha(src) == ent['sha256'], 'STAGE_SOURCE_INVENTORY_DRIFT:' + ent['path'])
        shutil.copy2(src, dst)
    require(inventory_tree(app) == entries, 'STAGE_COPY_IDENTITY_DRIFT')
    release_id = root.name + '-stage'
    config = copy.deepcopy(old_config)
    require(len(config['research_historical_owner_bindings']) == 9, 'EXPECTED_DEPLOYED_NINE_HISTORICAL_OWNERS')
    config['research_owner_binding'] = dict(app_root=me['V4_APP_ROOT'], release_id=me['V4_RELEASE_ID'],
        manifest_path=str(main_manifest), manifest_sha256=expected_main_manifest_sha256)
    config['research_historical_owner_bindings'].append(copy.deepcopy(old_config['research_owner_binding']))
    require(len({r['app_root'] for r in [config['research_owner_binding'], *config['research_historical_owner_bindings']]}) == 11, 'OWNER_ROOT_DUPLICATE')
    config['release_id'] = release_id
    # No helper write: the exact deployed cap16 bytes are reused unchanged.
    hp = app / 'infrastructure/manager_input_attestation.py'
    require(sha(hp) == sha(helper_before), 'HELPER_BYTES_CHANGED_DURING_COPY')
    cp = app / 'stage_center_tick_config.json'; os.chmod(cp, 0o644); save(cp, config)
    inv = inventory_tree(app)
    changed = [a['path'] for a, b in zip(inv, entries) if a != b]
    require(len(inv) == len(entries) and set(changed) == {'stage_center_tick_config.json'}, 'UNEXPECTED_STAGE_SOURCE_DIFF')
    manifest = copy.deepcopy(old_manifest)
    manifest.update(app_root=str(app), release_id=release_id, candidate=root.name,
        activation_status='PREPARED_NOT_ACTIVATED', deployment_status='PREPARED',
        parent_release_root=str(old_seal.parent), parent_manifest_sha256=sha(old_seal),
        generated_at=datetime.now(timezone.utc).isoformat(), source_base_commit='a060e113e74d9d8b7b31a7f39c59981bf30dc0ab')
    manifest['application_inventory'] = dict(entry_count=len(inv), entries=inv, aggregate_sha256=inventory_digest(inv))
    manifest['stage_witness_owner_repin_r3'] = dict(source_script=ref(__file__),
        unchanged_cap16_helper=ref(hp), previous_historical_owners=9, preserved_historical_owners=10,
        original_current_owner_appended=copy.deepcopy(old_config['research_owner_binding']),
        original_transition_unchanged=True, helper_bytes_changed=False, numerical_or_pool_rule_changes=False)
    seal = save(root / 'stage/release-manifest.json', manifest)
    def stage_map(value):
        if isinstance(value, str) and (value == str(old_stage) or value.startswith(str(old_stage) + '/')):
            return str(app) + value[len(str(old_stage)):]
        if isinstance(value, list): return [stage_map(v) for v in value]
        if isinstance(value, dict): return {k: stage_map(v) for k, v in value.items()}
        return value
    stage_proposed = stage_map(copy.deepcopy(stage)); pe = stage_proposed['EnvironmentVariables']
    pe.update(V4_APP_ROOT=str(app), V4_RELEASE_ID=release_id, V4_RELEASE_MANIFEST_PATH=seal['path'],
              V4_RELEASE_MANIFEST_SHA256=seal['sha256'], STAGE_CENTER_CONFIG=str(cp))
    stage_plist = root / 'stage/proposed.plist'; stage_plist.write_bytes(plistlib.dumps(stage_proposed, sort_keys=False))
    (root / 'stage/before.plist').write_bytes(stage_raw)
    policy_path = Path(me['V4_RESEARCH_RETENTION_POLICY']); policy = load(policy_path)
    require(sha(policy_path) == me['V4_RESEARCH_RETENTION_POLICY_SHA256'], 'MAIN_POLICY_SHA_DRIFT')
    pins_path = Path(policy['managed_pin_inventory']['path']); pins = load(pins_path)
    require(sha(pins_path) == policy['managed_pin_inventory']['sha256'], 'MAIN_PIN_INVENTORY_SHA_DRIFT')
    pin_diffs = []
    for index, source in enumerate(pins['source_bindings']):
        require(sha(source['path']) == source['sha256'], 'EXISTING_SOURCE_PIN_DRIFT:' + source['path'])
        old = copy.deepcopy(source)
        if source['path'].startswith(str(old_stage) + '/'):
            source.update(ref(Path(stage_map(source['path']))))
        elif source['path'] == str(stage_live):
            source['sha256'] = sha(stage_plist)  # authoritative FUTURE live path, not a shadow pin
        if source != old: pin_diffs.append(dict(index=index, before=old, proposed=copy.deepcopy(source)))
    require(len(pin_diffs) == 4, 'EXACT_STAGE_FOUR_PIN_UPDATES_REQUIRED')
    new_pins = save(root / 'main-control/research_storage_pins.json', pins)
    att_path = Path(policy['single_generation_lifecycle']['reader_inventory']['path']); att = load(att_path)
    require(sha(att_path) == policy['single_generation_lifecycle']['reader_inventory']['sha256'], 'READER_ATTESTATION_SHA_DRIFT')
    selected = [x for x in att['consumers'] if x['label'] == stage['Label']]
    require(len(selected) == 1, 'EXACT_STAGE_CONSUMER_REQUIRED')
    consumer = selected[0]; old_consumer = copy.deepcopy(consumer)
    require(consumer['plist_path'] == str(stage_live) and consumer['plist_sha256'] == sha(stage_live), 'STAGE_CONSUMER_PLIST_DRIFT')
    consumer['plist_sha256'] = sha(stage_plist)
    require(len(consumer['source_refs']) == 3, 'EXACT_THREE_STAGE_CONSUMER_REFS_REQUIRED')
    consumer['source_refs'] = [ref(Path(stage_map(x['path']))) for x in consumer['source_refs']]
    att_ref = save(root / 'main-control/reader-attestation.json', att)
    policy['managed_pin_inventory'] = new_pins
    policy['single_generation_lifecycle']['reader_inventory'] = att_ref
    policy_ref = save(root / 'main-control/research_storage_policy.json', policy)
    proposed_main = copy.deepcopy(main)
    proposed_main['EnvironmentVariables'].update(V4_RESEARCH_RETENTION_POLICY=policy_ref['path'], V4_RESEARCH_RETENTION_POLICY_SHA256=policy_ref['sha256'])
    main_plist = root / 'main-control/proposed.plist'; main_plist.write_bytes(plistlib.dumps(proposed_main, sort_keys=False))
    (root / 'main-control/before.plist').write_bytes(main_raw)
    require(main_live.read_bytes() == main_raw and stage_live.read_bytes() == stage_raw, 'LIVE_OWNER_CHANGED_DURING_PREPARE')
    result = dict(status='PREPARED_NOT_ACTIVATED', root=str(root), main_business_identity_unchanged=True,
        stage=dict(app_root=str(app), before_app_root=str(old_stage), manifest=seal, proposed_plist=ref(stage_plist),
                   live_plist=str(stage_live), before_plist=ref(root/'stage/before.plist'), config=ref(cp),
                   inventory_changed=changed, helper_before=ref(helper_before), helper_after=ref(hp),
                   previous_history_count=9, historical_count=10, helper_bytes_changed=False),
        main=dict(app_root=me['V4_APP_ROOT'], release_id=me['V4_RELEASE_ID'], manifest=ref(main_manifest),
                  live_plist=str(main_live), before_plist=ref(root/'main-control/before.plist'), proposed_plist=ref(main_plist),
                  before_policy=ref(policy_path), proposed_policy=policy_ref, before_pins=ref(pins_path), proposed_pins=new_pins,
                  before_reader_attestation=ref(att_path), proposed_reader_attestation=att_ref),
        exact_stage_pin_diffs=pin_diffs, reader_stage_consumer_diff=dict(before=old_consumer, proposed=consumer),
        activation_precondition='Controller only after D11 delivery; every live before plist/source/policy/ref must still match. If Main changes regenerate candidate against its final actual identity; never install stale control refs.',
        no_live_actions=True)
    save(root / 'PREPARE_RECEIPT.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--candidate-root', type=Path, required=True)
    parser.add_argument('--expected-main-manifest-sha256', required=True)
    args = parser.parse_args()
    result = prepare(args.candidate_root, args.expected_main_manifest_sha256)
    print(json.dumps(dict(status=result['status'], root=result['root'], main_identity_unchanged=True)))
