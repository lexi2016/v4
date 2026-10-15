# Cumulative220 catalog on-demand detail candidate

Status: IMPLEMENTED_WITH_WRITER_CHECKS / READY_FOR_INDEPENDENT_REVIEW. No independent verdict, integration, deployment, commit or push is claimed. This batch only addresses the measured oversized catalog list response. Source root remains `/Users/lexi/Desktop/学习/v4_app`. Preopt220 files were frozen before modification; all9 frozen preimages were verified intact after the interrupted turn resumed. No old preimage/receipt was recreated or overwritten.

Normal default, stock and US queries now return original catalog fields plus the necessary source revision summary: dated fact/current-applicability states, reason, outstanding evidence, source proposed use, supported scope, current limits/next evidence and full subsequent addenda. Full field assessments, complete research record and per-URL evidence remain in the unchanged overlay and are returned only for an explicit exact RID query. The API route and transport are reused. Every returned relation has `review_detail_level=SUMMARY|FULL`; no new endpoint, service or producer was added.

Each relation exposes “查看完整补证 RID”. Clicking performs a GET for that exact RID and renders original full fields, full source research record, field assessments and evidence links. A503 failure remains visible beside the correct RID and allows retry. Requests are keyed by RID and list generation, cancelled on a list/page/panel change; late responses cannot enter a later page. The detail response must match requested RID, HK/US/source-row identity, catalog/revision SHA and research safety flags. A wrong RID is rejected visibly. Direct RID search is also an explicit full-detail request.

Source overlay is byte-unchanged: SHA256 `72a0f074e6412036cd103c7f73ccf15230eb3d1633c09742c88653b863eba384`. Its full220 source revisions, all source/evidence records, original667/1003 data and R021/R137 boundaries remain available. All220 explicit RID revisions were tested for exact equality with the overlay. Progress remains220 relations/92 stocks/89 stocks with every original edge recorded/783 unprocessed/0 independently verified. Original fact_review_status=PENDING, prediction_eligible=false, prediction UNTESTED, historical PIT NOT_VALIDATED and all research safety flags remain unchanged. The incomplete700 part3 input was not ingested; pool code/services were not touched.

Actual API comparison uses the frozen preopt220 CatalogStore versus candidate CatalogStore through the same current canonical FastAPI catalog route and TestClient, same unchanged source files,8 sequential warm calls per query. It includes response serialization, excludes a live8873 service/browser/network and is not a rendered-page latency claim. Reproducer: `PYTHONPATH=. .venv/bin/python docs/handoffs/us_hk_667_finish_20261015/post220opt/measure_api.py`. Full samples and machine identities are in api_measurement.json.

| Query | Preopt serialized bytes | Candidate serialized bytes | Preopt warm mean | Candidate warm mean |
|---|---:|---:|---:|---:|
| Default25 stocks | 4,784,175 | 611,266 | 56.83ms | 9.56ms |
| Stock00001 | 264,202 | 51,070 | 3.90ms | 1.53ms |
| US CVE | 444,595 | 85,451 | 15.44ms | 11.12ms |
| RID R001 full | 83,749 | 83,778 | 2.03ms | 1.86ms |

Default API bytes decreased87.22% and are below1MB. Its627,644-byte plain `json.dumps` measurement differs from611,266 actual API wire bytes due to serializer formatting/envelope. Cold default API calls measured205.90ms before and153.08ms after; cold values are single observations. R001’s29 additional bytes are the explicit detail-level field; complete source content is unchanged.

Writer checks:

- `PYTHONPATH=. .venv/bin/pytest --basetemp=/tmp/us_hk_finish220opt_writer_20261015 -q tests/manager_workbench/test_us_mapping_catalog.py`:12 passed in2.49s, one existing Starlette/httpx deprecation warning. Includes full original conservation, unchanged progress/safety, bounded default list payload, absence of heavy revision/evidence fields in normal queries, all220 exact-RID full-source equality, API source identity and existing tamper fail-closed tests.
- From apps/web: `node_modules/.bin/vitest run src/manager-workbench/__tests__/us_mapping_catalog.spec.ts`:1 passed, latest run322ms test time. The component scenario covers lazy tab, normal summary without evidence prefetch,503 failure and retry, request pending during pagination, discarded late response, wrong-RID rejection, successful on-demand evidence rendering, unchanged220 progress/filter/search, source summary/addenda and safe URL handling.
- From apps/web: `node_modules/.bin/vue-tsc --noEmit --strict --skipLibCheck --target ES2022 --module ESNext --moduleResolution Bundler --types vitest/globals src/manager-workbench/Workbench.vue src/manager-workbench/useWorkbench.ts`:PASS.

Actual ownership:6 changed paths are listed in owned_changed_paths.json. Catalog-only sourcebase_delta.diff is373 lines from the frozen preopt220 bytes. delta_from_catalog40.diff is506 lines from the separately frozen40 candidate, for a controller/integrator whose active base still has40. The220 overlay must accompany a40→220 integration. Apply exact scoped hunks to the independently verified active base; do not copy canonical directories or replace active api.py. Pre/postimage SHA manifests record observed bytes.

Concurrent external change: canonical api.py changed from preopt SHA `0f0bed4dfc8636c4893ade8c44dd51f0bcb7c17f31a035f986cbb2f7f3952113` to observed SHA `231ce028428f73e077770ba8cf2521401546fafe29c3e60f394af1edb2a41faa` during this batch, solely in HK-history resolution/mode/fields behavior. This writer did not edit those bytes and preserved them. They are isolated in concurrent_api_change.diff/concurrent_changes.json and excluded from both catalog delivery deltas. Catalog API route and api.ts were not modified by this optimization. Preserve active industry/48-source/HK-history behavior during integration.

Independent review, live API/UI, build/deployment and natural-slot results: NOT_RUN by this writer. Independent company-fact verification, prediction/backtest/PIT and old997 comparison remain NOT_RUN / CANNOT_CONFIRM. No additional cleanup or architecture work was undertaken.
