# A-share preselection source repair — 2026-10-08

This is a bounded change snapshot, not a standalone application or a deployment receipt. It fixes the preselection API ignoring the configured source root, which made existing target-date A-share pools appear empty.

## Scope and identity

- Canonical source: v4_app; local baseline commit 55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054.
- The workspace already contained other edits. This batch preserves them; the exact before/after file hashes below define this change.
- The actual API baseline during initial preparation was hk-research-calendar-all-r1-20261007-api. Its monolithic preselection domain already supports the resolver; the canonical domain uses a scoped facade around the existing split implementation.
- Runtime entry remains apps.api.v35_api.run on the existing loopback service. No dependency or launcher change is required by the source fix. Candidate validation used the existing runtime Python 3.14.6.
- No source pool was regenerated or copied into another authoritative root. A/HK pools, exact dates, provenance validation, and trading safety boundaries remain separate.

## File hashes (SHA-256)

| File | Before | After |
|---|---|---|
| apps/api/v35_api/app.py | 90a2bf6390c6c0e219aa3d9bb22bc3b3630ecb2d447df494ae69425933424ed7 | 435dcedd3beb43bf4a0ccb35ff6fc033ba536a940990c36f5f23358f5492b590 |
| domains/preselection.py | 3d35e4274c564b826c248367e5bef6f24409b742966723ebeb5f60b726b7f106 | f209ceb037515586883dc669d830fb44afcf778b67971951bde69c5eab8b67a0 |
| tests/test_preselection_source_root_20261008.py | absent | 46330d42709005822e381c5566d7097cc54cc841193bee738fca151b9a8af5ff |

Existing infrastructure/preselection_pool_sources.py and infrastructure/preselection_pool_readers.py were unchanged. Their respective hashes are 23827109688cabbfb50fc4563cd3c1bdb0220fb6246b349a72836dc0e9b02827 and 949b16526e2b55ae23d121ca3909b4d33509483164d1899e65c94aef6d5781c1.

## Independent verification

Canonical review: PASS_WITH_P2_COVERAGE_GAP, no P0/P1 source defects; 7 new tests plus 3 focused regressions passed.
Commands:
- python -m pytest -q tests/test_preselection_source_root_20261008.py
- python -m pytest -q tests/test_preselection_pagination.py tests/test_preselection_slice.py::test_native_store_and_api_enforce_dates_statuses_limits_and_receipts

Before-fix source-only canary returned DATA_BLOCKED_EMPTY. Independent after-fix canary for 20261008 returned PARTIAL_WITH_ROWS, 178 deduplicated A rows and 100 separate HK rows. All 15 copied artifact/manifest/receipt hashes matched. Optional pool gaps remain CANNOT_CONFIRM. Two legacy HK fallback tests fail during fixture creation, before API execution, because historical provenance fields are missing; they are not reported as passed.

Source writer receipt digest: 43e3a859348402eb04851231f20927db8581e1451b8c7da6a7365fef1c49e4ce.
Independent source review digest: d9a0b970a24799368ff9cd5ac0529c811f26b968838b900dd41ebdd2c3e1012c.
Exact batch patch digest: ac5e7322940fb858d09de5d72942b677fe4fdf5a9d6202fec8e169f2d6d2a29a.

## Deployment status at this snapshot

IMPLEMENTED and source TESTED/REVIEWED/isolated BEHAVIOR_VERIFIED are established. DEPLOYED, live API_VERIFIED, and UI_VERIFIED are not established.

The first runtime candidate independently passed the isolated target-date canary. Its cutover plan failed review for a service-recovery gap, and a concurrent manager-workbench release invalidated its frozen active baseline. It must not be activated. Recovery tooling is being corrected and the source fix must be integrated on top of the newer active release, preserving all unrelated changes.

Candidate review digest: e9e37ba5edfd58cd2a8cb0168bcbfadba9912267c0ed8669c7517c8ca017398a.
Stage readiness, PIT/feature exclusion, and natural-slot behavior remain CANNOT_CONFIRM/out of scope.
RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false.

Excluded from this snapshot: credentials, plist/config bindings, raw receipts, complete runtime inventories, market data, business responses, dist, virtual environments, and node_modules.
