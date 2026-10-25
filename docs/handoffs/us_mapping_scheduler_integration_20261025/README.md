# US close scheduler cohort, 2026-10-25

Status: `PREPARED_NOT_ACTIVATED`, Writer handoff only. Independent review, activation,
live API/UI publication and natural-cycle verification remain outstanding.

The r3 scheduler parent contains the older Native/single-day producer path. This
candidate overlays the twelve exact files in `COHORT.json` with existing accepted
modern US source. No selector implementation or policy was changed by this batch.
The independent US market-digest collector remains the sole collector.

## Build boundary

Source branch: `codex/us-mapping-scheduler-cohort-20261025`; baseline local commit
`46c5e7dd759b6d762caf0aa275dbc9ba79bdd9ec`, tree
`ef4d31294cc7dd7e6ee023970e537e28d25ed410` (same tree as remote
`99fa4c11e284c7028501470a5e4c90d0d6185958`).

The authoritative parent is the outer r3 release manifest SHA
`70aa9cc0a4165471bef3c08ec96b53e2a417646042487b7a864c12b7054a1b2e`;
the inherited manifest inside `app` is preserved as an ordinary parent file.

`prepare_candidate.py` reuses the existing exact-parent overlay pattern and the
retained r6 release inventory primitive, pinned by SHA. The general API builder
requires a live API-role binding and cannot build this scheduler parent directly.
The helper creates only the fixed, absent candidate directory and refuses reuse.
It preserves all 996 canonical parent entries, including directory modes, except
the twelve declared overlays (nine replacements and three additions).

The controller accepted an exact exception for seven preexisting noncanonical
generated-cache entries: two directories and five CPython bytecode files. Their
paths and SHA/modes are recorded individually in `COHORT.json` and the candidate
manifest; only those entries are omitted from the new candidate. Parent bytes are
never deleted or modified. Any canonical drift or an unlisted extra stops build.
The QFQ source remains `7ce737550d855dd9e95bc62ebef2209bfc1c4b2bbe70f16cb51b75688342f445`;
daemon, workload catalog, source bindings, store and every other canonical entry
remain byte/mode identical to r3.

Build with the absolute PANEL_PYTHON, `-B`, and `PYTHONDONTWRITEBYTECODE=1`:

```sh
"$PANEL_PYTHON" -B docs/handoffs/us_mapping_scheduler_integration_20261025/prepare_candidate.py
```

## Bounded acceptance

Local evidence lives under the frozen task's `runtime-integration-r1` directory,
outside this sync artifact. The source test file is
`tests/manager_workbench/runtime/test_us_mapping_release_closure.py`.

Seven targeted cases passed across bounded invocations: candidate own-module
imports; read-only Native source comparison; actual Hook/handoff/service/loader/
Native/engine/store flow; both same-stage lane orders; concurrent publication;
and engine-version cache invalidation/reuse. The actual engine ran exactly once,
with actual Native input pre-frozen before invocation. Neither the original saved
LOAD_INPUTS nor a direct sorting function replaced the Native loader.

The real Native batch used by the service is
`8faad67673e5d724d36d6acb30067c4daf04f5773bce1cbc3466265860a8e333`.
Its exact records SHA is
`b4fbf97df063217e67be3db66268a47a334c7453660da1af08bcb73e01beed4b`;
source quotes, references and cutoff remain the original US23 source. A synthetic
old lane checkpoint without selection and the old consumed handoff cursor cannot
suppress the versioned execution. The isolated saved run is
`2b1f29523eb34586bf6ba427783e7a41`, with product SHA
`2d1d687d332a6b4f574a42e89ea3ce420ac399da652310ad4b0775e8ad06b5d9`.

Readback: focus 10, eligible 87, capped 77, not triggered 504, pending 79;
strict reference selected 0, rejected 449, pending 221. All 701 old stocks are
accounted for: 449 rejected, 221 pending, 31 outside the current candidate set.
The saved job is honestly `PARTIAL` because financial evidence remains incomplete.
The 670 candidates and the entire focus object (symbols/ranks/reasons) exactly
match the prior frozen-input accepted output. Strict results differ only in a
more specific missing-input reason:
`HK_HISTORY_OWNER_IDENTITY_PENDING` becomes `HK_PANEL_EXACT_DATE_BINDING_MISSING`;
strict decisions/counts do not change. Engine identity also changes as expected.

The Native comparison to the old saved batch is separate: modern strict/single-
day payloads and three source-fact fields (`current_validity`, `direction`,
`primary_theme`) are added. After comparison-only removal of these exact fields,
all 1,051 records match; evidence references match without normalization. The
original frozen input and old snapshot retain their original SHA.

Two failed test fixtures are retained locally: an immutable checkpoint seeded at
the wrong execution key, and an observer incorrectly assuming the existing loader
only iterates the requested lane. Both failed before any engine invocation; fixes
were limited to the test observer/fixture. Earlier inventory guard failures also
remain recorded. No business source was changed in response to these failures.

An additional no-engine smoke used `-S`, the actual scheduler site-packages,
candidate cwd/PYTHONPATH, and default `WorkbenchHook.from_environment(start=False)`.
It constructed the real Native/service role with 29 own-source modules, without a
running hook thread. PANEL_PYTHON and the parent's observed scheduler binary have
the same SHA `839b22560e27f02d716009a2d6bcd377cb6197ff70888787e3097919120e32aa`.
The smoke locally disables capture and CLI capability probes; it does not certify
announcement model execution or activate the daemon.

## Activation handoff, not executed

After independent PASS, the controller must refresh the healthy owner and idle
workload identity immediately before activation. Reuse the existing scheduler
role and rollback record. Point its launcher/cwd, `V35_APP_ROOT`, release ID and
outer manifest path/SHA to this candidate. Make candidate app and candidate
upstreams precede older package roots in effective PYTHONPATH; retain the existing
runtime binary/site-packages and source owner configuration. Preserve the pinned
A-share/QFQ owner references and all other role environment bytes unless the
controller explicitly freezes a necessary path rebinding. The copied daemon and
catalog require no enablement change. Keep the separate collector untouched.

The next processing of this US23 close is a reprocessing event. It is not proof of
two natural cycles. Do not publish this local canary or create another publisher.
The API role is separate and was not changed by this batch.

NOT_RUN: commit/push, deployment/service actions, official state writes, live
API/UI publication, new capture, labels, models, 87-case full suite, A-share
37/148/cache validation, and natural-cycle/economic-effect verification.
`RESEARCH_ONLY=true`, `production_allowed=false`, `buy_gate_updated=false`,
`orders_sent=false` throughout.
