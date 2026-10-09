# Issue32 Mac recovery — API and scheduler delivery

Target date: 20261009. Fixed incoming source: 9c4b868683a8a4547386cef22354c4f2299c2c26.

The preselection API repair is deployed on the Mac. A real request reads 37 premarket rows and 186 research-source rows, deduplicated to 216 A-share symbols. API pages return 200+16; the reloaded UI displays 200/216 and the complete 186-row research pool. UI rendering of all 216 rows is not claimed. The Stage preparation used all 216 inputs.

Actual runtime is issue32_preselection_api_actual_r4 under the permanent task candidate directory, not the canonical checkout or formal release directory. The exact root, manifest, PID, operation receipt and post-publication checks are in API_DEPLOYMENT_RESULT.json. All 1,015 non-delta application entries were preserved. The three API source files are byte-identical to the fixed incoming package; they are referenced rather than duplicated here.

The first publication stopped before changing the pointer because launchd unload was checked too early. The recorded rollback restored the old API. The reviewed fix adds bounded state-transition waits, verifies allowed transaction identities, rejects timeout/unknown state and checks the pointer again after waiting. The second guarded publication succeeded. Both incidents remain in local receipts. No scheduler or Stage plist was changed by the API publication.

Independent Mac checks: source suite 150, review probes 17, combined API replay 72; unchanged full-app candidate behavior; strict additive-field validation; 9 transition cases. These are separate suites with overlap, not a unique-test count. The 150/17 suites had non-failing pytest temporary cleanup warnings; retained in the review.

HK is still blocked: the required 20261008 security master has no verified entry/trio in the bounded inspected owner/store/archive paths. The 20261008 price observation exists but is not Connect eligibility. Latest confirmed master is 20260930. Today's snapshot and older records must not be relabeled as yesterday.

The original issue's inference that the executor did not run is corrected: 17:30/18:00 workload results prove execution and exact-date reuse failure. Empty started_workload_ids did not prove absence of invocation.

09:15 produced the V3 A acquisition universe (216 rows); an earlier V2-path check was incorrect. The 09:25 A artifact selected 10 from 205 observed of 216 requested symbols, with 11 missing. It is PARTIAL_WITH_ROWS/RECOVERY, not natural-slot acceptance. HK remains separate.

The paired scheduler/shared repair is now DEPLOYED: scheduler release `issue32-preselection-scheduler-mac-20261009-r1` and shared owner `issue32-hk-security-master-owner-mac-20261009-r1`, activated with reviewed R3 configuration. Independent focused tests: 108 passed with 5 non-failing temporary-directory cleanup warnings. The real facade binding and announcement constructor were checked separately. The facade canary uses controlled child stubs and reuses actual materializer output; it stops at HK_SECURITY_MASTER, retains A37/research186, and makes no HK scoring call. This is scoped BEHAVIOR_VERIFIED, not a successful live HK subprocess or Stage run.

The first scheduler activation exposed an inherited announcement pin mismatch and was rolled back. The old plist and R2 shared the same stale app-root, cycle SHA and canary SHA. R3 changes only those three pins to match the existing announcement binding. The real constructor passed under the actual runtime; final startup and loaded identity were independently checked. DAEMON_READY alone was not accepted as proof of the announcement hook. Previous roots and exact plist preimage remain available for rollback; Stage service configuration and Vibe 8910 were not changed.

The original 11:00 scheduler/hourly research slot ran automatically: SUCCEEDED / READY_WITH_RESEARCH_POOL, with only hourly_research. This verifies that scheduler/hourly slot only. Shared acquisition is NOT_STAGE_SLOT and natural_execution_verified=false. Stage NATURAL_SLOT_UNVERIFIED and HK recovery CANNOT_CONFIRM remain. The isolated selector-ready input also remains CANNOT_CONFIRM.

Six current canonical source files were read back against the fixed source delivery already inherited from incoming commit 9c4b8686. See scheduler/CANONICAL_REMOTE_SOURCE_VERIFICATION.json. Actual-owner and canonical identities remain distinct; no unrelated local changes or redundant source copies were uploaded.

One non-blocking P2 remains in optional verified-source master restoration: original owner writers must be quiescent because the final compare/replace is not locked. The deployed scheduled path does not configure that optional source restore. A separate existing P2 is that announcement initialization failure can coexist with DAEMON_READY; the final publication therefore checked startup errors explicitly.

Observed runtime receipts retain production_allowed=false, buy_gate_updated=false, orders_sent=false, and external_source_read_only=true. The runtime RESEARCH_ONLY field itself was not exposed and is CANNOT_CONFIRM at that field level; the task remains research-only. No claim of complete HK recovery or natural Stage success is made.

This delivery excludes raw market data, full HTTP payloads, live plists, account information, credentials and full runtime plans. Included local reproduction tools depend on existing owner inputs and local dependencies; this evidence slice is not a standalone deployable application.

Metadata P2: the immutable scheduler/shared build manifests retain their pre-activation labels. Use SCHEDULER_DEPLOYMENT_RESULT.json and the independent post-deploy receipt for actual loaded status; the inconsistency is retained rather than rewriting a SHA-bound live manifest.
