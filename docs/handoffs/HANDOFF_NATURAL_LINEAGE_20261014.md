# Natural dispatch timing and owner lineage repair — 2026-10-14

Canonical source: `/Users/lexi/Desktop/学习/v4_app`. GitHub base: `f282b54a4ec08c890f9317b36df556ab393d5d70` (private `lexi2016/v4`). Scope: scheduler timing, existing runner receipt writer, read-only execution projection, stage page, targeted tests. No subagents per user; independent REVIEWED / BEHAVIOR_VERIFIED: NOT_RUN.

The exact-second equality classified the 10:30:02.499705 dispatch as LATE_CATCHUP_REPLAY. Start diagnostics recorded 10:30:05.313517. launchd uses minute resolution. The scheduler now treats the scheduled minute after the exact cutoff as DUE; next-minute invocation remains late, and pre-cutoff/historical rules remain unchanged. This is a dispatch classification, not relaxation of market-data cutoff or PIT gates.

The existing writer did not produce the owner history and selection-trio binding fields its reader expected. It now writes the actual UTC owner-write clock, verifies current referenced SelectionStore trios, stores byte and canonical SHA values, and writes an exclusive content-addressed owner copy before the current receipt. Reader history bounds now match the existing SafeRoot receipt bound. Owner-copy/trio binding remains distinct from independent execution/natural attestation. The page now renders API execution_evidence when stage_lineage is absent and displays exact-slot observed clocks and evidence gaps.

Deployed Stage: `natural-lineage-stage-20261014-r1`, manifest `3f8f837b30c723477325415289070ce477722133ffba86b3600b06b88c067260`.
Deployed API/UI: `natural-lineage-api-20261014-r2`, manifest `f4db327caf73e384eec2f0e1ba22b7cb16b60c9f8bb3361a7fe589c61462935a`.
Runtime roots: `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/<release>/app`.
Runtime releases clone their currently active parents. Stage scheduler's existing recovery flag and receipt writer's scoped-market merge were preserved with exact local deltas. API page/readers matched the canonical pre-edit bytes. Build used existing node_modules temporarily; no dependency change. The private branch is a scoped handoff, not a standalone runtime image.

Validation:
- Reproduction: same-minute 2.499705-second and 59.999999-second cases failed before fix.
- Canonical: `.venv/bin/python -m pytest -q tests/test_natural_lineage_20261014.py tests/test_hk_display_receipt_20261014.py tests/test_hk_full_pool_ranking_20261014.py tests/test_hk_observation_calendar_20260925.py` — 35 passed (Python 3.14 environment).
- Actual candidate Stage writer/scheduler/SelectionStore plus candidate API reader, production `v3.5-mac/bin/python`, targeted 9 tests — passed. Tests cover >1 MiB owner copy, actual writer, immutable prior copy, SHA tampering, mismatched selection, exact slot diagnostic rejection, and no natural promotion.
- Vite production build — passed. Final local API identity: MANIFEST_EXECUTION_FILES_VERIFIED.
- API and fresh browser: exact 20261014/STAGE_0945_1030; A10/HK10 preserved. 10:30 old receipt SHA and both run IDs unchanged. UI explains legacy mistiming while retaining original raw LATE_CATCHUP_REPLAY and current evidence gaps.

IMPLEMENTED / INTEGRATED / DEPLOYED / API_VERIFIED / UI_VERIFIED. Main-agent regression passed; independent TESTED / REVIEWED / BEHAVIOR_VERIFIED NOT_RUN per no-subagent instruction. NATURAL_SLOT_UNVERIFIED: no new natural slot occurred after deployment. Old receipt lacks owner history/write clock and trio declarations and was not rewritten; execution_verified=false, natural_verified=false retained. No retroactive natural proof was fabricated. Research safety flags remain false for production_allowed, buy_gate_updated, orders_sent; no data recollection or trading changes.

Local receipts: `/Users/lexi/Desktop/学习/agents调试/V4_NATURAL_LINEAGE_20261014` (`SCOPE.json`, before/after SHAs, pytest.txt, runtime-tests.txt, activation*.json, api-final.json, identity-final.json, ui.txt, ui.png). Raw data and responses remain local and are excluded from GitHub.

Canonical source SHA256 (handoff document itself excluded):

| Path | Before | After |
|---|---|---|
| `stage_center/scheduler.py` | `e56651ec7bb481b28e383cb403d60ba48747ddf7426f9fb380f5ae24fc3a37a4` | `ab1924a8c1286369ca83fe13669bf76dd45e149d0574667a19d960150df01322` |
| `stage_center/receipt_lineage.py` | `NEW` | `462abed0bd619ffdcf03736970394bcf9b4dfbda4af743a117d083d74243d3a4` |
| `stage_center/_runner_parts/runner_receipts.py` | `af4322e65f21a4e14cc2680a63a2d93ad9bab855b235c7ef0751704549d986d5` | `4644bc399d333ec30e5311c4528b172cb453d228517325f784f79268f4f4766c` |
| `stage_center/execution_evidence.py` | `f378aaeadc8178e6482f6155095c4947e4c0387f46eec2f2b820f929c53e8a6c` | `b31877907313ab7fa015a37b9423c8267dde298c87b8277f14b22bcdbe61fc03` |
| `apps/web/src/App.vue` | `0e844a9043c3aaf90217dd2a37140dc4c2ab9ee253d973effb86cf4c8d6809a2` | `1b48a1fe966f36adbb0ea71d9572bc8fcbeb3b441867da49c87547b236739dc6` |
| `apps/web/src/app_shell/types.ts` | `09e1755cd4cfd795bc96d8478d5b29a97ea36f53a46b5676d865aeb582ab59c2` | `789c67010b2b919061ff9d48f82fe7769c1e2e6dc08ddc19057c8d5e1afbd890` |
| `tests/test_natural_lineage_20261014.py` | `NEW` | `4c89fcc35482a66f4b0a54809774dcd904aacd7427c55ed759057547b18c6008` |
