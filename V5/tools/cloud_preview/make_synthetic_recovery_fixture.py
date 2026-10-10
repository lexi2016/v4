"""Produce only a synthetic empty-owner response for frontend contract tests."""
import argparse,json,sys
from datetime import datetime,timezone
from pathlib import Path
base=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(base/'src'),str(base/'tests')]
from test_manager_current_recovery import ManagerCurrentRecoveryTests
from v5_shadow.manager_plan import run_manager_plan
parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
if args.out.exists():raise ValueError('NEW_SYNTHETIC_TEST_OUTPUT_REQUIRED')
case=ManagerCurrentRecoveryTests();case.setUp()
try:
 saved=run_manager_plan(case.request)
 page=run_manager_plan(dict(case.request,action='read',now=datetime.now(timezone.utc).isoformat()))
 args.out.write_text(json.dumps(dict(kind='SYNTHETIC_EMPTY_OWNER_NOT_BUSINESS_EVIDENCE',expected_run=saved['readback']['run_id'],expected_sha=saved['readback']['plan_sha256'],result=page)))
finally:case.doCleanups()
