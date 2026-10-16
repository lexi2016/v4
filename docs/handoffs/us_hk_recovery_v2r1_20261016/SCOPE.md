# US-HK recovery v2r1 intake and integration

GOAL: Integrate the user-provided complete 667-stock / 1003-relation recovery package into the existing V4 mapping catalog, preserving research closure versus relation validity and all evidence gaps.
WRITER: One Luna Max agent, to be assigned after intake.
REVIEWER: Separate Luna Max read-only reviewer.
ALLOWED_PATHS: This handoff directory; subsequent exact source/runtime delta scope must be frozen before writer dispatch.
FORBIDDEN_PATHS: Trading/BUY logic, A/HK pools, oversold scheduler, Vibe 8910, credentials, unrelated parallel changes, raw archive upload to GitHub.
PASS_SIGNAL: Reconciled input identities and 667/1003 accounting; exact status semantics in existing catalog; independent focused review; API/UI confirmation for deployed delta; scoped private GitHub synchronization and readback.
STOP_RULE: Conflicting source identities, missing mandatory source material, or changed live baseline requires bounded reconciliation; missing financial evidence remains CANNOT_CONFIRM, never fabricated validity.

Input: /Users/lexi/Downloads/US_HK_667_1003_recovery_v2r1_20261016.zip
Bytes: 508906833
SHA256: 48f1124c10ed3440c22910a9125038748c08d673fc3ec543635cc9aae0b344d4
Archive: 3638 entries; 1214430309 uncompressed bytes.
Source: user-provided Google Drive file 1FgIRcS4zJcWuUg1yWXDP0aBTkdAQPOAV.
Downloaded via browser after connector HTTP 413 at its 268435456-byte limit.

Initial live baseline: hk-morning-selection-recovery-20261016-r7; manifest bfde3721184d186e2b92f1747eb9d16219face2dc353e4e0be7de8a31e67ad47; API plist SHA256 2b902b87f17575258c5b483fe38f8cb1c02ab036bc14013adf2a14206cb37924. Recheck under existing release lock before activation.

RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false.

Source candidate scope:
WRITER: mapping_recovery_writer, Luna Max.
ALLOWED_PATHS: v4/manager_workbench/research_data/us_hk_667_recovery_overlay_20261016.json (new immutable derived projection); v4/manager_workbench/us_mapping_catalog.py; tests/manager_workbench/test_us_mapping_catalog.py; apps/web/src/manager-workbench/Workbench.vue (mapping catalog only); apps/web/src/manager-workbench/types.ts (mapping types only); apps/web/src/manager-workbench/__tests__/us_mapping_catalog.spec.ts; this handoff directory (builder, preimages, diff, compact receipts and tests).
Original catalog and old700 overlay are immutable. Existing reviewed history remains separately accessible; no unvalidated status crosswalk. Candidate phase must not touch runtime/services/config/scheduler.
PASS: 1003 processed = 757 closed research + 25 closed excluded + 221 open; 667 snapshot = 649 with edges + 18 without. 782 closure never labeled active/verified mappings. Existing original metadata, safe URL and lazy full-record behavior preserved; old700 historical evidence retained; missing-attachment and PIT/prediction limits visible. Independent fact acceptance remains 0.

Runtime PREPARE phase (parallel with source read-only review): same sole writer mapping_recovery_writer. May write only this handoff runtime/ helper/receipts paths, a new immutable release under /Users/lexi/Library/Application Support/com.lexi.v4.local/releases/us-hk-recovery-v2r1-20261016-rN, and new versioned us-hk-recovery-v2r1 config. Clone current actual API release, apply only approved exact mapping hunks + new overlay + corresponding manager static build. No live activation/plist/service/scheduler mutation in PREPARE. Fresh current release identity and all non-delta bytes must be preserved. Source files frozen under independent review. Runtime candidate must receive independent PASS before activation.

Bounded runtime repair: fix independent Reviewer P2 rollback exception ordering only in this batch runtime activation helper and add focused failure-path tests here. Imported old700 helpers and all candidate app/source/config bytes remain frozen. Detach confirmation failure must not skip atomic restoration of saved original plist; report/retain unknown process identity and rollback errors honestly, never blindly bootstrap a duplicate service. Independent reviewer rerun required before activation.
