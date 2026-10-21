# R6 exact approved deletions and current name observations

GOAL: Along the same original producer V2 candidate path, remove only individually approved old source keys absent from the already-certified native suspension repair; permit independently reviewed current-revision name observations through the explicitly frozen observation date. No formula/scoring/model parameters or ordinary incremental behavior changes.

WRITER: /root/v192_same_day_panel_writer, sole source/test Writer. REVIEWER: /root/same_day_panel_independent_review, independent/read-only. ALLOWED: original producer payload, existing same-day fixture file, handoff docs, batch NEXT_SAME_DAY_PANEL_* only. FORBIDDEN: original market artifacts, live sources/pointers/services/schedules/registry, other Writer files, Windows, source execution/import/compilation/tests/numerical data reads, commit/push. PASS_SIGNAL: independent incremental static review, unique registrar RUN_STARTED, then only the new test_v6_ cases. STOP: missing/ambiguous/delete/update/insert/source identity or review evidence, unknown name observation, failed exact-key transform, actual unapproved extra key changes.

Baseline source182872309e50ceff39abef513fcda08f0088606767eb2b89f95efda1d6c796a7 and tests57a35840082362375e3e0d06f82604b6612922459d6000ec1846b8feced4a7ea are preserved as exact source/test snapshots in this directory. Existing independent73 same-file cases are reused: prior45 plus R4's23 plus R5's5 (R5 receipt24b71a14d68b42dd6448ccd6faeeeec0b67b4b82a064503e45981f005c670966). The approved47 formula/input/trace results remain untouched. No old fixture oracle or business parameter changed; the session registration gate only admits the explicit new R6 scope.

Actual authorization is exact and limited: in each new selector/backtest candidate, exclude 300550.SZ/20260526, /20260527, /20260528, /20260529. Preserve all original artifacts unchanged. This document is not the native-absence evidence or independent complete input approval; those references remain pending with the unique input binder. No other source row is implicitly dropped. The35 selector20260430 missing-key disposition remains separately pending; R6 does not invent insertion approval. backtest.source_panel_path is a legitimate original policy drop and is not added as required. Three missing BJ names may use the original Mac producer TDX interface with actual observation20261021, explicitly non-PIT; no fake D-day timestamp is permitted.

Per-role deletion contract extension:

```text
approved_delete_keys: ordinary exact bound list of [ts_code, integer_date]
approved_delete_evidence: one and only one entry per delete key:
  key: [ts_code, integer_date]
  policy: APPROVED_NATIVE_ABSENT_SUSPENSION_CURRENT_REVISION
  reason: nonblank exact adjudicated reason
  review_receipt: exact path/SHA reference
  native_absence_binding: exact path/SHA reference
expected_new_rows: expected_old_rows + approved_insert_count - approved_delete_count
expected_new_key_sha256: null for this explicit deletion mode
approved_key_transform:
  schema: V192_EXACT_ORDERED_KEY_TRANSFORM_V1
  source_key_sha256: exact previously-bound old physical ordered-key SHA
  delete_keys_sha256: approved_delete_keys.sha256
  insert_keys_sha256: approved_insert_keys.sha256
  order: RETAIN_SOURCE_PHYSICAL_ORDER_THEN_SORTED_APPROVED_INSERTS
  sha256: canonical JSON SHA of the preceding five fields
```

Deletion keys must be disjoint from update and insert keys and belong to admitted symbols. Every deletion must match exactly one existing physical source row, including uniqueness across batches; missing or duplicate keys stop. Evidence keys must exactly equal the approved key set, with bound original receipt identities. Independent `input_binding_receipt.approved_deletions` must be true in addition to the existing complete V2 flags and exact source/contract identity. This is an explicit, independently approved operation, not a default drop-na/dedupe/missing-data policy.

R3 did not save the full ordered key stream, so its old SHA cannot yield the post-deletion SHA. The candidate's existing streaming read checks the full original ordered-key SHA, accumulates a separate retained-order digest while excluding only exact approved keys, then appends sorted approved insert keys. It produces actual new_key_sha256, key_transform_sha256, old_rows, deleted_rows and final rows. No preliminary full-source key read is added to precompute a guessed expected digest. The normal no-deletion path keeps its original exact expected new-key SHA requirement and write mode.

The actual R3+delta assembly spec must explicitly map the deleting roles' expected_new_key_sha256 to null and supply the new approved_key_transform, overriding the old R3 insert-only expected digest. Do not retain the old draft's later checker-to-expected-digest assignment for those roles: it would overwrite the resolved null with a digest that includes the four rows. The JSON-only helper can already apply the explicit final metadata mapping without a code change. Existing update/insert keys must separately consume the approved delta; R6 neither invents cross-role inserts nor treats old R3 gaps as PASS.

The candidate remains CANDIDATE_ONLY_REQUIRES_INDEPENDENT_REVIEW. Its computed digest does not approve its own transformation. Before the existing same_day_promote can proceed for a deletion candidate, the independently bound candidate review must additionally contain approved_delete_transform_verified=true and approved_key_transforms, exactly mapping each deleting role to {key_transform_sha256,new_key_sha256,rows,deleted_rows}. The reviewer verifies the real retained physical order and exact approved additions/removals. The review identity must differ from Writer and bind the exact candidate receipt/code as before. Subsequent strict-generation packaging/publication must honor the same independent real-candidate transformation acceptance; two legacy pointers alone do not publish a strict generation.

Current-revision name extension:

```text
runtime_binding.revision_observation_date: 20261021
static_rows.records[...]:
  field: name
  value: actual name from the authorized original source
  observed_date: actual integer date (20261021 for the new query)
  status: CURRENT_REVISION_NON_PIT
  reason: nonblank original-source/current-revision explanation
  source: exact path/SHA reference
  observation_review_receipt: independently bound exact path/SHA reference
```

Only name may have observed_date later than signal D, only through the frozen revision cutoff, and only with the additional independent observation receipt. Without the explicit cutoff, the original D cutoff applies. Every other static field retains the original observed_date<=D rule. Complete contract SHA binds this runtime metadata; no new root field or assembler helper change is needed. The candidate receipt records revision_observation_date, name_observation_status=CURRENT_REVISION_NON_PIT and historical_name_pit_claimed=false. This is a current snapshot revision, not a historical name PIT assertion. Existing D-day and earlier name behavior is unchanged.

Static new fixture selection: `tests/test_v192_same_day_panel_revision.py -k test_v6_`, declared25 parameter-expanded cases (NOT_COLLECTED/NOT_EXECUTED by Writer). Registration scope: SYNTHETIC_SAME_DAY_PANEL_V2_APPROVED_DELETE_AND_NAME_ONLY. Cases cover exact four-row dual-role deletion, source/pointer immutability, untouched large integers and unrelated duplicates, missing independent delete flag, exact reasons/evidence/policy, update/insert overlap, absent/duplicate physical source deletion, row-count/transform/source-key/source-order drift, no automatic deletion, independent publication transform gating, and reviewed post-D name approval versus missing receipt/cutoff/late/other-field rejection. Existing73 are not selected again.

Changed source/test SHA and exact static commands are in STATIC_R6_RECEIPT.json. No actual market, footer, name query, candidate, test, import, compilation, registry or publication execution occurred in this Writer stage. Real R3+delta input artifacts, source/current name approvals, retained-order semantic review and strict-generation owner/publish remain later gates. The already-reviewed JSON-only assembler f60dea40f14f0770b21aa0bc9150706a7a876e1d5dfc8e9df1a8f2931f54176f remains byte-identical; final metadata must reference actual R3+delta and this new producer identity rather than the unexecuted R2 draft.
