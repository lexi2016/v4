"""Full-size synthetic plan scan. Inventory supplies sizes, not original products."""
from collections import defaultdict
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import platform
import sys
from time import perf_counter

from test_manager_three_lane_history_r1 import DATE, stored, hashes
from v4.manager_research import workspace_history as history
from v4.manager_research.store import ManagerResearchStore
from v4.manager_research.workspace_plan import plan_context
from v4.manager_research.workspace_projection import digest

ROOT = Path('/workspace/scratch/90a399518fca/review_history')
DATA = ROOT/'scale_synthetic_r2'
DATA.mkdir(exist_ok=True)
INVENTORY = Path('/workspace/scratch/90a399518fca/input/V4_三路选股闭环_问题包_20261011/evidence/historical-plan-inventory.json')
metadata = json.loads(INVENTORY.read_text())
store = ManagerResearchStore(DATA)
latest_source = next(row for row in metadata['files'] if row['name'] == 'latest.json')
created = []
for number, item in enumerate((item for item in metadata['files'] if item['name'] != 'latest.json'), 1):
    product, attempt = stored(store, number, item['generated_at'])
    (store.root/'workspace_plan_runs'/DATE/(attempt['run_id']+'.json')).unlink()
    product['workspace']['plan_context'] = plan_context(DATE, now=datetime.fromisoformat(item['research_cutoff']))
    for offset in range(3):
        product['workspace']['announcement_review'] = {'synthetic_multibyte_text': 'x'*offset+'研'*20000}
        product['workspace']['synthetic_padding'] = ''
        product['sha256'] = '0'*64
        base = json.dumps(product, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
        try:
            base[:history._MAX_HEADER_BYTES].decode('utf-8')
        except UnicodeDecodeError:
            break
    else:
        raise AssertionError('multibyte boundary not exercised')
    product['workspace']['synthetic_padding'] = 'x'*(item['bytes']-len(base))
    product['sha256'] = digest({key:value for key,value in product.items() if key != 'sha256'})
    raw = json.dumps(product, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    assert len(raw) == item['bytes']
    path = store.root/'workspace_plans'/DATE/(product['run_id']+'.json')
    path.write_bytes(raw)
    created.append({'name':path.name, 'bytes':len(raw), 'file_sha256':hashlib.sha256(raw).hexdigest(),
                    'generated_at':product['generated_at'], 'source':'SYNTHETIC_VALID_JSON'})
    if item['run_id'] == latest_source['run_id']:
        (path.parent/'latest.json').write_bytes(raw)
        created.append({'name':'latest.json', 'bytes':len(raw), 'file_sha256':hashlib.sha256(raw).hexdigest(),
                        'generated_at':product['generated_at'], 'source':'SYNTHETIC_VALID_JSON'})
    del raw, product
assert len(created) == 7
assert sum(item['bytes'] for item in created) == 147031510
before = hashes(store.root)
metrics = defaultdict(int)
original_count = history.count
original_read = store._io.read_bytes
full_reads = []
def record_count(name, value=1):
    metrics[name] += value
    return original_count(name, value)
def record_read(path, **kwargs):
    raw = original_read(path, **kwargs)
    full_reads.append({'path':path, 'bytes':len(raw)})
    return raw
history.count = record_count
store._io.read_bytes = record_read
started = perf_counter()
try:
    boundary = history.boundary_context(DATE)
    selected = history.select_plan(store, DATE, boundary)
    outcome = {'selected':selected is not None, 'exception':None}
except Exception as error:
    outcome = {'selected':None, 'exception':type(error).__name__, 'reason':str(error)}
finally:
    elapsed = perf_counter()-started
    history.count = original_count
    store._io.read_bytes = original_read
unchanged = before == hashes(store.root)
source_path = Path(history.__file__)
result = {'scope':'SYNTHETIC_SAME_SIZE_ONLY_NOT_ORIGINAL_PRODUCTS_OR_MAC_ACCEPTANCE',
    'python':sys.version, 'platform':platform.platform(),
    'implementation':str(source_path), 'implementation_sha256':hashlib.sha256(source_path.read_bytes()).hexdigest(),
    'inventory_sha256':hashlib.sha256(INVENTORY.read_bytes()).hexdigest(),
    'synthetic_file_count':len(created), 'synthetic_total_bytes':sum(item['bytes'] for item in created),
    'journals_present':False, 'multibyte_prefix_boundary_exercised':True,
    'result':outcome, 'metrics':dict(metrics), 'full_read_calls':full_reads,
    'read_elapsed_seconds':elapsed, 'files_unchanged':unchanged, 'synthetic_files':created}
result['assertions'] = {
    'no_exception':outcome['exception'] is None,
    'no_late_plan_admitted':outcome['selected'] is False,
    'zero_full_body_reads':not full_reads and metrics.get('saved_plan_bytes',0) == 0,
    'bounded_header_reads':metrics.get('saved_plan_probe_bytes') == 7*history._MAX_HEADER_BYTES,
    'seven_late_exclusions':metrics.get('saved_plan_late_headers_excluded') == 7,
    'no_writes':unchanged}
(ROOT/'probe_history_r2_scale_result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
print(json.dumps(result, ensure_ascii=False, indent=2))
assert all(result['assertions'].values())
