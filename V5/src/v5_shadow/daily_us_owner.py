"""Daily ledger adapter for the existing isolated original US mapping owner.

This invokes the existing MANUAL_RECOVERY contract; it does not certify a
natural run, publish a manager plan, or broaden the four-relation registry.
"""
from v5_shadow.contracts import sha
from v5_shadow.digests import sha256_json
from v5_shadow.us_mapping_daily import run_us_mapping, _identity, PIN
from v5_shadow.daily_close_plan import PINS
from pathlib import Path
import hashlib


def bind_us_owner(config):
    """Rebuild at each dispatch so changed implementation cannot reuse success."""
    identity = _identity()
    for name in ('daily_us_owner.py', 'daily_dispatch.py', 'run_ledger.py', 'daily_close_plan.py', 'module_artifacts.py'):
        identity[name] = hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
    return dict(invoke=run_us_owner, code_sha256=sha256_json(identity),
                config_sha256=sha256_json(config),
                dependency_sha256=sha256_json(dict(us_owner=PIN, calendar=PINS)))


def run_us_owner(request, ledger_run_id):
    result = run_us_mapping(request)
    daily = result['persisted_daily']
    if (result.get('readback_status') != 'MATCHED'
            or daily != result['payload']['daily_run']
            or daily.get('target_trade_date') != request['target_date']):
        raise ValueError('DAILY_US_OWNER_READBACK')
    unsigned = dict(daily)
    artifact_sha = unsigned.pop('artifact_sha256')
    sha(artifact_sha)
    if sha256_json(unsigned) != artifact_sha:
        raise ValueError('DAILY_US_OWNER_ARTIFACT_SHA')
    succeeded = daily.get('status') in {'COMPLETED', 'VALID_EMPTY'}
    return dict(status='SUCCEEDED' if succeeded else 'FAILED',
                product_reference=dict(owner='us_mapping_daily', ledger_run_id=ledger_run_id,
                    manager_output_root=request['manager_output_root'],
                    target_date=request['target_date'], run_id=daily['run_id'],
                    artifact_sha256=artifact_sha, us_session_date=daily.get('us_session_date'),
                    owner_status=daily['status'], execution_kind=result['execution_kind'],
                    natural_verified=False, full_market_coverage=False,
                    target_date_eligibility=daily.get('target_date_eligibility')),
                readback_verified=True, retry_safe_without_external_effect=False,
                reason_codes=[] if succeeded else ['US_OWNER_' + str(daily.get('status'))])
