# Milestone completion/API connection repair

Baseline: `a67e81143f8a936df303356e532b6520850dfdb2`. Isolated Writer branch `codex/schedule-chain-repair-20261102`.

A successful Main milestone returned fields absent from its persisted receipt. Its complete Stage market JSON was also truncated by the executor's existing 2048-character cap. The API correctly refused to bind this stdout to the business receipt, leaving the timeline `CANNOT_CONFIRM`.

The milestone now persists its final returned fields, retains the complete business receipt, and prints a small versioned reference containing its exact path, SHA and node/date/stage/run/status. The API reads its own existing fixed receipt path and checks the reference against that independently read SHA and exact identity. A stdout path grants no file-read authority. The existing full-stdout equality path and common output cap are retained. Failure class/reason remain visible to the original dispatcher classification policy; optional sidecar failure stays separate from the primary milestone.

Integration ownership is narrow:

- Main: replace only `ops/run_stage_center_milestone.py` (r4 preimage SHA equals source baseline).
- API: replace only `domains/task_status.py` (r4 preimage SHA equals source baseline).
- Stage: no business file change. Do not copy Main/API modules across roles.
- Terra alone updates the existing candidate builder/manifest/bindings. No Main catalog registration, intraday enabling, Vibe8910 action, publication or launchd change.

`RESULT.json` contains before/after SHA and exact targeted commands (replace its `python` token with the recorded absolute interpreter). Fifteen unique direct cases passed incrementally: normal completion with API business READY, repeat without another milestone, foreign runner/expired event, failed consumer retry of the same immutable Stage run, seven reference rejection cases, real 2048 truncation, optional sidecar failure persistence, legacy exact stdout positive/negative, and actual milestone CLI reference. A separate API-role subprocess seam passed. Tests mutate task-owned temporary fixtures only; the registry/ledger/store/milestone/manager StageFeed/API are real, while child invocation is a local transport seam. Manager model execution, market collection, all-day natural operation and deployment are not certified.

The initial weak r2 candidate check passed process/identity connections but did not assert business READY. The strengthened oracle exposed the real failure. The first writing-order repair still failed due to truncation; the second compact-reference check passed normal READY but lost failure classification. Writer stopped; controller explicitly authorized one metadata-preservation correction, which passed its affected case. This bounded exception and the earlier test-only method-name/truncation-suffix mistakes are preserved in the result; none are hidden as PASS.

After Terra assembles final roles, execute the harness from the Main app with `PYTHONPATH=<main-app>:<main-app>/upstreams`, `SCHEDULE_CHAIN_API_APP=<api-app>`, `PYTHONDONTWRITEBYTECODE=1`, original candidate release identity env, and graph/sidecar/foreign task-status env absent:

`<absolute-python> -B <writer-source>/tests/test_schedule_chain_connections.py`

This performs fixture completion/dispatch/milestone/manager reads in the actual Main app, then ASGI status reads in the actual API app in a separate bounded subprocess. It opens no listener/service and deletes only its temporary fixture. The final assembled candidate run and independent Reviewer remain pending at Writer handoff.

Read-only diagnosis is in `/Users/lexi/Desktop/学习/agents调试/v4_schedule_chain_repair_20261102/DIAGNOSIS.json` and `DEADLINE_DIAGNOSIS.json`. The five morning HK trios match their runner identities (10 rows each); A 09:25 lacks its original snapshot, later four A stages lack the F10 completion witness handled by Terra. The 26 task registrations are all disabled/non-dispatchable contract entries. Main lacks the API's intraday workload and required binding environment; retain `CANNOT_CONFIRM` rather than enable another producer. PDF/WeChat are not changed.

HK deadline correction: the import traceback is September stderr (`STALE`), not a November error. The actual current release's read-only `--check` returns `CHECK_OK` with empty stderr. Today's five deadline alerts remain real missing-at-deadline observations; current later pointers do not certify timely publication. No deadline code/launcher change is justified by this evidence, and no 5-second hard-timeout/business-success claim is made.

Mature upstream references were used only to frame existing idempotency and typed failure checks: [Kubernetes CronJob](https://kubernetes.io/docs/concepts/workloads/controllers/cron-jobs/) and [Step Functions error handling](https://docs.aws.amazon.com/step-functions/latest/dg/concepts-error-handling.html). No framework, dependency, producer or retry policy was added.
