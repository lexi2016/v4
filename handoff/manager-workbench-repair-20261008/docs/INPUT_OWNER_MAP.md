# Inputs diagnosis — frozen source only

**本文保留修复前的定位记录，F1–F4 的行号和行为均指冻结前像，不是最终候选的现状。** 最终修改与剩余条件见 [README](../README.md)、[源码前后 SHA](../source_manifest.json)、[输入合同回归](../after/tests/test_manager_input_contracts_20261008.py) 和 [最终测试结果](../evidence/results.json)。下面列出的实质缺口仍须按现场证据验收。

Repository: `lexi2016/v4`  
Commit: `0fd5eb374cb155232ed003d5fc4d0d3594252491`  
Scope: manager Connect eligibility, canonical D-1 Top100 consumer, HK0.2 screen session, volume units.  
Boundary: source reads and synthetic offline reproductions only. No Mac access, raw market or account data, remote writes, scheduler action, deployment, or Stage source edits.

The frozen source reads were checked against their remote Git blob IDs byte for byte. The manager source SHA values match the supplied source map for workspace_plan.py, connect_selection.py, and connect_capture_adapter.py. This package records the overall [source comparison](../evidence/source_identity_comparison.json) and exact changed-file origins in [source_manifest.json](../source_manifest.json).

## Deterministic findings

### F1 — a D-1 capture passes the formal target-day Connect filter

- `v4/manager_research/connect_selection.py:74-83`: on failure of target-day HK_UNIVERSE_V2, read_scope reads a previous-session capture and returns it directly with status OWNER_VERIFIED.
- `connect_selection.py:106-128`: _scope_error accepts EXACT_PREVIOUS_FULL_SESSION_CAPTURED_CONNECT_CODES as a successful formal scope.
- `connect_selection.py:136-164`: filter_cards accepts those symbols. The output label says VERIFIED_PREVIOUS_FULL_SESSION_CONNECT_MEMBERSHIP, so the source itself is distinguished; the consumer nevertheless lets it through the formal target-day gate.
- `v4/manager_research/workspace.py:508-518,579,628` (20261008 API handoff): that scope is consumed by formal material-card filtering, gate_workspace, and announcement-lane filtering.
- Baseline reproduction built an internally linked synthetic D-1 scope with no target-day V2 and the actual filter accepted one card. The final [input regressions](../after/tests/test_manager_input_contracts_20261008.py) require that the target gate reject this substitution.

Minimal correction: read_scope must retain target-day status CANNOT_CONFIRM and target failure diagnostic when V2 is absent; attach the independently verified D-1 capture as a separate diagnostic child. _scope_error must only allow TARGET_DATE_CAPTURED_HK_CONNECT_AUTHORITY_V2 for formal eligibility. Preserve read_d1_scope as a separately labelled read-only artifact contract.

A second direct qualification declaration exists in `workspace_plan.py:1209-1213`: a screen row gets VERIFIED_TARGET_UNIVERSE from the panel date security master without consuming the target-day V2. This is not target-day eligibility evidence and must be represented as source-universe membership only.

### F2 — the consumer loses the panel publication time when reading the daily supplement

- `workspace_plan.py:300-315`: the real panel witness returns `panel_available_at=manifest.manifest_prepared_at`.
- `workspace_plan.py:576-598`: the daily-supplement adapter passes `expected_panel.manifest_prepared_at=panel.get('manifest_prepared_at')`, but the witness has no such field.
- `upstreams/v3_shared_data/shared_data/hk_daily_supplement.py:489-495`: the existing owner requires exact pointer identity equality, including manifest_prepared_at.
- The existing supplement producer requires that parent time to be present and valid (`hk_daily_supplement.py:273-278`), so a normal non-null parent time cannot equal the adapter's None.
- Reproduction: the actual adapter receives a witness with panel_available_at and transmits None for expected manifest_prepared_at.

Minimal correction: map the adapter's expected manifest_prepared_at from the verified witness's panel_available_at (or retain a clearly named alias in the witness). Do not loosen the owner identity check and do not modify the producer.

This is a reproducible consumer incompatibility. The live summary's missing-panel errors do not by themselves prove this was the active runtime failure; an exact panel witness must first exist to reach this call.

### F3 — unknown volume units can yield a strict research candidate

- `workspace_plan.py:1121-1137`: numeric ratio and Boolean gate are calculated without a unit/scale proof requirement.
- `workspace_plan.py:1180-1185`: complete numeric history can yield history_status KNOWN, strict=True, or near=True.
- `workspace_plan.py:1261-1262`: the same row emits volume_unit_status NOT_PROVEN and either scale 1 or None.
- `workspace_plan.py:1318-1327`: the supplement authority metadata also preserves NOT_PROVEN.
- `hk_daily_supplement.py:191-209,591-594`: original category-4 bars explicitly carry native trade, scale_applied 1, volume_unit None, NOT_PROVEN.
- The code already avoids mixing target volume and prior-five volumes from different selected paths (`workspace_plan.py:919-923,1048-1050,1063-1068`). This useful constraint is not sufficient to attest identical units/scales across inherited panel history.
- Reproduction with synthetic exact-calendar rows at price 80 / prior60 high 100 and current volume 150 / prior-five mean 100: actual screen returns READY, volume flag True, strict True, and volume_unit_status NOT_PROVEN.

Minimal correction: preserve the numeric observations but mark the quantity gate unresolved until the existing owner's manifest/attestation proves the native field, unit, scale, source identity, all six session bindings, and cross-source consistency when applicable. Add an explicit unit-evidence gap; prevent unresolved volume from entering strict, near, or confirmed exclusion. Keep the price threshold 0.80 and volume threshold 1.5 exactly. No guessed lots-to-shares conversion, turnover/price inference, or bare metadata string can supply proof.

The present frozen owner contract contains no authoritative positive unit attestation. A patch can correctly fail closed and expose the missing evidence; it cannot honestly create an accepted real-volume candidate.

### F4 — plan date and completed screen date are not separately modelled for same-day post-close review

- `workspace_plan.py:18-98`: plan_context deliberately caps market_session below target date, takes the latest completed FULL HK securities session, and labels all target-day times after open AS_OF_RESEARCH_REVIEW.
- `workspace.py:431-432,532-538`: the same plan context feeds close references and the rebound screen.
- This is valid for a next-session plan, including a plan created on the previous evening. It does not provide a separate same-day post-close screen contract.
- Do not change plan_context.market_session globally: the prior close reference and connect_capture_adapter rely on `source_date < target_date`.

Actual frozen-calendar reproduction:

| Target | HK cutoff | Current market_session | Meaning |
|---|---|---|---|
| 20261008 | 2026-10-08 08:00 | 20261007 | Correct latest completed full session for pre-open |
| 20261008 | 2026-10-08 16:09 | 20261007 | Target session is not complete under the native calendar |
| 20261008 | 2026-10-08 16:10 or 17:00 | 20261007 | Always D-1; no separate same-day post-close screen phase |
| 20261009 | 2026-10-08 17:00 | 20261008 | Correct next-session plan after D closes |
| 20261005 | 2026-10-05 08:00 | 20261002 | HK calendar, not the closed Connect/A-share calendar |

The pinned native calendar defines HK full close as 16:10 and half-day close as 12:10. The existing price-screen baseline and prior-five volume history use FULL_TRADING_DAY; prior60 highs include full and half HK sessions as currently implemented. Preserve that approved distinction.

Minimal correction: add a distinct screen-session resolver/context. Pre-open/intraday target D consumes the previous completed full HK session; post-close selection for D can consume D only after its native close and only once the exact owner panel was available at the research cutoff. A next-day plan target T retains plan_context's previous-session mapping. Bind selection target, plan target, panel session, phase, cutoff, and calendar SHA explicitly. A missing completed-session panel remains an input gap; it is not evidence that a producer failed. The requested UI date=20261007 and plan_date=20261008 should retain their separate meanings.

## The actual canonical D-1 Top100 Stage consumer

The three contracts are separate:

| Contract | Owner/read path | Date/identity |
|---|---|---|
| Target-day Connect qualification | `domains.manager_research_evidence.read_universe_evidence(require_v2=True)` → pinned `stage_center.hk_universe_preflight` pure V2 contract | Exact target/effective/trade/source date; original capture, artifact, manifest, receipt, current, publication SHA/run; acquired and available before cutoff |
| Previous full-session Connect capture | `connect_capture_adapter.read_d1_scope` | Prior full session; research-panel receipt, original capture/manifest, security-master trio, and exact successful dispatch-finish availability upper bound |
| Canonical D-1 Top100 Stage pool | `stage_center.runner._build_hk_stage_binding` / `_build_hk_d1_binding` / `_validate_hk_d1` → `PreselectionSourceResolver.read_pool_snapshot(D,'hkconnect_d1_top100')` | Exact target-day physical preselection pool artifact/manifest/receipt trio, 100 unique rows, STRICT_0_2_READY, SHARED_VERIFIED_HK_0_2, v3_shared_hk_0_2_consumer_v1, prob_active model when declared, run and byte SHA |

Concrete Stage source map:

1. `stage_center/runner.py:920+` `_build_hk_stage_binding` resolves and binds the pool.
2. `stage_center/_runner_parts/hk_input_validation.py:31-243` `__validate_hk_d1_body` reads the exact trio through PreselectionSourceResolver and checks producer/status/dates/model/100 unique rows and source identity stability.
3. `hk_input_validation.py:166-221` independently derives the previous HK securities price-signal date and previous Connect eligibility-source date. When they differ, it requires `v4.hk_d1_split_date_provenance.v1`, both date identities, eligibility run/artifact/captured_at, and D-1 run/artifact/manifest/receipt SHA links.
4. `hk_input_validation.py:287-313` produces a `HK_CONNECT_D1_TOP100` StageUniverseBinding.
5. `stage_center/_runner_parts/slot_execution.py:487-506` calls `_attach_hk_authority` for the HK selection input.
6. `stage_center/_runner_parts/hk_candidate_authority.py:6-38,75-178` consumes D-1 rows, overlays only authoritative metadata/static lanes, and records the D-1 JSON SHA. Live-minute assertions require their own capture; a full-market quote row is not a D-1 static lane.

The D-1 capture adapter is not used in this Stage pool chain. No US relation input can supply any of these qualification or Stage membership identities.

The 20261007 R2 Stage handoff is explicitly an inactive candidate. Its exact-target 100/100 readback confirms membership only; PIT and natural-slot outcomes remain unverified. Its 20260924 and 20260930 replay was blocked before selection by HK_ACTIVE_SNAPSHOT_EVIDENCE_MISSING. Preserve this boundary and do not modify Stage.

## 20261007 calendar / daily-chain boundary

The 20261007 all-research calendar delta changes eligible research workloads and daily_materialize from A_OR_HK_CONNECT_TRADE_DAY to A_OR_HK_SECURITIES_TRADE_DAY and adds the matching runtime graph calendar mapping. It does not add volume-unit evidence or change the manager's plan-context date contract.

The original daily supplement already requests target plus five immediately preceding FULL HK securities sessions. It rejects a non-full target session. It is a six-bar native category-4 sidecar bound to one exact panel/master revision. The frozen file still records NOT_PROVEN.

The 20261007 Stage handoff documents a separate open P1: exact-date security-master preflight occurs before TDX day-file/panel refresh required to provide its date-specific inputs, leaving a bootstrap dependency. This is handoff evidence, not independently observed current producer failure.

## Suggested focused regression set

1. Target V2 passes formal filter; internally valid prior-session capture does not; missing V2 preserves the exact original rejection reason.
2. Screen row built from D-1 master has no target-day eligibility claim.
3. Actual panel witness + actual daily-supplement reader preserves publication timestamp identity; reject mismatch and publication after cutoff.
4. Pre-open, 16:09, native 16:10 boundary, next-day plan, weekend/HK-only trading day; no use of unfinished session.
5. Unknown unit/scale → unresolved volume, zero strict/near, no confirmed two-gate exclusion; numeric ratio remains explicitly unverified.
6. Positive unit evidence path only when original owner contract and exact bound hashes exist; no fixture may elevate actual runtime evidence.
7. Price equality at 80% and proven-volume equality at 1.5 remain inclusive; missing/duplicate session and zero prior-five mean remain unresolved.
8. Same-source all-six-volume constraint remains intact; no mixing panel target with category-4 history.

## Cannot be proved in this environment

Current R3 loaded file fingerprints; active scheduler dispatch object; actual authority roots and immutable manifests; target-day V2 existence; exact-date panel/master/supplement availability; real volume units/scales; actual D-1 Top100 run consumed by Stage; same-day/next-day natural slot behavior; or API/UI reloaded results. Those require the existing Mac owner/read-only runtime receipts and an actual natural run, not source inspection or synthetic tests.

The original diagnosis was read-only. Its minimal corrections were subsequently implemented and checked by the [red regressions](../evidence/tests/input_contract_red.log) and [final backend run](../evidence/tests/backend_final.log). Positive live volume attestation and actual Mac input availability are still unverified.

