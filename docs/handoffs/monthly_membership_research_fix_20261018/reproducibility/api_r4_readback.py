"""Read the existing authorized run after a display-only deployment; never POST."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import urllib.request

H = Path.cwd() / 'docs/handoffs/monthly_membership_research_fix_20261018'
O = H / 'local_only/actual_r4'
O.mkdir(exist_ok=True)
run = json.loads((H / 'ROOT_RUN_SUBMISSION_R2.json').read_text())['run_id']
path = '/api/v4/manager-workbench/days/20261020/recommendations/US_MAPPING'
url = 'http://127.0.0.1:8873' + path + '?run_id=' + run + '&limit=50'
with urllib.request.urlopen(url, timeout=60) as response:
    raw = response.read()
    status = response.status
(O / 'lane-response.json').write_bytes(raw)
data = json.loads(raw)
lane = data['data']
prior = json.loads((H / 'local_only/actual_r2/lane-response.json').read_text())
for key, value in dict(RESEARCH_ONLY=True, production_allowed=False,
                       buy_gate_updated=False, orders_sent=False).items():
    assert data[key] == value, key
assert lane['snapshot']['run_id'] == run
assert lane['snapshot']['product_sha256'] == prior['data']['snapshot']['product_sha256']
assert lane['snapshot']['input_sha256'] == prior['data']['snapshot']['input_sha256']
assert lane['us_mapping_summary']['directional_proxy_lists'] == prior['data']['us_mapping_summary']['directional_proxy_lists']
assert lane['recommendation_counts']['US_MAPPING']['watch'] == 153
assert lane['recommendation_counts']['US_MAPPING']['selected'] == 0
result = dict(
    status='API_VERIFIED_EXISTING_RUN_DISPLAY_FIX', http_status=status, run_id=run,
    response_sha256=hashlib.sha256(raw).hexdigest(), response_bytes=len(raw),
    recommendation_counts=lane['recommendation_counts'],
    candidate_stock_counts=lane['counts'],
    original_record_counts=lane['recommendation_projection']['source_decision_counts'],
    recommendation_projection=lane['recommendation_projection'],
    pagination=lane['pagination'],
    saved_directions_and_decisions_unchanged=True, new_run_submitted=False,
    observed_at=datetime.now(timezone.utc).isoformat(),
)
(H / 'ROOT_API_READBACK_R4.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({k: v for k, v in result.items() if k != 'recommendation_projection'}, ensure_ascii=False))
