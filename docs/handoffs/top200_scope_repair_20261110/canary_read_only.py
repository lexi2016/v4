"""11/9 frozen acceptance oracle; GET and file reads only, no producer replay."""
import argparse
import json
from pathlib import Path
import urllib.request

from ops.build_a_share_pool_top200 import read_daily_projection, sha, STAGES

parser = argparse.ArgumentParser()
parser.add_argument('--product-root', type=Path, required=True)
parser.add_argument('--stage-root', type=Path, required=True)
parser.add_argument('--legacy', type=Path, required=True)
parser.add_argument('--out', type=Path, required=True)
args = parser.parse_args()
paths = [args.stage_root/'selection_latest.json', args.product_root/'index.json']
paths += [args.stage_root.parent/'receipts/20261109'/stage/'receipt.json' for stage in STAGES]
before = {str(path): sha(path) for path in paths}

def page(date, limit, offset=0):
    url = f'http://127.0.0.1:8873/api/v4/preselection-pools?date={date}&limit={limit}&offset={offset}'
    with urllib.request.urlopen(url, timeout=120) as response:
        return json.load(response)

result = read_daily_projection('20261109', page, args.product_root, args.stage_root, args.legacy)
row = next(e for e in result['dates'] if e['date'] == '20261109')
assert (row['a_pool']['selected_count'], row['a_pool']['hit_count'], row['a_pool']['materialized_pool_count']) == (487,36,2)
assert (row['seven_stage']['selected_count'], row['seven_stage']['hit_count'], row['stage_coverage']['available']) == (10,2,1)
assert [(r['selected_count'],r['hit_count']) for r in row['formula_comparison']['rows']] == [(387,10),(47,1),(287,6),(111,3),(47,3),(19,2)]
assert row['formula_comparison']['historical_PIT'] is False
assert all(row['seven_stage']['stages'][k]['execution_status'] == 'EXECUTION_FAILED' and row['seven_stage']['stages'][k]['hit_count'] is None for k in STAGES[1:])
assert all(any('HOURLY_COMPLETION_WITNESS_MISSING' in e for e in row['seven_stage']['stages'][k]['errors']) for k in STAGES[1:])
assert before == {str(path): sha(path) for path in paths}
summary = dict(status='PASS_READ_ONLY_DATED_CANARY', date='20261109',
    pool={k:row['a_pool'][k] for k in ['selected_count','hit_count','materialized_pool_count','pool_count']},
    stage={k:row['seven_stage'][k] for k in ['selected_count','hit_count']}, stage_coverage=row['stage_coverage'],
    stages={k:{f:v.get(f) for f in ['status','execution_status','row_count','hit_count','errors','receipt_source']} for k,v in row['seven_stage']['stages'].items()},
    formula_comparison=row['formula_comparison'], source_hashes_unchanged=before)
args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n')
print(summary['status'])
