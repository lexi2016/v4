"""Controller integration recipe; preserve the reviewed API gate context."""
from pathlib import Path
import argparse
import json
import sys

CASE=Path(__file__).resolve().parent
R4=CASE.parent/'R4'
sys.path.insert(0,str(R4))
from integrate_batch1 import reviewed_inputs,owned_lock
from activate_one_shots import activate


def invoke_full_plan(plan,api_receipt,**fixture_overrides):
    # Do not filter plan.operations: observe_current needs the API proposal as
    # well as the graph operation. The frozen activate() function itself
    # strictly selects only com.lexi.v35.runtime-graph for service mutations.
    if len([op for op in plan['operations'] if op['role']=='api'])!=1:
        raise ValueError('COMPLETE_API_GATE_CONTEXT_REQUIRED')
    return activate(plan,rollback=False,wait_seconds=45,api_receipt=api_receipt,**fixture_overrides)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review-receipt',type=Path,required=True)
    parser.add_argument('--api-ready-receipt',type=Path,required=True)
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    if not args.execute:raise ValueError('EXPLICIT_EXECUTE_REQUIRED')
    plan=reviewed_inputs(json.loads(args.review_receipt.read_text()))
    api=json.loads(args.api_ready_receipt.read_text())
    with owned_lock():result=invoke_full_plan(plan,api,journal_root=CASE)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
