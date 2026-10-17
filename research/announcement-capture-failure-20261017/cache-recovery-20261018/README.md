# Issue 44 cached-product recovery — terminal verification

The bounded cache recovery fix is implemented, independently tested (30 passed), deployed and terminally verified. One explicit POST recovered the exact saved product into new job c3717353b23c4257af5a10be41a69db9 without recapture. Actual new model output, persisted result and API binding were verified. Rendered UI matches target date, completion time and seven new candidates. The UI does not render the job ID and some status badges remain unknown; those limits are preserved.

The run finished at 2026-10-18 02:35:19 +08:00 with PARTIAL research results: main tasks 192 succeeded / 3 failed; long-body parts 27 succeeded / 18 failed; zero queue pending. The 38 aggregate failure items comprise 17 retained historical failures, 3 new main-task failures and 18 part failures. One body gap and 21 membership-unknown rows remain. Seven new model candidates are unreviewed. This is recovery-behavior acceptance, not semantic acceptance of model conclusions.

The independent terminal verdict is PASS_WITH_P2. The retained nonblocking cursor-write edge requires auditing a failed POST before retry. All 1,001 immutable protected baseline files remain unchanged; only the mutable queue-state file changed. No old successful output was overwritten. No repeated tests or successful-task re-inference was requested.

integrated-source contains the exact bounded overlay applied to the active base; unrelated canonical api.py changes are preserved locally and excluded. This evidence branch is not a complete runtime tree. No raw capture, model output, API response, logs, credentials or runtime release directory is uploaded. See verification.json and terminal-review.json for hashes, counts, limitations and financial gates.
