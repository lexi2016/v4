"""Existing owner consumption; blocked business inputs are never success."""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import hashlib
from v5_shadow.contracts import aware
from v5_shadow.digests import sha256_json
from v5_shadow.run_ledger import claim_run, finish_run


def blocked(reference, reasons, *, readback=False):
    return dict(status='BLOCKED', product_reference=reference,
                readback_verified=readback, retry_safe_without_external_effect=False,
                reason_codes=reasons)


def read_announcement_owner(request, ledger_run_id):
    if 'revision_create' in request:
        from v5_shadow.daily_announcement_revision import run_revision
        return run_revision(request,ledger_run_id)
    from v5_shadow.announcement_offline_reader import read_owner
    first=read_owner(request['binding'],request['cutoff'])
    second=read_owner(request['binding'],request['cutoff'])
    if first!=second:raise ValueError('DAILY_ANNOUNCEMENT_READBACK_CHANGED')
    # Legacy consumption is not the separately reviewed decision revision.
    return blocked(dict(ledger_run_id=ledger_run_id,binding=request['binding'],
        readback_sha256=sha256_json(first),consumption=first['consumption'],
        natural_verified=False),['ANNOUNCEMENT_DECISION_REVIEWER_ADAPTER_NOT_BOUND'],readback=True)


def rebound_receipt(request, ledger_run_id, result, artifact):
    if (artifact['request']!=request['request']
            or artifact['run_id']!=result['reference']['run_id']
            or artifact['computation_status']!=result['computation_status']):
        raise ValueError('DAILY_REBOUND_INDEPENDENT_READBACK')
    # 2d8e38ec produces numeric observations, explicitly not admitted selection.
    return blocked(dict(ledger_run_id=ledger_run_id,root=request['output_root'],
        reference=result['reference'],computation_status=result['computation_status'],
        selection_status=result['selection_status'],reused=result['reused'],
        natural_verified=False),list(result['reason_codes'])+['REBOUND_SELECTION_CANNOT_CONFIRM'],readback=True)


def run_manager_daily(request, ledger_root, binding_identity):
    """Save via original workspace and its independent same-attempt reader.

    Caller must supply the exact post-owner request, including actual cutoff and
    input/reference hashes. This never generates an earlier cutoff or publishes.
    """
    from v5_shadow.manager_plan import run_manager_plan
    now=datetime.now(timezone.utc)
    today=now.astimezone(timezone(timedelta(hours=8))).strftime('%Y%m%d')
    if request['target_date']!=today or request['action']!='refresh' or aware(request['now'])>now:
        raise ValueError('DAILY_MANAGER_CURRENT_REFRESH_REQUIRED')
    from v5_shadow.daily_close_plan import _sources,_market_states
    if _market_states(_sources(),today)['hk_securities'] not in {'FULL_TRADING_DAY','HALF_TRADING_DAY_AM'}:
        raise ValueError('DAILY_MANAGER_CALENDAR_NOT_OPEN')
    identity=dict(binding_identity,lane='manager_plan',target_date=today,
        input_sha256=sha256_json(request),research_cutoff=request['now'])
    claim=claim_run(ledger_root,identity,max_attempts=1)
    if claim['status']!='CLAIMED':return claim
    # Errors retain RUNNING: a plan may already have been saved before failure.
    result=run_manager_plan(request)
    readback=result['readback'];product=result['payload']['plan_product']
    if (readback['status']!='MATCHED' or readback['run_id']!=product['run_id']
            or readback['plan_sha256']!=product['sha256']
            or readback['attempt']['run_id']!=product['run_id']):
        raise ValueError('DAILY_MANAGER_SAME_ATTEMPT_READBACK')
    page=run_manager_plan(dict(request,action='read',view='auto'))
    page_product=page['payload']['plan_product']
    if page_product.get('run_id')!=product['run_id'] or page_product.get('sha256')!=product['sha256']:
        raise ValueError('DAILY_MANAGER_PAGE_PRODUCT_MISMATCH')
    reference=dict(root=request['manager_output_root'],readback=readback,
        page_payload_sha256=sha256_json(page['payload']),page_readback='ORIGINAL_AUTO_WORKSPACE_READ_MATCHED_NOT_HTTP_DEPLOYMENT',
        plan_status=product.get('status'),natural_verified=False)
    # Saving a partial plan is useful but not three-lane business success.
    receipt=blocked(reference,['THREE_LANE_BUSINESS_ACCEPTANCE_NOT_VERIFIED'],readback=True)
    return dict(state=finish_run(ledger_root,claim,receipt),result=result)


def adapter_identity(config, dependencies):
    files=('daily_owner_adapters.py','daily_rebound_owner.py','daily_announcement_revision.py','daily_manager_assembly.py','daily_tick.py','daily_dispatch.py','run_ledger.py',
           'announcement_offline_reader.py','daily_close_plan.py','module_api.py','module_artifacts.py')
    return dict(code_sha256=sha256_json({name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in files}),
        config_sha256=sha256_json(config),dependency_sha256=sha256_json(dependencies))
