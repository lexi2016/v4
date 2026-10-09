from __future__ import annotations
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

E = Path('/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_REAL_RESULT_RECOVERY_20261009')
RUN = E / 'outputs/us_mapping_recovery/runs/20261009T155524+0800'
MANAGER = RUN / 'manager_state'
SOURCE = E / 'candidate/original_r3_business_source'
OUT = E / 'review/isolated_owner_readback_20261009.json'
DATE = '20261009'
MAP_RUN = 'a95450cd4b264fb6840308d7d2681cf6'
PLAN_OLD = '5244092d1606430690fb903a6301b35c'
PLAN_FINAL = 'dba211c2677045afb4e0ef8c990367ee'
EXPECTED = {
    'scope_sha256': '1d5bbab2269c1f0f998ccacb80e31b75cab108f9abd1f3e705c532c8e1b1bf83',
    'receipt_sha256': '4e4030934504ecc75beff43009a26fa3cdea4df819351f4688e950b54a471f80',
    'announcement_sha256': '9ec9d0f6357b081702567dc3ba481602edc3f0d5764a68e14de5d6965024fe85',
    'input_manifest_sha256': 'd98d586348c8aa6021ba24d92ae72f51cceacd37498fd1edfab778112851d09a',
}
checks: dict[str, dict] = {}

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def load(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))

def record(name: str, ok: bool, detail=None):
    checks[name] = {'status': 'PASS' if ok else 'FAIL', 'detail': detail}

scope = E / 'SCOPE.md'
receipt_path = E / 'evidence/actual_owner_recovery_receipt_20261009.json'
announcement_path = E / 'evidence/announcement_handoff_20261009.md'
input_manifest_path = E / 'evidence/us_mapping_recovery_input_manifest.json'
receipt = load(receipt_path)
input_manifest = load(input_manifest_path)
record('frozen_scope_and_named_evidence_hashes',
       sha(scope) == EXPECTED['scope_sha256']
       and sha(receipt_path) == EXPECTED['receipt_sha256']
       and sha(announcement_path) == EXPECTED['announcement_sha256']
       and sha(input_manifest_path) == EXPECTED['input_manifest_sha256'],
       {'scope': sha(scope), 'receipt': sha(receipt_path),
        'announcement': sha(announcement_path), 'input_manifest': sha(input_manifest_path)})

# Verify exact source files and their isolated copies against the frozen input manifest.
source_base = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/state/data')
input_copy = E / 'outputs/us_mapping_recovery/input_data'
input_hashes = {}
for rel in ('research/peripherals/20261008/external_finance.json',
            'receipts/research/peripherals/20261008/external_finance.json',
            'research/peripherals/manifest.json'):
    src = source_base / rel
    copied = input_copy / rel
    input_hashes[rel] = {'source_sha256': sha(src), 'isolated_sha256': sha(copied),
                         'same_bytes': src.read_bytes() == copied.read_bytes()}
expected_input_hashes = {x['relative_path']: x['sha256'] for x in input_manifest['inputs']}
record('input_copy_and_manifest_sha',
       all(v['same_bytes'] and v['source_sha256'] == expected_input_hashes[k]
           for k, v in input_hashes.items()), input_hashes)

payload_path = source_base / 'research/peripherals/20261008/external_finance.json'
source_receipt_path = source_base / 'receipts/research/peripherals/20261008/external_finance.json'
source_manifest_path = source_base / 'research/peripherals/manifest.json'
dispatch_path = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/state/dispatcher/receipts/live/20261009/0415/11438e3e254c42a9b3222b324795d85a.dispatch-receipt.json')
payload, source_receipt, source_manifest, dispatch = map(load,
    (payload_path, source_receipt_path, source_manifest_path, dispatch_path))
post_close = next((x for x in payload.get('us_session_captures', [])
                   if x.get('capture_phase') == 'POST_CLOSE'
                   and x.get('us_session_date') == '20261008'), None)
workload = next((x for x in dispatch.get('workload_results', [])
                 if x.get('workload_id') == 'us_market_digest'), {})
record('authenticated_us_20261008_post_close_lineage',
       payload.get('trade_date') == '20261008'
       and payload.get('source') == 'external_finance'
       and payload.get('original_time_capture') is True
       and payload.get('status') == 'READY'
       and post_close is not None
       and post_close.get('original_time_capture') is True
       and source_receipt.get('payload_sha256') == sha(payload_path)
       and source_manifest.get('research/peripherals/20261008/external_finance.json') == sha(payload_path)
       and dispatch.get('run_id') == input_manifest.get('input_dispatch_run_id')
       and workload.get('capture_phase') == 'POST_CLOSE'
       and workload.get('capture_artifact_verified') is True
       and workload.get('new_capture_verified') is True
       and workload.get('payload_sha256') == sha(payload_path)
       and workload.get('receipt_verified') is True,
       {'payload_sha256': sha(payload_path), 'source_receipt_sha256': sha(source_receipt_path),
        'source_manifest_sha256': sha(source_manifest_path), 'dispatch_receipt_sha256': sha(dispatch_path),
        'capture': {k: post_close.get(k) for k in ('capture_phase','capture_window_start','capture_window_end','captured_at','us_session_date','run_id')},
        'dispatch_run_id': dispatch.get('run_id'), 'dispatch_status': dispatch.get('status'),
        'capture_artifact_verified': workload.get('capture_artifact_verified'),
        'receipt_verified': workload.get('receipt_verified')})

# Check the exact, recorded source baselines without changing them.
source_paths = {
    'manager_announcement_supervisor.py': 'infrastructure/scheduling/manager_announcement_supervisor.py',
    'manager_research_router.py': 'apps/api/v35_api/manager_research_router.py',
    'plan_owner_dispatch.py': 'v4/manager_research/plan_owner_dispatch.py',
    'run_manager_daily_announcement.py': 'ops/run_manager_daily_announcement.py',
    'us_mapping_research.py': 'v4/manager_research/us_mapping_research.py',
    'workspace.py': 'v4/manager_research/workspace.py',
}
source_hashes = {name: sha(SOURCE / rel) for name, rel in source_paths.items()}
record('frozen_original_owner_source_sha',
       all(source_hashes[name] == expected for name, expected in receipt['inspected_code_sha256'].items()),
       source_hashes)

# Run original read-only owner validators against only the isolated manager store.
sys.path.insert(0, str(SOURCE))
from v4.manager_research.store import ManagerResearchStore
from v4.manager_research.workspace import _read_plan, verified_plan_attempt
from v4.manager_research.us_mapping_research import read_workspace_mapping
store = ManagerResearchStore(MANAGER)
saved_plan = _read_plan(store, DATE)
plan_attempt = verified_plan_attempt(store, saved_plan)
mapping_result = read_workspace_mapping(SimpleNamespace(store=store), DATE)
daily = mapping_result['daily_run']
plan_ws = saved_plan['workspace']
plan_map = plan_ws['us_mapping_research']['daily_run']
final_plan_summary = load(RUN / 'plan_runs/20261009T160130+0800_summary.json')
old_plan_summary = load(RUN / 'actual_plan_result_summary.json')
final_product_path = MANAGER / 'workspace_plans' / DATE / f'{PLAN_FINAL}.json'
latest_product_path = MANAGER / 'workspace_plans' / DATE / 'latest.json'
final_attempt_path = MANAGER / 'workspace_plan_runs' / DATE / f'{PLAN_FINAL}.json'
latest_attempt_path = MANAGER / 'workspace_plan_runs' / DATE / 'latest.json'
record('original_owner_mapping_readback',
       daily.get('run_id') == MAP_RUN
       and daily.get('status') == 'VALID_EMPTY'
       and daily.get('run_readback', {}).get('status') == 'VERIFIED'
       and daily.get('coverage', {}).get('configured_us_universe_count') == 33
       and daily.get('coverage', {}).get('available_us_universe_count') == 33
       and daily.get('coverage', {}).get('reviewed_us_symbol_count') == 4
       and daily.get('coverage', {}).get('matched_us_symbol_count') == 0
       and daily.get('coverage', {}).get('matched_hk_relation_count') == 0
       and daily.get('coverage', {}).get('full_market_coverage') is False
       and not daily.get('gaps') and not daily.get('matches'),
       {'run_id': daily.get('run_id'), 'status': daily.get('status'),
        'run_readback': daily.get('run_readback'), 'coverage': daily.get('coverage'),
        'coverage_scope': daily.get('coverage_scope'),
        'gap_count': len(daily.get('gaps') or []), 'match_count': len(daily.get('matches') or [])})
record('original_owner_final_plan_same_run_sha_input_readback',
       saved_plan is not None
       and saved_plan.get('run_id') == PLAN_FINAL
       and plan_attempt.get('run_id') == PLAN_FINAL
       and plan_attempt.get('state') == 'PARTIAL'
       and saved_plan.get('input_identity') == plan_attempt.get('input_identity')
       and saved_plan.get('owner') == 'ManagerResearchJobService.refresh_workspace_plan'
       and saved_plan.get('target_trade_date') == DATE
       and saved_plan.get('execution_context', {}).get('natural_run_verified') is False
       and final_plan_summary.get('plan_product', {}).get('run_readback', {}).get('status') == 'VERIFIED'
       and final_plan_summary.get('plan_product', {}).get('run_readback', {}).get('run_id') == PLAN_FINAL
       and final_plan_summary.get('plan_product', {}).get('run_readback', {}).get('input_identity') == saved_plan.get('input_identity')
       and final_plan_summary.get('plan_product', {}).get('run_readback', {}).get('artifact_sha256') == saved_plan.get('sha256')
       and final_plan_summary.get('mapping_run_id') == MAP_RUN
       and final_plan_summary.get('mapping_artifact_sha256') == daily.get('artifact_sha256')
       and plan_map.get('run_id') == MAP_RUN
       and plan_map.get('artifact_sha256') == daily.get('artifact_sha256')
       and saved_plan.get('workspace', {}).get('stocks') == []
       and final_plan_summary.get('stock_count') == 0,
       {'mapping_run_id': daily.get('run_id'), 'mapping_artifact_sha256': daily.get('artifact_sha256'),
        'plan_run_id': saved_plan.get('run_id'), 'plan_product_sha256': saved_plan.get('sha256'),
        'plan_input_identity': saved_plan.get('input_identity'), 'plan_attempt_state': plan_attempt.get('state'),
        'plan_run_readback': final_plan_summary.get('plan_product', {}).get('run_readback'),
        'plan_stock_count': final_plan_summary.get('stock_count'),
        'plan_workspace_gaps': final_plan_summary.get('workspace_gaps')})
record('final_vs_superseded_plan_pointer_and_root',
       load(latest_attempt_path).get('run_id') == PLAN_FINAL
       and load(latest_product_path).get('run_id') == PLAN_FINAL
       and load(final_attempt_path) == load(latest_attempt_path)
       and load(final_product_path) == load(latest_product_path)
       and old_plan_summary.get('workspace_plan_attempt', {}).get('run_id') == PLAN_OLD
       and old_plan_summary.get('source_screen_root_read_only') != final_plan_summary.get('source_screen_root_read_only')
       and final_plan_summary.get('source_screen_root_read_only') == receipt['scope']['screen_read_root'],
       {'superseded_1558_run_id': old_plan_summary.get('workspace_plan_attempt', {}).get('run_id'),
        'superseded_1558_screen_root': old_plan_summary.get('source_screen_root_read_only'),
        'latest_1601_run_id': saved_plan.get('run_id'),
        'latest_1601_screen_root': final_plan_summary.get('source_screen_root_read_only'),
        'latest_attempt_state': load(latest_attempt_path).get('state'),
        'latest_plan_product_file_sha256': sha(latest_product_path),
        'run_plan_product_file_sha256': sha(final_product_path),
        'screen_status': plan_ws.get('market_screen', {}).get('status'),
        'screen_gaps': plan_ws.get('market_screen', {}).get('gaps')})

# Summaries and output bytes are checked against the frozen receipt.
summary_hashes = {
    'us_mapping_summary': sha(RUN / 'actual_owner_result_summary.json'),
    'superseded_1558_plan_summary': sha(RUN / 'actual_plan_result_summary.json'),
    'final_1601_plan_summary': sha(RUN / 'plan_runs/20261009T160130+0800_summary.json'),
    'final_plan_product': sha(final_product_path),
}
record('summary_and_product_file_hashes',
       summary_hashes['us_mapping_summary'] == receipt['actual_owner_runs']['us_mapping']['summary_sha256']
       and summary_hashes['superseded_1558_plan_summary'] == receipt['actual_owner_runs']['plan_summary_sha256'][0]
       and summary_hashes['final_1601_plan_summary'] == receipt['actual_owner_runs']['plan_summary_sha256'][1]
       and summary_hashes['final_plan_product'] == receipt['actual_owner_runs']['plan_attempts'][1]['product_file_sha256'],
       summary_hashes)
record('unresolved_channel_and_safety_boundaries',
       receipt['unresolved_channels']['announcement']['status'] == 'NOT_RUN'
       and receipt['unresolved_channels']['hk']['status'] == 'CANNOT_CONFIRM'
       and receipt['unresolved_channels']['hk']['used_695_row_handoff'] is False
       and receipt['scope']['live_api_or_ui_invoked'] is False
       and receipt['safety'] == {'RESEARCH_ONLY': True, 'production_allowed': False,
                                  'buy_gate_updated': False, 'orders_sent': False}
       and final_plan_summary.get('announcement_review_status') == 'NOT_RUN'
       and plan_ws.get('market_screen', {}).get('status') == 'CANNOT_CONFIRM'
       and plan_ws.get('market_screen', {}).get('gaps') == ['SCREEN_SECURITY_MASTER_READ_FAILED:StoreError'],
       {'announcement': receipt['unresolved_channels']['announcement'],
        'hk': receipt['unresolved_channels']['hk'],
        'live_api_or_ui_invoked': receipt['scope']['live_api_or_ui_invoked'],
        'safety': receipt['safety'], 'screen_gaps': plan_ws.get('market_screen', {}).get('gaps')})

failed = [name for name, item in checks.items() if item['status'] != 'PASS']
result = {
    'schema_version': 'v4.manager.isolated_owner_readback_review.v1',
    'reviewed': 'PASS' if not failed else 'FAIL',
    'behavior_verified': 'PASS' if not failed else 'FAIL',
    'scope': 'isolated original-owner readback only; no owner rerun, API, UI, service, source, or real-state write',
    'command': "'/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python' review/verify_isolated_owner_readback_20261009.py",
    'original_readback_functions': ['v4.manager_research.us_mapping_research.read_workspace_mapping', 'v4.manager_research.workspace._read_plan', 'v4.manager_research.workspace.verified_plan_attempt'],
    'target_trade_date': DATE,
    'mapping': {'run_id': daily.get('run_id'), 'status': daily.get('status'),
                'coverage': daily.get('coverage'), 'matches': len(daily.get('matches') or []),
                'gaps': daily.get('gaps')},
    'plan': {'run_id': saved_plan.get('run_id'), 'status': plan_attempt.get('state'),
             'stock_count': len(plan_ws.get('stocks') or []),
             'input_identity': saved_plan.get('input_identity'),
             'product_sha256': saved_plan.get('sha256'),
             'attempt_sha256': plan_attempt.get('sha256'),
             'mapping_run_id': plan_map.get('run_id'),
             'mapping_artifact_sha256': plan_map.get('artifact_sha256'),
             'gaps': final_plan_summary.get('workspace_gaps'),
             'readback_status': final_plan_summary.get('plan_product', {}).get('run_readback', {}).get('status')},
    'p0_findings': [], 'p1_findings': [],
    'p2_findings': [],
    'p2_risks': [{
        'status': 'CANNOT_CONFIRM',
        'risk': 'A downstream consumer could overread VALID_EMPTY plus gaps=[] as full universe exhaustion.',
        'evidence': {'coverage_scope': plan_map.get('coverage_scope'),
                     'reviewed_us_symbol_count': daily.get('coverage', {}).get('reviewed_us_symbol_count'),
                     'configured_us_universe_count': daily.get('coverage', {}).get('configured_us_universe_count'),
                     'full_market_coverage': daily.get('coverage', {}).get('full_market_coverage'),
                     'plan_status': plan_attempt.get('state'), 'plan_stock_count': len(plan_ws.get('stocks') or [])},
        'consumer_misinterpretation_observed': False,
    }],
    'cannot_confirm': [
        'full-market US coverage or all 33 configured symbols reviewed; only 4 relations reviewed and full_market_coverage=false',
        'complete manager selection: final plan is PARTIAL with 0 stocks and documented owner gaps',
        'announcement Reader/Reviewer product, HK exact-date/security-master result, live API/UI, and natural run',
        'any downstream consumer misinterpreting VALID_EMPTY/gaps=[] as end-to-end completion',
    ],
    'not_run': {'live_api': True, 'ui': True, 'natural': True,
                'full_regression_suite': True, 'owner_rerun': True},
    'checks': checks,
    'failed_checks': failed,
}
OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
print(json.dumps(result, ensure_ascii=False, sort_keys=True))
if failed:
    raise SystemExit(1)
