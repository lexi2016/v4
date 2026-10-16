# R2 live independent engineering review
Reviewer: `mapping_recovery_review` (independent from `mapping_recovery_writer`)
Candidate manifest SHA256: `ae2ca8cee0380217b8c09a3dc3baed5cc88f27c82b02d4cd68668b15d79c5359`
LIVE_ENGINEERING_INTEGRATION=PASS — The active API-only service, live mapping API response, and served manager-selection JavaScript match the prepared R2 candidate and target contract.
API_VERIFIED=PASS — Live GETs returned the 667/1003 accounting, all expected closure totals and exact-RID records, retained prior-700 history, and research-only safety flags.
STATIC_HTTP_VERIFIED=PASS — The manager-selection page and its hashed JavaScript returned HTTP 200; the JavaScript bytes match the selected candidate release file.
UI_VERIFIED=CANNOT_CONFIRM — This review did not inspect the rendered page; independent CUA inspection is pending.

## Runtime identity

The active plist SHA256 is `001b0b9dc70f041818d84b9c7ed1065df5ff856abeeccf888d0323df9eca5958` and selects release `us-hk-recovery-v2r1-20261016-r2`, manifest SHA256 `ae2ca8cee0380217b8c09a3dc3baed5cc88f27c82b02d4cd68668b15d79c5359`, and config SHA256 `589eaa058b9abd9cef59ab71ef2c3f4c3c998bae18dd26777134bf0fa22ef86e`. Read-only `launchctl print` reported `running`, PID `52858`; the only port-8873 listener was PID `52858`; `lsof` reported the candidate app as its working directory. An independent `verify_api_release_candidate` call with `active_pointer='candidate'` returned PASS and retained the exact six-path delta plus 1,211 unchanged entries (non-delta inventory SHA256 `64887c095d00f6be15c03385b3f6c6a0158eda9f6a7ee1a3f536e59da3f33723`). The activation receipt reports `ACTIVATED_API_READBACK_OK`, with preflight and postflight verifier status PASS.

## Live API and static response

`GET http://127.0.0.1:8873/api/v4/manager-workbench/mapping-catalog` returned HTTP 200 (`application/json`, 772,473 bytes; SHA256 `0a2f322ea5874601e7ba1485b584956a944db9226c138c0fe7add68ffe34b6ef`). It reports 667 snapshot stocks, 1,003 original and processed relations, 757 `CLOSED_RESEARCH_SCOPE`, 25 `CLOSED_EXCLUDED_SCOPE`, and 221 `OPEN`. Exact-RID GETs returned one FULL-detail record each: R006 `CLOSED_RESEARCH_SCOPE`, R003 `CLOSED_EXCLUDED_SCOPE`, R001 `OPEN`, and R700 `CLOSED_RESEARCH_SCOPE`. R700 remains `NOT_PROCESSED` in the prior source-review state, with its recovery detail available at FULL level.

The separate prior-700 history remains present with 700 records, SHA256 `d45d44fb074fc82923a0af5e37a8d645923a84acb48dc2bb1794b1f4ddc98c69`, and `status_crosswalk=NOT_ESTABLISHED`. Safety remains `RESEARCH_ONLY=true`, `production_allowed=false`, `buy_gate_updated=false`, and `orders_sent=false`.

`GET /manager-selection/` returned HTTP 200. Its HTML selected `/assets/managerSelection-DfkJEj5r.js`; that asset returned HTTP 200 with SHA256 `50671d5dfd096de3f1eaebbdace53fec0facfaf3fb3f431f9696e20f61247d67`, identical to the candidate release file.

## Limits

No runtime identity, API contract, or served-asset mismatch was found. Semantic mapping validity remains `CANNOT_CONFIRM`; historical PIT remains `NOT_VALIDATED`; prediction validation remains `UNTESTED`; independent fact acceptance remains zero. Overall workflow acceptance remains unissued. Natural-slot verification is not required for this static catalog integration. This review made no source, configuration, service, or data-store changes; it writes only the independent receipts. Rendered-page verification remains pending the separate CUA review.
