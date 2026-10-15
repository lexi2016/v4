# HK history owner migration and read canary

Phase 2 review status: `REVIEWED` / `BEHAVIOR_VERIFIED` for the frozen candidate data-owner, exact package move, and isolated API behavior. This does not validate raw-value semantics or activate scoring; the live 8873 route remains `NOT_DEPLOYED`.

```text
GOAL: Keep the existing C-owned HK panel authoritative on overlapping keys and make the pinned B raw daily history available only for B-only keys through a bounded, read-only, source-tagged view. Relocate exactly the two authorized old packages with same-device renames and preserve their original paths as absolute symlinks. Do not create another Parquet producer or enable scoring.
WRITER: /root/migration_writer, sole Luna Max writer for this batch.
REVIEWER: Independent Luna Max reviewer, read-only.
ALLOWED_PATHS:
  - v4/hk_research_history.py
  - tests/test_hk_research_history.py
  - v4/manager_workbench/api.py (additive /hk-history route only)
  - docs/handoffs/hk_data_consolidation_20261015/SCOPE.md
  - docs/handoffs/hk_data_consolidation_20261015/reconciliation.json (existing phase 1 receipt; read only)
  - docs/handoffs/hk_data_consolidation_20261015/MOVE_RECEIPT.json
  - docs/handoffs/hk_data_consolidation_20261015/PHASE2_RECEIPT.json
  - C owner metadata: .../assets/hk_0_2/research_history.json (exclusive create)
  - The exact two audited package directories below, moved by same-device rename to the exact quarantine paths below; old paths become absolute symlinks.
FORBIDDEN_PATHS:
  - All other existing source, config, data, runtime, and application paths.
  - Reading/parsing A feature or label contents, or B operator feature/label contents; their SHA/size identities are metadata only.
  - Any changes to the C panel pointer, active panel/manifest, model state, scheduler, plist, database, score, or BUY state.
  - C panel rewrite, merged Parquet, alternate owner, second producer, release/staging copy, API restart/reload, deployment, or service stop.
PASS_SIGNAL: Eight focused fixture/API tests pass; both moved packages retain every pinned file SHA/size/inode and directory inode, original paths resolve through absolute symlinks, C owner descriptor loads the dynamic active C pointer/manifest/panel and verifies B/C source hashes, the three frozen real-key canaries pass both the direct adapter and an isolated TestClient, and the C pointer/manifest/panel/model plus relevant API and HK scheduler plist identities match their pinned baselines. The transaction's aggregate 16-plist comparison was observed equal, but its per-file map was not retained; all-16 identity acceptance remains CANNOT_CONFIRM. Independent Phase 2 review and target-behavior verification passed for the frozen candidate scope; the live 8873 API remains NOT_DEPLOYED.
STOP_RULE: Stop after archiving the independent review receipt. Do not deploy, reload, broaden the migration, change live pointers, or interpret raw values as unit-, adjustment-, currency-, or PIT-safe.
```

## Frozen sources and exact relocation

The original B raw daily file is now reached through its compatibility alias and physically resides at the quarantine target below. Its original SHA, byte size, row count, and columns remain pinned. The C source is resolved on every query through the existing `hk_0_2/panel_latest.json` pointer and the manifest it names; the descriptor does not freeze a C panel path or SHA.

| ID | Role | Original/alias path | Current data path or resolution | SHA256 | Bytes | Rows |
| --- | --- | --- | --- | --- | ---: | ---: |
| B | Raw daily history: `code`, `date`, OHLC, `trade`, `amount` | `/Users/lexi/Desktop/学习/数据/港股/hk_connect_research_panels/versions/20260912/20260912_operator_d1_overnight` | `/Users/lexi/Desktop/待删除/港股统一_20261015_旧面板原件/20260912_operator_d1_overnight/daily_bars.parquet` | `17f5b62b6ec0264d48b6ee66ce0cd31aa8c1deb661e3e765b90b780add2eb230` | 17,142,047 | 1,014,835 |
| C | Existing 32-column HK daily panel; dynamic current owner | n/a | `assets/hk_0_2/panel_latest.json` → current manifest → `panel_relative` | Current panel SHA is read from the active manifest and verified per query | dynamic | dynamic |

The A package and B operator package were each moved as one directory by same-device `os.rename`; all ten regular files retain their original sizes, SHA256 values, device/inode identities, and both package directory inode identities. The original package locations are absolute symlinks to those moved directories. The move receipt records all identities. No copy or deletion was performed.

The A feature and label plus B operator-feature and operator-label files appear only as metadata references in the C owner descriptor. No feature/label Parquet schema or rows were parsed; file size and SHA256 were used only to verify identity. Label references explicitly record `label_values_read=false`. The C active panel pointer, its current manifest and panel, and `model_latest.json` have individual before/after SHA evidence in `MOVE_RECEIPT.json`. The active API and HK scheduler plists match their independently supplied baseline SHAs in the receipt. The writer observed the aggregate 16-plist before/after hash maps equal, but did not retain the per-file map; unchanged identity for the other plists is CANNOT_CONFIRM.

## Adapter and API contract

- Normalize only the join key to `HK.00001` plus `YYYYMMDD`; reject malformed keys and fail on duplicate normalized keys.
- Classify every valid B row exactly once as `B-only`, `raw_matching_overlap`, or `raw_conflicting_overlap`; malformed B keys count as `invalid_key` and fail acceptance.
- C owns all overlapping keys. Preserve each C row and add a B row only when its normalized key is absent from C. Preserve raw source fields, source ID, and source SHA; do not rescale or rename `trade` or `amount`.
- Compare only the six raw numeric fields using the frozen audit tolerance (`rtol=1e-6`, `atol=1e-6`). Numeric agreement does not establish source quality, units, adjustment basis, currency basis, or point-in-time safety.
- Return units, adjustment basis, currency basis, and PIT safety as `UNKNOWN`. Every result remains `research_only=true` and `scoring_allowed=false`.
- The additive candidate route is `/api/v4/manager-workbench/hk-history`. It requires one five-digit `HK.` symbol, calendar `YYYYMMDD` start/end dates, nonnegative offset, and limit 1–200. It uses the existing `service.config.shared_root/assets/hk_0_2` owner and response sanitizers. The route was exercised only in an isolated FastAPI `TestClient`; no active runtime was reloaded or deployed.
- The report exports no market rows. Reconciliation outputs contain counts, source identities, normalized canary keys, and row digests only.

## Frozen reconciliation and phase 2 canaries

The phase 1 full partition receipt remains pinned in `reconciliation.json`; its source SHA checks, exact-once classification, duplicate/invalid checks, field-mismatch counts, and partition counts passed before the move. The move preserves those same bytes and inodes. Counts were not recomputed by rereading the full partition during phase 2.

Frozen partition: B rows `1,014,835`; common keys `437,024` (`406,683` raw matches and `30,341` raw conflicts); B-only `577,811`; C-only `23,073`; union `1,037,908`; duplicates and invalid keys `0`. The strict diagnostic `B.amount > 0 AND B.trade > 0 AND C.amount == 0 AND C.trade == 0` is 8 rows on `20260706` and 621 on `20260722`, 629 total. A broader presentation predicate using `B.amount > 0 OR B.trade > 0` yields 630, including `HK.03403` with positive B amount and nonpositive B trade. These are different predicates; the broader count is not an audit error.

Phase 2 verified these frozen keys through both the dynamic adapter and an isolated TestClient: `HK.00001/20180102` is B-only; `HK.00001/20230630` is a matching overlap owned by C; `HK.00001/20260706` is a conflicting overlap owned by C. The returned source and category matched the receipt and the source-order row digests matched their frozen digests. Exact results are recorded without raw market values in `PHASE2_RECEIPT.json`.

## Validation and unresolved evidence

Focused command:

```text
'/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python' -B -m unittest tests.test_hk_research_history -v
```

Result: 8 tests passed, including fixture classification, source integrity, dynamic C pointer changes, traversal/tamper rejection, and isolated TestClient bounds/sanitization.

`CANNOT_CONFIRM`: The live 8873 route is not online for this candidate (the direct GET returned 404); candidate TestClient verification does not imply deployment. Raw value units, currency basis, adjustment basis, and PIT safety remain unknown. Per-file unchanged identity for LaunchAgent plists outside the active API and HK scheduler plists is unverified because the aggregate transaction's per-file hash map was not retained. Phase 2 review does not establish semantic validation of canonical data or scoring activation.
