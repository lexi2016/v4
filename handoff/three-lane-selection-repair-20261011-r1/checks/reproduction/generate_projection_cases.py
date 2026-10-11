"""Reviewer-only synthetic read boundaries through the real Python projector.

No service import, refresh, persistence owner, market fetch, or API request runs.
The output is a test input for the unchanged TypeScript DTO/DOM renderer.
"""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import sys

ROOT = Path('/workspace/scratch/ff44f882fe5c')
sys.path[:0] = [str(ROOT / p) for p in (
    'candidate', 'candidate/tests', 'support_source', 'support_source/upstreams')]

from test_manager_three_lane_channels_r1 import three_lane_workspace
from v4.manager_research.workspace_daily_channels import build_daily_channels

OUT = Path(__file__).resolve().parent
value = three_lane_workspace()
reference = value['announcement_reviewed_analysis']['research_references'][0]
product = value['announcement_reviewed_analysis']['products'][0]
# Legal original consumption readback includes this binding. Earlier synthetic
# backend fixtures omitted it; do not weaken the unchanged frontend validator.
original_projection = build_daily_channels(value)
fixture_manifest_was_missing = product.get('source_manifest_sha256') is None
if fixture_manifest_was_missing:
    product['source_manifest_sha256'] = reference['source_manifest_sha256']
assert product['source_manifest_sha256'] == reference['source_manifest_sha256']

baseline_input = deepcopy(value)
baseline = build_daily_channels(value)
assert value == baseline_input, 'Projector must not mutate the supplied read boundary'
by_name = {row['channel']: row for row in baseline['channels']}
assert [by_name[name]['candidate_count'] for name in ('ANNOUNCEMENT', 'HK_CONNECT', 'OVERSOLD')] == [1, 2, 1]
assert [row['symbol'] for row in by_name['HK_CONNECT']['rows']] == ['HK.00002', 'HK.00001']
assert [row['rank'] for row in by_name['HK_CONNECT']['rows']] == [2, 1]
assert [row['order'] for row in by_name['HK_CONNECT']['rows']] == [1, 2]

cases = [dict(id='all_read_boundaries', missing=None, workspace=deepcopy(value), daily=baseline)]
for missing, field in (
    ('ANNOUNCEMENT', 'announcement_reviewed_analysis'),
    ('HK_CONNECT', 'stage_selection'),
    ('OVERSOLD', 'research_attention'),
):
    item = deepcopy(value)
    item.pop(field)
    before = deepcopy(item)
    daily = build_daily_channels(item)
    assert item == before
    current = {row['channel']: row for row in daily['channels']}
    assert current[missing]['status'] == 'CANNOT_CONFIRM'
    assert current[missing]['candidate_count'] is None
    assert current[missing]['pending_count'] is None
    assert current[missing]['rows'] == []
    for name in set(by_name) - {missing}:
        assert current[name] == by_name[name], f'{missing} erased or changed {name}'
    cases.append(dict(id='missing_' + missing, missing=missing, workspace=item, daily=daily))

sources = [
    'candidate/v4/manager_research/workspace_daily_channels.py',
    'candidate/v4/manager_research/research_attention.py',
    'candidate/tests/test_manager_three_lane_channels_r1.py',
    'candidate/tests/test_manager_research_selection_ledger.py',
    'candidate/apps/web/src/manager-selection/dailyChannels.ts',
]
envelope = dict(
    scope='SYNTHETIC_PYTHON_TO_TYPESCRIPT_READ_BOUNDARY_ONLY',
    real_owner_executed=False, real_api_called=False, natural_run_accepted=False,
    fixture_manifest_was_missing=fixture_manifest_was_missing,
    fixture_only_adjustment=('Matched product source_manifest_sha256 to its reference; no code changes'
                            if fixture_manifest_was_missing else 'None'),
    original_fixture_projection=original_projection if fixture_manifest_was_missing else None,
    source_sha256={path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in sources},
    cases=cases,
)
(OUT / 'projection_cases.json').write_text(json.dumps(envelope, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(dict(scope=envelope['scope'], source_sha256=envelope['source_sha256'],
    fixture_manifest_was_missing=fixture_manifest_was_missing,
    cases=[dict(id=c['id'], counts={r['channel']:r['candidate_count'] for r in c['daily']['channels']},
                statuses={r['channel']:r['status'] for r in c['daily']['channels']}) for c in cases]),
    ensure_ascii=False))
