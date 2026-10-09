# Issue32 Mac recovery — API publication milestone

Target date: 20261009. Fixed incoming source: 9c4b868683a8a4547386cef22354c4f2299c2c26.

The preselection API repair is deployed on the Mac. A real request reads 37 premarket rows and 186 research-source rows, deduplicated to 216 A-share symbols. API pages return 200+16; the reloaded UI displays 200/216 and the complete 186-row research pool. UI rendering of all 216 rows is not claimed. The Stage preparation used all 216 inputs.

Actual runtime is issue32_preselection_api_actual_r4 under the permanent task candidate directory, not the canonical checkout or formal release directory. The exact root, manifest, PID, operation receipt and post-publication checks are in API_DEPLOYMENT_RESULT.json. All 1,015 non-delta application entries were preserved. The three API source files are byte-identical to the fixed incoming package; they are referenced rather than duplicated here.

The first publication stopped before changing the pointer because launchd unload was checked too early. The recorded rollback restored the old API. The reviewed fix adds bounded state-transition waits, verifies allowed transaction identities, rejects timeout/unknown state and checks the pointer again after waiting. The second guarded publication succeeded. Both incidents remain in local receipts. No scheduler or Stage plist was changed by the API publication.

Independent Mac checks: source suite 150, review probes 17, combined API replay 72; unchanged full-app candidate behavior; strict additive-field validation; 9 transition cases. These are separate suites with overlap, not a unique-test count. The 150/17 suites had non-failing pytest temporary cleanup warnings; retained in the review.

HK is still blocked: the required 20261008 security master has no verified entry/trio in the bounded inspected owner/store/archive paths. The 20261008 price observation exists but is not Connect eligibility. Latest confirmed master is 20260930. Today's snapshot and older records must not be relabeled as yesterday.

The original issue's inference that the executor did not run is corrected: 17:30/18:00 workload results prove execution and exact-date reuse failure. Empty started_workload_ids did not prove absence of invocation.

09:15 produced the V3 A acquisition universe (216 rows); an earlier V2-path check was incorrect. The 09:25 A artifact selected 10 from 205 observed of 216 requested symbols, with 11 missing. It is PARTIAL_WITH_ROWS/RECOVERY, not natural-slot acceptance. HK remains separate.

Remaining work: paired scheduler/shared preparation integration and full actual-facade acceptance are still in progress at this milestone. No claim of complete HK recovery or daily automatic success. This delivery excludes raw market data, full HTTP payloads, live plists, credentials and full runtime plans. Research-only boundaries remain unchanged.
