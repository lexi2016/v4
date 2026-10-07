# Guarded v4 owner import command

Run this once only after the independent v4 product/rebind receipt is `REVIEWED_PASS`. Set `ANNOUNCEMENT_PRODUCT_REVIEW_RECEIPT` to that reviewer receipt. This command does not call the catalog owner or fetch listing pages; its only write is `ManagerResearchJobService.import_announcement_analysis(product)`. It preserves the previous catalog-import failure and writes separate analysis-import attempt and terminal receipts. Do not run it if either new receipt already exists.

Before loading the runtime, it requires the LaunchAgent-resolved app root, release manifest SHA, and `apps/api/v35_api/app.py` SHA to match the approved `announcement-daily-20261007-r2` release. The successful terminal receipt retains those observed runtime identities and both post-import owner/API date and PIT readbacks.

The reviewer receipt must bind product SHA `7b27fe7d40e9c12db3d56751cc789c6eb84515bb2392fc1b00a3bc4a5fd38278`, v4 product receipt file SHA `9b20d85cd22c611c040157cd97a5faabc5392b8761717e115e008c7428c6cbc5`, and catalog-equivalence receipt file SHA `7f9c8964c0beebfc742b9cdb50ecb0ba9a661e38489233ffde0d064313c3f6c5`.

```bash
TASK='/Users/lexi/Desktop/学习/agents调试/V4_ANNOUNCEMENT_DAILY_REPAIR_20261007'
PY='/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python'
ANNOUNCEMENT_PRODUCT_REVIEW_RECEIPT="$TASK/INDEPENDENT_PRODUCT_V4_REBIND_REVIEW_RECEIPT.json" \
TASK_ROOT="$TASK" \
"$PY" - <<'PY'
import hashlib, importlib, json, os, sys, urllib.parse
from datetime import datetime, timezone
from pathlib import Path

task = Path(os.environ['TASK_ROOT']).resolve()
sys.path.insert(0, str(task))
ops = importlib.import_module('guarded_announcement_import')
target, publication = '20261007', '2026-10-06'
catalog_run = 'b640f4477a1c43569f225d139cdf8669'
catalog_sha = 'b01d28d9c27e511479b7bcdce45c62918895fd6cdaf782631c50eec45361b7a7'
product_sha = '7b27fe7d40e9c12db3d56751cc789c6eb84515bb2392fc1b00a3bc4a5fd38278'
approved_root = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/announcement-daily-20261007-r2/app').resolve()
approved_manifest_sha = 'dffcde634d7eed5c088b202e9128e11296923b93e2053fd184876be85c638b59'
approved_app_sha = '909bdccecadf36c70f791a2c4c0d818371f4da68762e4cff40f9786e4613f80e'
product_path = task / 'daily_runs/20261007_20261006/evidence/analysis_product_20261007_v4.json'
product_receipt_path = task / 'daily_runs/20261007_20261006/evidence/ANALYSIS_CANDIDATE_PRODUCT_RECEIPT_v4.json'
equivalence_path = task / 'daily_runs/20261007_20261006/active_import/catalog_equivalence_reconciliation_v1.json'
failed_catalog_receipt = task / 'daily_runs/20261007_20261006/active_import/import_receipt.json'
attempt_path = task / 'daily_runs/20261007_20261006/active_import/analysis_v4_import_attempt.json'
terminal_path = task / 'daily_runs/20261007_20261006/active_import/analysis_v4_import_receipt.json'
state = ops.STATE_ROOT

def raw_sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def check(condition, label):
    if not condition:
        raise RuntimeError('PRECONDITION_OR_READBACK_FAILED:' + label)

check(not attempt_path.exists() and not terminal_path.exists(), 'NO_PRIOR_ANALYSIS_IMPORT_ATTEMPT')
review_path = Path(os.environ['ANNOUNCEMENT_PRODUCT_REVIEW_RECEIPT']).expanduser().resolve()
review = json.loads(review_path.read_text(encoding='utf-8'))
check(review.get('status') == 'REVIEWED_PASS', 'INDEPENDENT_REVIEW_PASS')
check(review.get('product_sha256') == product_sha, 'REVIEWED_PRODUCT_SHA')
check(review.get('product_receipt_file_sha256') == raw_sha(product_receipt_path), 'REVIEWED_PRODUCT_RECEIPT_SHA')
check(review.get('catalog_equivalence_file_sha256') == raw_sha(equivalence_path), 'REVIEWED_EQUIVALENCE_SHA')
check(raw_sha(failed_catalog_receipt) == '9e14314393045ffabf651b5019ff1a16a8b41d4c8d405909ce7a06a0f27d7610', 'FIRST_CATALOG_FAILURE_PRESERVED')

product = json.loads(product_path.read_text(encoding='utf-8'))
product_receipt = json.loads(product_receipt_path.read_text(encoding='utf-8'))
equivalence = json.loads(equivalence_path.read_text(encoding='utf-8'))
check(product.get('sha256') == product_sha == product_receipt.get('analysis_product_sha256'), 'PRODUCT_IDENTITY')
check(raw_sha(product_path) == product_receipt.get('analysis_product_file_sha256'), 'PRODUCT_FILE_SHA')
check(product_receipt.get('catalog_run_id') == catalog_run and product_receipt.get('catalog_sha256') == catalog_sha, 'PRODUCT_CATALOG_BINDING')
check(equivalence.get('status') == 'PASS_CONTENT_EQUIVALENT_OWNER_RUN_REBIND', 'CATALOG_EQUIVALENCE_STATUS')
check(equivalence.get('active_owner_catalog', {}).get('run_id') == catalog_run and equivalence.get('active_owner_catalog', {}).get('product_sha256') == catalog_sha, 'CATALOG_EQUIVALENCE_ACTIVE_IDENTITY')
check(raw_sha(equivalence_path) == product_receipt.get('catalog_equivalence_reconciliation', {}).get('file_sha256'), 'CATALOG_EQUIVALENCE_FILE_SHA')

# Resolve the current LaunchAgent owner dynamically, but require the exact
# reviewer-approved R2 app root; never reuse a saved PID or load another app.
owner = ops.launchd_owner_identity(expected_root=approved_root)
release_root = Path(owner['active_root']).resolve()
check(release_root == approved_root, 'ACTIVE_RELEASE_APPROVED_R2_APP_ROOT')
program_env = owner['program_environment']
manifest_path = Path(program_env['V35_RELEASE_MANIFEST_PATH']).resolve()
manifest_sha = program_env['V35_RELEASE_MANIFEST_SHA256']
approved_manifest_path = approved_root.parent / 'release-manifest.json'
check(manifest_path == approved_manifest_path.resolve(), 'ACTIVE_RELEASE_MANIFEST_PATH')
check(manifest_sha == approved_manifest_sha, 'ACTIVE_RELEASE_APPROVED_MANIFEST_SHA')
check(manifest_path.is_file() and raw_sha(manifest_path) == manifest_sha, 'ACTIVE_RELEASE_MANIFEST')
app_path = release_root / 'apps/api/v35_api/app.py'
check(app_path.is_file() and raw_sha(app_path) == approved_app_sha, 'ACTIVE_RELEASE_APPROVED_APP_PY_SHA')
candidate = ops.candidate_source_check()
check(ops.release_source_hashes(release_root) == candidate['source_sha256'], 'ACTIVE_RELEASE_ACCEPTED_SOURCE_HASHES')
legacy = ops.legacy_readback()  # GET + exact 2026-09-30/2026-09-29 owner-file check
check(legacy.get('selected_stock_count') == 23 and legacy.get('stock_count') == 140, 'LEGACY_OWNER_UNCHANGED')

service_cls, store_cls, material_cls = ops.load_runtime(release_root)
service = service_cls(store_cls(state), None, None, material_store=material_cls(state / 'materials'))
catalog_read = service.get_announcement_date_catalog(target, publication)
catalog = catalog_read.get('catalog') or {}
check(catalog_read.get('status') == 'COMPLETE' and catalog_read.get('readback_status') == 'VERIFIED', 'OWNER_CATALOG_READBACK')
check(catalog.get('target_trade_date') == target and catalog.get('publication_date') == publication, 'OWNER_CATALOG_DATES')
check(catalog.get('run_id') == catalog_run and catalog.get('sha256') == catalog_sha, 'OWNER_CATALOG_RUN_AND_SHA')
check(catalog.get('manager_consumer_row_count') == 580 and catalog.get('manager_source_identity_count') == 584, 'OWNER_CATALOG_ROWS_AND_ASSOCIATIONS')
check(len(catalog.get('manager_source_codes', [])) == 524 and catalog.get('manager_issuer_count') is None, 'OWNER_CATALOG_SOURCE_CODES_AND_UNKNOWN_ISSUERS')
check(catalog.get('connect_eligibility_status') == 'NOT_ASSESSED', 'CONNECT_REMAINS_UNASSESSED')

# Confirm API and service agree before writing, and that only analysis is absent.
query_catalog = urllib.parse.urlencode({'date': target, 'source_scope': 'EASTMONEY_HK_DATE_CATALOG', 'publication_date': publication})
status, raw, api_body = ops.api_get('?' + query_catalog)
api_catalog = api_body.get('catalog') or {}
check(status == 200 and api_body.get('readback_status') == 'VERIFIED', 'API_CATALOG_READBACK')
check(api_catalog.get('run_id') == catalog_run and api_catalog.get('sha256') == catalog_sha, 'API_CATALOG_RUN_AND_SHA')
check(api_catalog.get('manager_consumer_row_count') == 580 and api_catalog.get('manager_source_identity_count') == 584 and len(api_catalog.get('manager_source_codes', [])) == 524, 'API_CATALOG_COUNTS')

analysis_path = state / 'workspace_announcements/20261007/eastmoney_date_catalog/20261006/analysis.v1.json'
check(not analysis_path.exists(), 'TARGET_ANALYSIS_FILE_ABSENT')
before_owner = service.get_announcement_analysis(target, publication)
before_analysis = before_owner.get('analysis') or {}
before_source = before_owner.get('source_catalog') or {}
before_selection = before_analysis.get('stock_selection') or {}
check(before_analysis.get('status') == 'NOT_IMPORTED', 'TARGET_ANALYSIS_ABSENT')
check(before_source.get('catalog_run_id') == catalog_run and before_source.get('catalog_product_sha256') == catalog_sha, 'TARGET_SOURCE_OWNER_BINDING')
check(before_selection.get('status') == 'NOT_ASSESSED' and before_selection.get('stock_count') is None, 'TARGET_SELECTION_ABSENT')
query_analysis = urllib.parse.urlencode({'date': target, 'publication_date': publication})
api_status, api_raw, before_api = ops.api_get('/analysis?' + query_analysis)
before_api_analysis = before_api.get('analysis') or {}
before_api_source = before_api.get('source_catalog') or {}
before_api_selection = before_api_analysis.get('stock_selection') or {}
check(api_status == 200 and before_api.get('target_trade_date') == target and before_api.get('publication_date') == publication, 'PREIMPORT_API_DATE_BINDING')
check(before_api_analysis.get('status') == 'NOT_IMPORTED', 'PREIMPORT_API_ANALYSIS_ABSENT')
check(before_api_source.get('catalog_run_id') == catalog_run and before_api_source.get('catalog_product_sha256') == catalog_sha, 'PREIMPORT_API_SOURCE_BINDING')
check(before_api_selection.get('status') == 'NOT_ASSESSED' and before_api_selection.get('stock_count') is None, 'PREIMPORT_API_SELECTION_ABSENT')

attempt = {
    'schema': 'v4.manager_research.announcement_analysis_import_attempt.v1',
    'status': 'ATTEMPT_STARTED', 'started_at_utc': datetime.now(timezone.utc).isoformat(),
    'target_trade_date': target, 'publication_date': publication,
    'active_pid_observed': owner['pid'], 'active_root': str(release_root),
    'active_plist_sha256': owner['plist_sha256'],
    'active_manifest_path': str(manifest_path), 'active_manifest_sha256': manifest_sha,
    'active_app_py_sha256': raw_sha(app_path),
    'catalog_run_id': catalog_run, 'catalog_sha256': catalog_sha,
    'product_sha256': product_sha, 'product_file_sha256': raw_sha(product_path),
    'preimport_api_catalog_raw_sha256': hashlib.sha256(raw).hexdigest(),
    'preimport_api_analysis_raw_sha256': hashlib.sha256(api_raw).hexdigest(),
    'legacy_readback': legacy, 'first_catalog_import_receipt_file_sha256': raw_sha(failed_catalog_receipt),
    'one_attempt_only': True,
}
ops.atomic_json(attempt_path, attempt)
try:
    # The existing public method performs the owner write; do not edit the JSON path directly.
    imported = service.import_announcement_analysis(product)
    owner_after = service.get_announcement_analysis(target, publication)
    analysis = owner_after.get('analysis') or {}
    selection = analysis.get('stock_selection') or {}
    summary = analysis.get('summary') or {}
    owner_postimport_readback = {
        'target_trade_date': owner_after.get('target_trade_date'),
        'publication_date': owner_after.get('publication_date'),
        'point_in_time_status': analysis.get('point_in_time_status'),
    }
    expected_counts = {
        'stock_count': 524, 'article_count': 580, 'selected_stock_count': 7,
        'conditional_watch_count': 8, 'not_selected_stock_count': 429,
        'not_assessed_stock_count': 80,
    }
    check(imported.get('analysis', {}).get('status') == 'VERIFIED', 'OWNER_IMPORT_RESULT')
    check(owner_postimport_readback.get('target_trade_date') == target, 'POSTIMPORT_OWNER_TARGET_TRADE_DATE')
    check(owner_postimport_readback.get('publication_date') == publication, 'POSTIMPORT_OWNER_PUBLICATION_DATE')
    check(owner_postimport_readback.get('point_in_time_status') == 'CANNOT_CONFIRM', 'POSTIMPORT_OWNER_PIT_STATUS')
    check(analysis.get('status') == 'VERIFIED' and analysis.get('product_sha256') == product_sha, 'OWNER_ANALYSIS_PRODUCT_READBACK')
    check(analysis.get('source_manifest', {}).get('catalog_run_id') == catalog_run and analysis.get('source_manifest', {}).get('catalog_product_sha256') == catalog_sha, 'OWNER_ANALYSIS_SOURCE_READBACK')
    check(summary.get('manager_announcements') == 580 and summary.get('manager_source_identity_associations') == 584 and summary.get('distinct_manager_source_codes') == 524, 'OWNER_ANALYSIS_SUMMARY_COUNTS')
    check(all(selection.get(key) == value for key, value in expected_counts.items()), 'OWNER_SELECTION_COUNTS')

    after_status, after_raw, after_api = ops.api_get('/analysis?' + query_analysis)
    after_analysis = after_api.get('analysis') or {}
    after_selection = after_analysis.get('stock_selection') or {}
    after_source = after_api.get('source_catalog') or {}
    api_postimport_readback = {
        'target_trade_date': after_api.get('target_trade_date'),
        'publication_date': after_api.get('publication_date'),
        'point_in_time_status': after_analysis.get('point_in_time_status'),
    }
    check(after_status == 200 and after_api.get('target_trade_date') == target and after_api.get('publication_date') == publication, 'POSTIMPORT_API_DATE_BINDING')
    check(api_postimport_readback.get('point_in_time_status') == 'CANNOT_CONFIRM', 'POSTIMPORT_API_PIT_STATUS')
    check(after_analysis.get('status') == 'VERIFIED' and after_analysis.get('product_sha256') == product_sha, 'POSTIMPORT_API_PRODUCT_SHA')
    check(after_source.get('catalog_run_id') == catalog_run and after_source.get('catalog_product_sha256') == catalog_sha, 'POSTIMPORT_API_CATALOG_BINDING')
    check(all(after_selection.get(key) == value for key, value in expected_counts.items()), 'POSTIMPORT_API_SELECTION_COUNTS')
    check(after_api.get('RESEARCH_ONLY') is True and after_api.get('production_allowed') is False and after_api.get('buy_gate_updated') is False and after_api.get('orders_sent') is False, 'POSTIMPORT_API_SAFETY_FLAGS')
    legacy_after = ops.legacy_readback()
    legacy_stable_keys = ('analysis_status', 'source_status', 'manager_announcement_count',
        'manager_issuer_count', 'stock_count', 'selected_stock_count',
        'legacy_owner_sha256', 'safety')
    check(all(legacy_after.get(key) == legacy.get(key) for key in legacy_stable_keys), 'LEGACY_OWNER_STILL_UNCHANGED')
    terminal = {
        'schema': 'v4.manager_research.announcement_analysis_import_receipt.v1',
        'status': 'PASS_OWNER_METHOD_AND_API_READBACK', 'completed_at_utc': datetime.now(timezone.utc).isoformat(),
        'attempt_file_sha256': raw_sha(attempt_path), 'target_trade_date': target,
        'publication_date': publication, 'active_pid_observed': owner['pid'],
        'active_root': str(release_root), 'active_plist_sha256': owner['plist_sha256'],
        'active_manifest_path': str(manifest_path), 'active_manifest_sha256': manifest_sha,
        'active_app_py_sha256': raw_sha(app_path), 'catalog_run_id': catalog_run,
        'catalog_sha256': catalog_sha, 'product_sha256': product_sha,
        'analysis_owner_file_sha256': raw_sha(analysis_path),
        'owner_readback_status': analysis.get('status'), 'api_http_status': after_status,
        'api_raw_sha256': hashlib.sha256(after_raw).hexdigest(),
        'postimport_owner_readback': owner_postimport_readback,
        'postimport_api_readback': api_postimport_readback,
        'point_in_time_status': 'CANNOT_CONFIRM',
        'selection_counts': {key: selection.get(key) for key in expected_counts},
        'legacy_readback_before': legacy, 'legacy_readback_after': legacy_after,
        'legacy_owner_unchanged': True, 'first_catalog_import_failure_preserved': True,
        'trade_or_buy_use': False, 'live_state_written': True,
    }
except Exception as exc:
    terminal = {
        'schema': 'v4.manager_research.announcement_analysis_import_receipt.v1',
        'status': 'IMPORT_INDETERMINATE_NO_RETRY', 'completed_at_utc': datetime.now(timezone.utc).isoformat(),
        'attempt_file_sha256': raw_sha(attempt_path), 'target_trade_date': target,
        'publication_date': publication, 'catalog_run_id': catalog_run,
        'catalog_sha256': catalog_sha, 'product_sha256': product_sha,
        'active_root': str(release_root), 'active_manifest_path': str(manifest_path),
        'active_manifest_sha256': manifest_sha, 'active_app_py_sha256': raw_sha(app_path),
        'postimport_owner_readback': locals().get('owner_postimport_readback'),
        'postimport_api_readback': locals().get('api_postimport_readback'),
        'error': type(exc).__name__ + ':' + str(exc),
        'automatic_retry_or_rollback': False,
    }
finally:
    if 'terminal' in locals():
        ops.atomic_json(terminal_path, terminal)
if terminal.get('status') != 'PASS_OWNER_METHOD_AND_API_READBACK':
    raise RuntimeError(terminal.get('error', 'ANALYSIS_IMPORT_NOT_VERIFIED'))
print(json.dumps({'status': terminal['status'], 'receipt': str(terminal_path),
                  'product_sha256': product_sha, 'catalog_run_id': catalog_run,
                  'postimport_owner_readback': terminal.get('postimport_owner_readback'),
                  'postimport_api_readback': terminal.get('postimport_api_readback'),
                  'selection_counts': terminal['selection_counts']}, ensure_ascii=False, indent=2))
PY
```

The `IMPORT_INDETERMINATE_NO_RETRY` terminal status is final for that attempt. Diagnose through read-only owner/API evidence and a new controller decision; do not remove receipts, invoke the catalog import again, or retry blindly. UI and natural-slot verification remain separate controller-owned checks.
