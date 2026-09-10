# V3.5 session closeout — 2026-08-22

## Status

`PARTIAL / NATURAL_SLOT_UNVERIFIED`

The candidate scheduler integration is implemented and focused-tested. It is
not formally installed or deployed. Therefore a natural LaunchAgent run,
formal current pointer, API response, and reloaded 8873 page remain
`CANNOT_CONFIRM` in this batch.

## Boundary incident — Desktop tree excluded from delivery

An early UI agent write was recorded in the read-only Desktop project tree at
approximately 11:13–11:17. The reported seven files were:

```text
apps/web/src/App.spec.ts
apps/web/src/App.vue
apps/web/src/components/research/ResearchFeedCard.vue
apps/web/src/components/research/ResearchSourceColumns.vue
apps/web/src/composables/useResearchLane.ts
apps/web/src/views/ResearchView.spec.ts
apps/web/src/views/ResearchView.vue
```

A second agent write was recorded in the same Desktop project context at
approximately 11:30–11:34:

```text
ops/wechat_preselection_sync.py
ops/wechat_probe.py
tests/test_wechat_probe_and_sync.py
```

The same window also generated these test cache files under
`tests/__pycache__/`:

```text
test_preselection_optional_pools*.pyc
test_preselection_slice*.pyc
test_wechat_probe_and_sync*.pyc
```

These Desktop-tree bytes are boundary-incident evidence only. They are not
counted as candidate implementation, test, or delivery artifacts. Sol did not
revert, delete, or overwrite them. The active Documents candidate contains its
own bounded scheduler/research integration and is the only worktree counted in
this closeout; no Desktop bytes were copied, reconciled, or used as a write
source.

## Delivered in the active candidate root

`/Users/lexi/Documents/Codex/2026-08-13/v35-stage-selection-20260821-fix/release-candidate/app`

- Added fixed 09:01/20:01 WeChat and 21:15 Review Core workload registrations;
  added exact 17:00 A and 17:20 HK research-panel producer lanes, and retained
  17:30 research-panel runtime evidence as a publisher-only lane. The producer
  lanes reuse the existing formal `com.lexi.research-panel.daily` entry and
  full authority arguments; they do not create a second collector.
- Hardened the candidate LaunchAgent renderer: it now requires and emits the
  launch shell, explicit AppSupport/release roots for every registered shell,
  research-panel and Review Core adapter binding, release/fingerprint identity,
  and both uppercase/lowercase false safety environment keys. It rejects a
  partial binding rather than allowing implicit path fallback.
- Bound future WeChat input to the separate
  `data_root/preselection_inputs/{date}` source root and output to
  `data_root/preselection_pools/{date}`; the historical 20260821 pool-sidecar
  pair is evidence-only and never a natural fallback. The exact-pair producer
  ownership remains explicit.
- Changed missing/partial WeChat and Review Core results to typed retryable
  `UPSTREAM_NOT_READY` failures. A five-minute catch-up can retry after the
  exact pair/official READY receipt appears; `CANNOT_CONFIRM` is not recorded as
  a successful lane.
- Accepted research-panel publisher evidence only when the child exits 0 with
  A=`READY|PARTIAL` and HK=`READY`; `evidence_status=PARTIAL` is retained.
- Added the canonical A/H order `17:00 -> 17:20 -> 17:30` to the fixed slot
  catalog. A retryable 15:00 failure cannot starve an exact hourly slot or the
  exact 17:00/17:20 research-panel producer; the dependent 17:30 evidence
  node remains ordered catch-up after both producer lanes.
- Added deterministic scheduler/runtime-graph LaunchAgent plist generators and
  the V3.5 producer-to-receipt-to-pointer-to-API-to-UI code graph.

## Verification

Focused command (candidate worktree, App Support Python, no cache writes):

```text
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=<candidate> TMPDIR=<Documents test root> \
  <App Support v3.5-mac Python> -m pytest -p no:cacheprovider -q \
  --basetemp=<Documents test root>/scheduler-retry-green2 \
  tests/test_scheduler_workload_integration.py \
  tests/test_launchagent_schedule.py \
  tests/test_macos_scheduler_hourly_catchup.py \
  tests/test_hk_scheduler_python_forwarding.py \
  tests/test_runtime_graph_topology_contract.py
```

Result: `64 passed` (scheduler/workload, LaunchAgent, fairness/catch-up,
  forwarding, topology and 19-node regression).

The upstream/data-boundary regression group also passed: `83 passed`
(WeChat retry/sync, Review Core natural/wrapper, research-panel evidence and
  runtime-graph tests). The new TDD checks were RED before implementation and
  GREEN after: the explicit plist-root binding, chronological 17:00/17:10/17:20/17:30
  order, and 17:00/17:20 fairness checks.

The topology contract was regenerated with the existing deterministic
`infrastructure.runtime_graph.v35_topology.write_v35_topology` generator after
the workload catalog changed; its byte-stability test is green.

The broader legacy catalog/governance regression was also sampled separately:
`23 passed, 19 failed`. Those failures are outside this bounded scheduler
batch (old catalog/governance hashes and assumptions, plus missing candidate
`.runtime/evidence/phase0` inputs); no such baseline files were rewritten.

## CANNOT_CONFIRM / intentionally not done

- No formal `launchctl bootstrap`, install, service restart, or 8873 deployment
  was performed.
- Formal current/latest pointers and natural receipts are therefore
  `CANNOT_CONFIRM`.
- The exact WeChat URL/pair producer remains the legacy owner; the scheduler
  does not claim to collect it.
- Review Core 20:25 acquisition remains a separate owner.
- The Documents-only Review Core canary for `20260821 -> 20260824` reached
  official exit 0 but adapter exit 2 / `CANNOT_CONFIRM`: fupan was `PARTIAL`
  with 54 rows and `DAILY_VIDEO_NOT_LOCKED`, HK close was `PARTIAL` with eight
  missing shared stage roles (`EVIDENCE_GAP`), and Stage7 was
  `CANNOT_CONFIRM` with 0 rows (`no latest run for 20260821 /
  A_SHARE_1MIN_STAGE_1445_1500`). The first symlinked package path was
  rejected; the resolved immutable release package root passed path checks.
  This confirms the Stage Center/Review Core producer-consumer split and is
  not a READY result.
- Stage7 exact raw19 normalized source is still `CANNOT_CONFIRM`; no summary CSV
  adapter was used to fabricate it.
- Formal preflight proved the existing research-panel producer label and exact
  canonical times (A 17:00, HK 17:20); the receipts were current through
  20260821. A natural candidate-scheduler run remains `CANNOT_CONFIRM` because
  this batch did not deploy or supersede the existing 60-second label. Formal
  installation must replace/disable that label before enabling the two new
  producer lanes; otherwise dual producers are forbidden.

## Superseded evidence roots

The following were read-only/evidence-only and are not active integration roots:

```text
/Users/lexi/Documents/Codex/2026-08-13/v35-stage-selection-20260813
/Users/lexi/Documents/Codex/2026-08-13/v35-stage-selection-finance-localize-20260817
/Users/lexi/Documents/Codex/2026-08-13/v35-stage-selection-hourly-20260817
/Users/lexi/Documents/Codex/2026-08-13/v35-stage-selection-publish-chain-repair-20260819
/Users/lexi/Documents/Codex/2026-08-13/v35-stage-selection-research-depth-20260817
/Users/lexi/Documents/Codex/2026-08-13/v35-stage-selection-research-quality-retry-20260817
/Users/lexi/Documents/Codex/2026-08-13/v35-019ff6cd
```

Safety remains closed: `production_allowed=false`, `buy_gate_updated=false`,
`orders_sent=false`.
