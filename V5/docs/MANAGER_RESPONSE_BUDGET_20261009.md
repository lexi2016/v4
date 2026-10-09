# Manager response publication budget candidate

Parent/Mac read-only report: fixed `074a65e100fb675581607ac033ffa861929d9afc` passed 101/101 combined tests. Real plan `468c25...` publication failed at lexical precheck. Cloud did not read the Mac evidence file; the parent supplied these measurements:

| Object | UTF-8 bytes | Lexical nodes | Depth | Parsed value nodes |
|---|---:|---:|---:|---:|
| payload | 7806965 | 252467 | 8 | 139487 |
| read envelope | 7837730 | 254143 | 9 | 140674 |
| publication record | 7807440 | 252493 | 9 | 139500 |

1735 materials occur once (5598853 bytes / 221981 lexical nodes). Their source_refs repeat 1735 times across 32 unique bindings (1629780 repeated bytes / 69400 nodes); source_row has 1679 unique rows and 56 duplicates. These repetitions carry evidence references, so a deduplicated transport would need an explicit resolver contract.

Source inspection: original workspace_projection retains a deep copy of every admitted material. Original archive projection retains article source_row, material identity, time fields and source references. Those are traceability fields, not proven removable duplicates. Replacing them with references requires a new retrieval/UI contract. This patch therefore does not rewrite payload, delete evidence, truncate input, or alter the frozen original owner.

The finite dedicated budget is 300000 lexical nodes (47507 nodes over the reported publication record), with default lexical 200000 unchanged. Parsed-value nodes remain capped at 200000 for every response, including manager; field names still count in the lexical limit. It applies to:

- Publication and immutable/legacy record readback for trusted config module_id `manager` with configured exact `/api/v4/manager/research/workspace` route; the record must be v5.module_response.v1, module_id manager, exact path, OWNER_RESULT, status_code 200. Existing release/query/hash validation remains mandatory. Other record identities fall back to default validation and cannot be accepted above 200000.
- Gateway responses only for configured module_id manager, exact workspace path, GET, HTTP 200. Gateway sees the ordinary payload, not the record envelope; data-kind validation stays in module publication/readback. Query dates/views do not change the budget.

Request body budgets, POST, other paths/modules, errors, active pointers and generation manifests retain their default limits. No caller-provided query/header/config budget exists. The pre-JSON-allocation lexical scan, 64-depth checks, 16 MiB response/record limits, generation total bytes, bounded concurrency, timeout, immutable digests and compare-and-swap activation remain. Added parser-level byte check reinforces existing read limits.

Risk: the manager success response may contain up to 50% more lexical tokens including field names; parsed-value allocation remains capped at 200000; 16 MiB and concurrency limits still apply. Manager-config record parsing provisionally permits 300000 before validating embedded identity, then rejects nonqualifying records at 200000 without a second JSON allocation. The measured production node count is supplied by the parent from Mac read-only diagnostics; 300000 is deliberately finite, and future larger output still fails. Unrelated module configs never enter provisional enlarged parsing. No real publication or gateway activation performed here.

Cloud: four Python files AST-checked; git diff whitespace check. Product tests NOT_RUN. Mac candidate command:
```bash
PYTHONPATH=V5/src:V5/tests python3 -m unittest test_manager_response_budget.ManagerResponseBudgetTests test_module_artifacts test_module_api test_api_gateway -v
```
Nine new tests: exact 200000 and 300000 lexical boundaries; unchanged manager 200000 parsed-node limit; field-dense oversized object rejection; unchanged depth/bytes/nonfinite protections; route/method/status isolation; forged record metadata/other module rejection; full publication→next generation→module API→gateway payload equality; over-budget rejection preserving active generation. Actual real-plan publication remains independent Mac acceptance, using the existing saved plan rather than new business calculation.

Previous optional registry-observation candidate is in ancestor a21f430; omit registry_observation request key during this P1 acceptance. That observation feature is separately unverified and not needed for the budget fix.
