"""Prepare one API-only inactive release with the existing exact-delta builder."""
from pathlib import Path
import importlib.util
import json
import sys

B=Path(__file__).resolve().parent
W=Path('/Users/lexi/.codex/worktrees/futu76-mac-integration-20261026/v4_app')
sys.path.insert(0,str(W))
from ops import api_release_integration as a
a.MODULE_CONTRACT_PATH=B/'control/api_module_contracts.json'
P=Path('/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist')


def save(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n')


def prepare():
    active=a.read_active_release(P)
    assert active['release_id']=='schedule-remediation-20261026-api-r2'
    assert active['release_manifest_sha256']=='6d2754c2af947ae1aa2bcd1d6d5fbed6faeae6f008f1688a6cf16d60c247d0f6'
    assert active['api_plist_sha256']=='a25fdaa0dbcca7fa68785bfe991e6c2048e4a4f71b50e9854032bbacfab2026d'
    save(B/'control/ACTIVE_BASE_IDENTITY.json',{k:v for k,v in active.items() if k not in {'manifest','inventory'}})
    relative='apps/api/v35_api/a_share_panel_history.py'
    before=(Path(active['app_root'])/relative).read_bytes();after=(W/relative).read_bytes()
    assert a.sha256_bytes(before)=='eb121a82096dc6102a81514c6f9097d33417e32f621960f79fee6a87c97daee1'
    proof,hunks=a._diff_proof(before,after)
    delta=dict(schema_version=a.DELTA_SCHEMA_VERSION,base=a._base_binding(active),
        entries=[dict(path=relative,before_sha256=a.sha256_bytes(before),after_sha256=a.sha256_bytes(after),
                      unified_diff_sha256=proof,unified_diff_hunk_count=hunks)])
    delta_path=B/'control/API_DELTA_RECEIPT.json';save(delta_path,delta)
    assert [r['path'] for r in delta['entries']]==sorted(r['path'] for r in delta['entries'])
    a._validate_delta_receipt(delta,base_identity=active)
    candidate=B/'package/futu76-mac-price-signal-api-20261026-r1'
    candidate.mkdir(parents=True,exist_ok=False)
    result=a.build_integrated_app(active_api_plist_path=P,source_root=W,candidate_root=candidate,
        delta_receipt_path=delta_path,explicit_untracked_paths=())
    inventory=a.inventory_tree(candidate/'app')
    manifest=dict(schema_version='v4.release_candidate.v1',candidate=dict(root=str(candidate),
        app_root=str(candidate/'app'),release_id=candidate.name,module_role='gateway'),
        application_inventory=dict(entries=inventory,aggregate_sha256=a.inventory_digest(inventory)),
        api_integration=result,research_only=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
    save(candidate/'release-manifest.json',manifest)
    manifest_sha=a.sha256_bytes((candidate/'release-manifest.json').read_bytes())
    verification=a.verify_api_release_candidate(candidate_root=candidate,active_api_plist_path=P,
        expected_manifest_sha256=manifest_sha)
    save(B/'control/PACKAGE_RESULT.json',dict(candidate_root=str(candidate),manifest_sha256=manifest_sha,
        verification=verification,api_source_sha256=a.sha256_bytes(after),default_pointers_changed=False,
        service_actions=0,admission='NOT_CREATED_REQUIRES_REAL_INDEPENDENT_REVIEW'))
    print(json.dumps(dict(status='PREPARED_AND_ORIGINAL_DELTA_VERIFY_PASS',candidate_root=str(candidate),
        manifest_sha256=manifest_sha,delta_paths=verification['delta_paths'],preserved=verification['non_delta_entry_count'])))


if __name__=='__main__':prepare()
