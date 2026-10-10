# 2026-10-09 Stage recovery — actual result

A-share 13:00–13:15 was restored to the ordinary 8873 page as an explicitly labeled historical research backfill. The independently verified API matrix now has 10 rows in all seven applicable A-share stages (09:25, 09:30, 09:35, 09:40, 09:45, 13:00, 14:45); 15:45 is not applicable to A shares. These remain PARTIAL_WITH_ROWS, not complete-data or natural-slot acceptance.

HK formal preselection and remaining stages are NOT RESTORED. A retrospective 100-row candidate exists, but the historical security-master capture/PIT provenance remains unverified. The existing TDX query returned no 20261008 rows for 00853/02172/02252 and did not resolve all prior-close gaps. Missing names and field/provenance gaps are preserved. No strict-ready/eligibility flag was fabricated. HK 09:30 retains its earlier 10 observation rows with unverified membership; other HK stage slots remain without formal rows.

## Source and boundaries

Canonical root: `/Users/lexi/Desktop/学习/v4_app`. Frozen handoff parent: `8033b368a2ee1a960480aee655e1d502880fda87`; reviewed source delivery: `63224d83d6458bb589fca89d48a3bd997d2de766`.

The common hourly evidence projector reconstructs source-backed audit diagnostics, without a new date-specific exception or weakened source SHA check. Changes are isolated in this handoff; unrelated workspace modifications and previous branches remain intact.

| File | Before SHA256 | After SHA256 |
| --- | --- | --- |
| domains/research.py | b77cc0d3c9ec36eeee3e6cab207945a783b0352a703efdb5c8e2f7f17966506f | b784915ade13720032732921ebc7f219efa420452cf8cd57d42b6e3bad6c9860 |
| tests/test_stage_historical_research_projection.py | d787131197385fe44de517c011203e0892530b8a7dd12f3ac0221a3a253b3b79 | ea51d1054c30b2db8f22fac67080e3e07b382b42979e8ca76055826998670e0a |
| tests/test_stage_research_context_v4.py | e65ef87dc31bfa69a929ecf8dccd05fb731c574d0c6c16ed360621df0d8438a4 | 5985bdf2d2ebe294a94a68d23249808ee3954b6a5517b6264bcf863b143a72cd |

## Actual historical publication

Original R3 Stage runner generated backfill `67f131d7732641659c89837dbfd7ea16`, selection run `run-2e40cc6a40d0e6d3c65d8f72`, for exact date 20261009 and STAGE_1300_1315. A: 10 selected rows, 206/216 source coverage, known research/morning-news evidence gaps retained. The corrected candidate morning-news root removed a false missing-date diagnostic; no absent stage evidence was synthesized.

Only this run's raw, receipts, and selection namespaces were added to the existing V4 state roots. Raw and receipts were published first, then selection atomically with no-overwrite rename. Existing locks cover cooperating normal-root writers only; optimistic same-key checks and exact-run API verification detect conflicting historical publications. Run-specific quarantine is the rollback boundary. The standard selection pointer and all 51 pre-existing A result files are unchanged.

The running API remains PID 10321 at 127.0.0.1:8873, rooted at `V4_MANAGER_OWNER_INPUT_INTEGRATION_MAC_20261010_R1/candidate/stage_r4_manager_r2_owner_input_r1_fused_r1/app`. Its source hashes are recorded in the independent final receipt. No application release, service, plist, scheduler, Manager or 8910 change was performed in this recovery publication.

## Verification

- IMPLEMENTED / TESTED / REVIEWED: common A1300 projection; independent five focused tests passed (Python 3.14.6, pytest 9.1.1; exact commands in projection review). Full suite NOT_RERUN for the later data-only publication.
- BEHAVIOR_VERIFIED: independent native candidate read and live read preserve partial research status and exact row/order/source/receipt identity.
- INTEGRATED / DEPLOYED: only the reviewed historical backfill artifacts were published. Application source deployment: NOT_PERFORMED.
- API_VERIFIED: ordinary `/api/v3/workbench/stage?date=20261009&stage=STAGE_1300_1315&limit=50` returns exact backfill, 10 A rows, verified runner receipt; independent eight-stage matrix captured.
- UI_VERIFIED: parent explicitly reloaded ordinary date/stage page, saw A 10 rows, BACKFILL, verified receipt, 206/216 coverage and HK missingness. Local screenshot: `coordination/A1300_RECOVERY_UI_20261010.png` under the R4 evidence root.
- NATURAL_SLOT_UNVERIFIED. This is historical replay, not proof of future scheduler behavior.

Publication used the existing runtime Python with `promote_a1300.py --dry-run` then `--execute`. The first dry-run probe had a precheck bug and failed before live writes; corrected probe passed absent-target and existing-target preservation checks using macOS renameatx_np(RENAME_EXCL). Execute exited 0. The independent final reviewer checked promoted bytes/modes, runtime identity, unchanged baseline, same-key uniqueness and current API semantics.

Final independent receipt SHA256: `555a7071a866b419b8a37b416ffc4b8a778ab062006e4c15242fe239444ee3cd`.
Execution receipt SHA256: `1c5f1d8610f1095081553afc420dbde21ebdd962145c8f74db835ae9b3fa2857`.
Runner receipt SHA256: `03caa6aa0d552e6339fd8dbe9ddc5949dab2694f55659275503508efd4eb0fbc`.

RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false. Raw market data, full API responses/plans, credentials, dependencies and builds are excluded from this GitHub handoff. Complete requested HK recovery remains blocked by historical data/provenance gaps.
