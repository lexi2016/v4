"""Exact three-owner publication parameters; never changes a live plist/job."""
from __future__ import annotations
import argparse
import copy
import json
import os
from pathlib import Path
import plistlib
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from ops.prepare_f10_stage_binding import dump, inventory_tools, loaded_role, sha

LABELS = {"main": "com.lexi.v4.scheduler", "stage": "com.lexi.stage-center.scheduler", "api": "com.lexi.v4.api"}
IDENTITY = ("V4_APP_ROOT", "V4_RELEASE_ID", "V4_RELEASE_MANIFEST_PATH", "V4_RELEASE_MANIFEST_SHA256")


def omitted_owner_proof(ledger_root, release_id, app_root, *, first_date="00000000"):
    checked = []; matches = []
    root = Path(ledger_root) / "receipts/live"
    for date in sorted(root.iterdir()):
        if not date.is_dir() or date.name < first_date: continue
        for path in sorted(date.glob("*/*.dispatch-receipt.json")):
            raw = path.read_bytes(); row = json.loads(raw)
            checked.append({"path": str(path), "sha256": sha(raw)})
            if row.get("release_id") == release_id or row.get("app_root") == app_root:
                matches.append({"path": str(path), "sha256": sha(raw), "status": row.get("status"), "slot": row.get("slot")})
    return {"release_id": release_id, "app_root": app_root, "ledger_root": str(ledger_root), "first_date": first_date,
        "receipt_count": len(checked), "checked_receipts_sha256": sha(json.dumps(checked, sort_keys=True).encode()), "matching_receipts": matches,
        "admission": "ZERO_MATCHES_REQUIRED_UNDER_GUARD", "reason": "No valid hourly publication can exist without its bound dispatch completion; any match requires compatibility review"}


def validate_transition_publication_set(embedded, paths):
    if not paths or any(p.is_symlink() or not re.fullmatch(r'[0-9]{4}\.json', p.name) for p in paths):
        raise ValueError('TRANSITION_PUBLICATION_SET_INVALID')
    if {p.stem for p in paths} != set(embedded):
        raise ValueError('TRANSITION_PUBLICATION_RECEIPT_SET_MISMATCH')


def validate_transition_receipt(receipt, item, expected, as_of):
    from infrastructure import manager_input_attestation as attestation
    name = Path(item['path']).name
    run_id = receipt.get('run_id')
    if (receipt.get('schema_version') != 'v3_5.dispatch.v1'
        or receipt.get('release_id') != expected['release_id']
        or receipt.get('app_root') not in (None, expected['app_root'])
        or receipt.get('mode') != 'LIVE'
        or any(receipt.get(key) != expected['trade_date'] for key in ('business_date','scheduled_date','target_date'))
        or not isinstance(run_id, str) or not re.fullmatch(r'[0-9a-f]{32}', run_id)
        or name != run_id + '.dispatch-receipt.json'
        or receipt.get('slot') != Path(item['path']).parent.name
        or receipt.get('ledger_sha256') != sha(attestation.encoded({k:v for k,v in receipt.items() if k!='ledger_sha256'})[:-1])):
        raise ValueError('TRANSITION_RECEIPT_IDENTITY_INVALID')
    finished = attestation.aware(receipt.get('finished_at'))
    if finished > as_of or finished.astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d') != expected['trade_date']:
        raise ValueError('TRANSITION_RECEIPT_TIME_INVALID')


def transition_owner_proof(candidate_receipt, *, as_of):
    """Freeze the exact old-Main receipts and verified original publications."""
    from infrastructure import manager_input_attestation as attestation
    stage_info = candidate_receipt['roles']['stage']
    stage = Path(stage_info['app_root'])
    if sha((stage/'infrastructure/manager_input_attestation.py').read_bytes()) != sha(Path(attestation.__file__).read_bytes()):
        raise ValueError('TRANSITION_READER_NOT_CANDIDATE_BYTES')
    cfg = json.loads((stage / 'stage_center_tick_config.json').read_bytes())
    env = candidate_receipt['live_preimages']['main']['environment']
    expected = {'app_root': env['V4_APP_ROOT'], 'release_id': env['V4_RELEASE_ID'],
                'manifest_sha256': env['V4_RELEASE_MANIFEST_SHA256'], 'trade_date': '20261102'}
    if (cfg.get('research_transition_owner_binding') != expected
        or expected['release_id'] != 'f10-daily-20261101-c94609b4e5fff848-main'
        or expected['manifest_sha256'] != '3f9a184c28884411bfc79872b44e6b2189cd33a44bc8413da0f79b9644a83388'):
        raise ValueError('TRANSITION_OWNER_IDENTITY_INVALID')
    ledger = env['V4_DISPATCH_LEDGER_ROOT']
    old = omitted_owner_proof(ledger, expected['release_id'], expected['app_root'])
    if any(Path(row['path']).parent.parent.name != expected['trade_date'] for row in old['matching_receipts']):
        raise ValueError('TRANSITION_RECEIPT_OUTSIDE_DATE')
    embedded = {}
    for item in old['matching_receipts']:
        raw = Path(item['path']).read_bytes()
        if sha(raw) != item['sha256']:raise ValueError('TRANSITION_RECEIPT_CHANGED_DURING_SCAN')
        receipt = json.loads(raw)
        validate_transition_receipt(receipt, item, expected, as_of)
        for workload in receipt.get('workload_results', []):
            if not isinstance(workload, dict):raise ValueError('TRANSITION_RECEIPT_WORKLOAD_INVALID')
            authority = workload.get('_authoritative_payload')
            publication = authority.get('hourly_publication') if isinstance(authority, dict) else None
            if publication is None:continue
            slot = receipt.get('slot')
            if (workload.get('status') != 'SUCCEEDED' or not isinstance(publication, dict)
                or publication.get('trade_date') != expected['trade_date'] or publication.get('slot') != slot
                or not isinstance(slot, str) or not re.fullmatch(r'[0-9]{4}', slot)):
                raise ValueError('TRANSITION_EMBEDDED_PUBLICATION_INVALID')
            embedded.setdefault(slot, []).append(publication)
    data = Path(env['V4_DATA_ROOT'])
    folder = data / 'research/hourly/publication/live' / expected['trade_date']
    paths = sorted(folder.glob('*.json'))
    validate_transition_publication_set(embedded, paths)
    identity = {'V4_APP_ROOT': str(stage), 'V4_RELEASE_ID': stage_info['release_id'],
        'V4_RELEASE_MANIFEST_PATH': str(stage.parent/'release-manifest.json'),
        'V4_RELEASE_MANIFEST_SHA256': stage_info['manifest_sha256'],
        'STAGE_CENTER_CONFIG': str(stage/'stage_center_tick_config.json')}
    previous = {key: os.environ.get(key) for key in identity}
    publications = []
    try:
        os.environ.update(identity)
        for path in paths:
            publication_bytes = path.read_bytes()
            if any(value != json.loads(publication_bytes) for value in embedded[path.stem]):
                raise ValueError('TRANSITION_EMBEDDED_PUBLICATION_MISMATCH')
            record, _ = attestation.read_stage_hourly_attestation(stage_app=stage, data_root=data,
                date=expected['trade_date'], slot=path.stem, mode='LIVE', as_of=as_of)
            witness = record['completion_witness']
            if witness['release_id'] != expected['release_id']:
                raise ValueError('TRANSITION_PUBLICATION_OWNER_MISMATCH')
            if path.read_bytes() != publication_bytes:raise ValueError('TRANSITION_PUBLICATION_CHANGED_DURING_SCAN')
            publications.append({'slot': path.stem, 'publication_sha256': sha(publication_bytes),
                'input_publication_sha256': record['input_publication_sha256'],
                'source_input_sha256': record['source_input_sha256'], 'artifact_sha256': record['artifact_sha256'],
                'available_at': record['available_at'], 'finished_at': witness['finished_at'],
                'dispatch_receipt_sha256': witness['receipt_sha256'], 'dispatch_receipt_ref': witness['receipt_ref']})
    finally:
        for key, value in previous.items():
            if value is None:os.environ.pop(key, None)
            else:os.environ[key] = value
    return {'schema_version': 'v4.f10_transition_evidence_set.v1', 'as_of': as_of.isoformat(),
        'owner': expected, 'stage_manifest_sha256': stage_info['manifest_sha256'],
        'ledger_root': ledger, 'matching_receipts': old['matching_receipts'], 'publications': publications,
        'admission': 'EXACT_SET_MUST_MATCH_UNDER_GUARD'}


def prepare(candidate, output, batch1):
    if output.exists(): raise ValueError("PUBLICATION_OUTPUT_MUST_BE_NEW")
    candidate_receipt = json.loads((candidate / "candidate_receipt.json").read_bytes())
    records = {}; original = {}; output.mkdir()
    for role, label in LABELS.items():
        before = candidate_receipt["live_preimages"][role]
        env = before["environment"]
        if loaded_role(label, Path(env["V4_APP_ROOT"]), env["V4_RELEASE_MANIFEST_SHA256"]) != before:
            raise ValueError("PUBLICATION_LIVE_PREIMAGE_DRIFT:" + role)
        path = Path(before["plist_path"]); raw = path.read_bytes()
        if sha(raw) != before["plist_sha256"]: raise ValueError("PUBLICATION_PLIST_CAS_DRIFT")
        original[role] = raw
        payload = plistlib.loads(raw); after = copy.deepcopy(payload)
        new = candidate_receipt["roles"][role]; app = new["app_root"]
        after["WorkingDirectory"] = app
        after["ProgramArguments"] = [arg.replace(env["V4_APP_ROOT"], app) for arg in payload["ProgramArguments"]]
        proposed_env = after["EnvironmentVariables"]
        proposed_env.update(dict(zip(IDENTITY, (app, new["release_id"], str(Path(app).parent / "release-manifest.json"), new["manifest_sha256"]))))
        if role != "api": proposed_env["PYTHONPATH"] = proposed_env["PYTHONPATH"].replace(env["V4_APP_ROOT"], app)
        if role == "stage": proposed_env["STAGE_CENTER_CONFIG"] = app + "/stage_center_tick_config.json"
        if role == "api": proposed_env["V4_MANUAL_COLLECTION_STAGE_CONFIG"] = app + "/config/api-v4_manual_collection_stage_config.json"
        newraw = plistlib.dumps(after, sort_keys=True)
        (output / (role + ".original.plist")).write_bytes(raw); (output / (role + ".proposed.plist")).write_bytes(newraw)
        records[role] = {"label": label, "preimage": {key: env[key] for key in IDENTITY}, "candidate": new,
            "original_plist": str(output / (role + ".original.plist")), "original_plist_sha256": sha(raw),
            "proposed_plist": str(output / (role + ".proposed.plist")), "proposed_plist_sha256": sha(newraw)}
    main_env = plistlib.loads(original["main"])["EnvironmentVariables"]
    proof = omitted_owner_proof(main_env["V4_DISPATCH_LEDGER_ROOT"], main_env["V4_RELEASE_ID"], main_env["V4_APP_ROOT"])
    stage_app = Path(records['stage']['candidate']['app_root'])
    stage_config = json.loads((stage_app/'stage_center_tick_config.json').read_bytes())
    transition_proof = None
    if stage_config.get('research_transition_owner_binding') is not None:
        cutoff = datetime.now(ZoneInfo('Asia/Shanghai'))
        transition_proof = transition_owner_proof(candidate_receipt, as_of=cutoff)
        if proof['matching_receipts'] != transition_proof['matching_receipts']:
            raise ValueError('TRANSITION_RECEIPT_SET_CHANGED_DURING_PREPARE')
        proof['admission'] = 'TRANSITION_OWNER_RETAINED_NOT_ZERO'
        proof['reason'] = 'Retained for legacy rollback ledger reference; forward admission uses exact transition_owner_proof.'
    elif proof['matching_receipts']:
        raise ValueError('OMITTED_MAIN_HAS_RECEIPTS_COMPATIBILITY_REQUIRED')
    protected = []
    for path in sorted((Path.home() / "Library/LaunchAgents").glob("com.lexi.*.plist")):
        label = plistlib.loads(path.read_bytes())["Label"]
        if label not in LABELS.values(): protected.append({"label": label, "plist_path": str(path), "plist_sha256": sha(path.read_bytes())})
    stage_app = Path(records["stage"]["candidate"]["app_root"])
    manual = Path(records["api"]["candidate"]["app_root"]) / "config/api-v4_manual_collection_stage_config.json"
    api_env = candidate_receipt["live_preimages"]["api"]["environment"]
    panel_env = {key: value for key, value in api_env.items() if key.startswith(("V4_RESEARCH_PANEL_", "V4_WORKBENCH_"))}
    external = {}
    for key in ("V4_RESEARCH_PANEL_ASSET_MANIFEST", "V4_WORKBENCH_HOST_BINDING"):
        path = Path(panel_env[key]); external[key] = {"path": str(path), "sha256": sha(path.read_bytes())}
    if external["V4_WORKBENCH_HOST_BINDING"]["sha256"] != panel_env["V4_WORKBENCH_HOST_BINDING_SHA256"]:
        raise ValueError("CURRENT_HOST_BINDING_SHA_CHANGED")
    tools = inventory_tools(Path(api_env["V4_APP_ROOT"]))
    entries = tools.inventory_tree(Path(panel_env["V4_RESEARCH_PANEL_ROOT"]))
    external["panel_inventory"] = {"entry_count": len(entries), "aggregate_sha256": tools.inventory_digest(entries)}
    if transition_proof is not None and transition_owner_proof(candidate_receipt, as_of=cutoff) != transition_proof:
        raise ValueError('TRANSITION_EVIDENCE_CHANGED_DURING_PREPARE')
    plan = {"schema_version": "v4.runtime_main_stage_api_publication.v1", "status": "PREPARED_NOT_AUTHORIZED_TO_ACTIVATE",
        "roles": records, "forward_order": ["main", "stage", "api"], "rollback_order": ["api", "stage", "main"],
        "main_binding": json.loads((stage_app / "stage_center_tick_config.json").read_bytes())["research_owner_binding"],
        "manual_config": {"after_path": str(manual), "after_sha256": sha(manual.read_bytes())},
        "protected_labels": protected, "protected_external": external, "preserved_panel_environment": panel_env,
        "omitted_main_owner_zero_proof": proof,
        "candidate_receipt_path": str(candidate / 'candidate_receipt.json'),
        "candidate_receipt_sha256": sha((candidate / 'candidate_receipt.json').read_bytes()),
        "requires_future_explicit_activation_authorization": True,
        "RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
    if transition_proof is not None:plan['transition_owner_proof'] = transition_proof
    dump(output / "publication-plan.json", plan)
    return plan


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("candidate", "output", "batch1"): parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args(); plan = prepare(args.candidate, args.output, args.batch1)
    print(json.dumps({"status": plan["status"], "plan_path": str(args.output / "publication-plan.json"), "omitted_owner_receipts": len(plan["omitted_main_owner_zero_proof"]["matching_receipts"])}))
