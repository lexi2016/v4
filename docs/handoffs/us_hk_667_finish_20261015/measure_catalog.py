"""Small in-process measurement, not a browser latency benchmark."""
from pathlib import Path
import hashlib
import json
import platform
import statistics
import time
from v4.manager_workbench.us_mapping_catalog import CatalogStore

ROOT = Path(__file__).resolve().parents[3]
base = ROOT/'v4/manager_workbench/research_data/us_hk_667_catalog_20261015.json'
overlay = ROOT/'v4/manager_workbench/research_data/us_hk_667_review_overlay_20261015.json'
store = CatalogStore()
start = time.perf_counter()
store.search(base, overlay, 'CVE')
cold = (time.perf_counter()-start)*1000
samples = {}
for query in ['CVE', '', 'R001']:
    timings = []
    for _ in range(8):
        start = time.perf_counter()
        body = store.search(base, overlay, query)
        timings.append((time.perf_counter()-start)*1000)
    samples[query or 'default_page'] = {
        'milliseconds': timings, 'mean_ms': statistics.mean(timings),
        'response_json_bytes': len(json.dumps(body, ensure_ascii=False).encode()),
    }
result = {
    'python': platform.python_version(), 'platform': platform.platform(),
    'method': '8 sequential in-process calls per query; cold separate; no network/browser timing; full revision/evidence included',
    'cold_ms': cold, 'queries': samples,
    'overlay_sha256': hashlib.sha256(overlay.read_bytes()).hexdigest(),
    'base_sha256': hashlib.sha256(base.read_bytes()).hexdigest(),
    'progress': body['review_progress'],
}
print(json.dumps(result, ensure_ascii=False, indent=2))
