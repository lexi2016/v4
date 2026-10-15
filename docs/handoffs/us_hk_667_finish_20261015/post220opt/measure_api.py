"""Compare frozen preopt220 and candidate through the same in-process API.

No service is started, and no file/cache in a running release is changed.
Timings include TestClient/FastAPI response serialization, not browser/network.
"""
from pathlib import Path
import hashlib
import importlib.util
import json
import platform
import statistics
import time
from fastapi import FastAPI
from fastapi.testclient import TestClient
import v4.manager_workbench.api as api
from v4.manager_workbench.us_mapping_catalog import CatalogStore

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
old_path = HERE/'preimage/v4/manager_workbench/us_mapping_catalog.py'
spec = importlib.util.spec_from_file_location('frozen_preopt220_catalog', old_path)
old = importlib.util.module_from_spec(spec)
spec.loader.exec_module(old)
results = {}
identities = []
for label, store in [('preopt220', old.CatalogStore()), ('candidate', CatalogStore())]:
    api._US_MAPPING_CATALOG_STORE = store
    app = FastAPI()
    app.include_router(api.create_router(None))
    with TestClient(app) as client:
        start = time.perf_counter()
        cold = client.get('/api/v4/manager-workbench/mapping-catalog')
        cold_ms = (time.perf_counter()-start)*1000
        assert cold.status_code == 200
        queries = {}
        for name, query in [('default', ''), ('stock_00001', '00001'), ('US_CVE', 'CVE'), ('RID_R001', 'R001')]:
            timings = []
            sizes = []
            for _ in range(8):
                start = time.perf_counter()
                response = client.get('/api/v4/manager-workbench/mapping-catalog', params={'q':query})
                timings.append((time.perf_counter()-start)*1000)
                assert response.status_code == 200
                sizes.append(len(response.content))
            data = response.json()['data']
            identities.append((data['catalog_integrity_sha256'], data['review_source']['integrity_sha256'], data['review_progress'], data['safety']))
            queries[name] = {'milliseconds': timings, 'mean_ms': statistics.mean(timings),
                'serialized_response_bytes': sizes[0], 'response_size_stable': len(set(sizes)) == 1,
                'matching_stocks': data['total']}
        results[label] = {'cold_default_ms': cold_ms, 'queries': queries}
assert all(identity == identities[0] for identity in identities)
overlay = ROOT/'v4/manager_workbench/research_data/us_hk_667_review_overlay_20261015.json'
assert overlay.read_bytes() == (HERE/'preimage/v4/manager_workbench/research_data/us_hk_667_review_overlay_20261015.json').read_bytes()
result = {'python': platform.python_version(), 'platform': platform.platform(),
    'method':'8 sequential warm TestClient calls per query, same canonical API route and unchanged source files; cold default separately. Includes FastAPI serialization. No live8873 service/browser/network benchmark.',
    'overlay_sha256': hashlib.sha256(overlay.read_bytes()).hexdigest(),
    'progress_and_safety_identical':True, 'results':results}
print(json.dumps(result, ensure_ascii=False, indent=2))
