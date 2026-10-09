from __future__ import annotations
import hashlib, json, sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

E = Path('/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_REAL_RESULT_RECOVERY_20261009')
SOURCE = E / 'candidate/original_r3_business_source'
DATA = E / 'outputs/us_mapping_recovery/input_data'
summary_paths = sorted((E / 'outputs/us_mapping_recovery/runs').glob('*/actual_owner_result_summary.json'))
if not summary_paths:
    raise SystemExit('US_MAPPING_ACTUAL_OWNER_RESULT_MISSING')
previous = json.loads(summary_paths[-1].read_text())
RUN_ROOT = Path(previous['run_root'])
MANAGER_ROOT = RUN_ROOT / 'manager_state'
SCREEN_ROOT = Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data')
sys.path.insert(0, str(SOURCE))
from v4.manager_research.store import ManagerResearchStore
from v4.manager_research.service import ManagerResearchJobService
from v4.manager_research.us_market_bridge import ResearchPeripheralUsMarketReader
from v4.manager_research.workspace_projection import HK

started = datetime.now(HK)
owner = ManagerResearchJobService(
    ManagerResearchStore(MANAGER_ROOT), None, None,
    catalyst_data_root=DATA,
    workspace_security_master_root=SCREEN_ROOT,
    workspace_screen_authority_root=SCREEN_ROOT,
    workspace_us_market_reader=ResearchPeripheralUsMarketReader(DATA),
)
result = None
error = None
try:
    result = owner.refresh_workspace_plan(
        '20261009', execution_kind='MANUAL_REFRESH', now=started,
        execution_context={'trigger_kind': 'MANUAL', 'timing': 'LATE_CATCHUP'},
        workspace_date_bindings={'selection_date': '20261009', 'announcement_date': '20261008'},
    )
except Exception as exc:
    error = {'type': type(exc).__name__, 'code': str(exc) if str(exc).isupper() and len(str(exc)) < 180 else None}
finally:
    owner.close()
product = (result or {}).get('plan_product') or {}
product_path = MANAGER_ROOT / 'workspace_plans' / '20261009' / f"{product.get('run_id')}.json" if product.get('run_id') else None
product_file_sha = hashlib.sha256(product_path.read_bytes()).hexdigest() if product_path and product_path.is_file() else None
summary = {
    'actual_invoked_method': 'ManagerResearchJobService.refresh_workspace_plan',
    'target_trade_date': '20261009',
    'date_bindings': {'selection_date': '20261009', 'announcement_date': '20261008'},
    'actual_started_at': started.isoformat(timespec='microseconds'),
    'actual_finished_at': datetime.now(HK).isoformat(timespec='microseconds'),
    'status': 'PRODUCED' if isinstance(result, dict) else 'FAILED',
    'error': error,
    'plan_product': product,
    'plan_product_path': str(product_path) if product_path and product_path.exists() else None,
    'plan_product_file_sha256': product_file_sha,
    'workspace_plan_attempt': (result or {}).get('workspace_plan_attempt'),
    'workspace_gaps': (result or {}).get('gaps'),
    'stock_count': len((result or {}).get('stocks') or []),
    'announcement_review_status': ((result or {}).get('announcement_review') or {}).get('status'),
    'announcement_review_gaps': ((result or {}).get('announcement_review') or {}).get('gaps'),
    'market_screen_evidence': (result or {}).get('market_screen_evidence'),
    'us_market_attention': {
        key: ((result or {}).get('us_market_attention') or {}).get(key)
        for key in ('status', 'expected_us_session', 'coverage', 'source_identity', 'gaps')
    },
    'us_mapping_research': {
        'daily_run': {
            key: (((result or {}).get('us_mapping_research') or {}).get('daily_run') or {}).get(key)
            for key in ('status', 'run_id', 'generated_at', 'artifact_sha256', 'coverage', 'gaps')
        },
    },
    'us_mapping_plan_reference': (result or {}).get('owner_chain', {}).get('us_mapping_daily_plan_reference'),
    'safety': {key: (result or {}).get(key) for key in ('RESEARCH_ONLY', 'production_allowed', 'buy_gate_updated', 'orders_sent')},
    'source_screen_root_read_only': str(SCREEN_ROOT),
    'input_data_root_isolated': str(DATA),
    'manager_store_root_isolated': str(MANAGER_ROOT),
    'source_baseline': str(SOURCE),
    'mapping_run_id': previous.get('run_id'),
    'mapping_artifact_sha256': previous.get('artifact_sha256'),
}
summary['summary_sha256'] = hashlib.sha256(json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
outdir = RUN_ROOT / 'plan_runs'
outdir.mkdir(parents=True, exist_ok=True)
out = outdir / f"{started.strftime('%Y%m%dT%H%M%S%z')}_summary.json"
out.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + '\n')
print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
if error:
    raise SystemExit(1)
