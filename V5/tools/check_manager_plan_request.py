"""Mac-only explicit candidate verification; never run by the ordinary API GET."""
import copy
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from v5_shadow.manager_plan import run_manager_plan
from v5_shadow.digests import canonical_bytes


def main(path):
    request=json.loads(Path(path).read_text())
    if request['action']!='refresh':
        raise ValueError('EXPLICIT_REFRESH_REQUEST_REQUIRED')
    refreshed=run_manager_plan(request)
    read_request=copy.deepcopy(request);read_request['action']='read'
    read=run_manager_plan(read_request)
    first=refreshed['payload'];second=read['payload']
    if (second['plan_product']['consumed'] is not True
            or second['plan_product']['run_id']!=refreshed['readback']['run_id']):
        raise ValueError('MANAGER_REGULAR_READ_NOT_SAME_SAVED_PLAN')
    reference=second['owner_chain']['us_mapping_daily_plan_reference']
    daily=second['us_mapping_research']['daily_run']
    if reference['status']!='CONSUMED' or daily['target_trade_date']!=request['target_date']:
        raise ValueError('MANAGER_EXPECTED_CURRENT_DAILY_NOT_CONSUMED:'+str(reference))
    if daily['status']=='VALID_EMPTY' and daily['matches']!=[]:
        raise ValueError('VALID_EMPTY_CANNOT_REUSE_PRIOR_MATCHES')
    print(canonical_bytes(dict(status='MATCHED', target_date=request['target_date'],
        plan_run_id=refreshed['readback']['run_id'],plan_sha256=refreshed['readback']['plan_sha256'],
        daily_run_id=daily['run_id'],daily_status=daily['status'],match_count=len(daily['matches']),
        target_date_eligibility=daily.get('target_date_eligibility'),reference=reference,
        natural_verified=False, readback=refreshed['readback'])).decode())


if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('Usage: check_manager_plan_request.py request.json')
    main(sys.argv[1])
