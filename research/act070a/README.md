# ACT-070A D-only candidate handoff

ACT-070A constructs four known calibration cases from pinned V4 evidence. The frozen ACT-069B evidence marks P4 `registered_segment` as `MISSING_SOURCE` with `SEGMENT_DEFINITION_SOURCE_UNBOUND`. No case qualifies as a certified first test. The pack includes an empty `02_FIRST_TEST_8D` directory.

Use the project's `PANEL_PYTHON` from the worktree root. The plan is selected and retained by A. It has two keys with exactly four ordered `calibration` entries and an empty `first_test` list. Each entry has an A-assigned `case_id` from `C01` through `C04`, and a distinct ISO `d` from the pinned ACT-069B checkpoints.

```sh
"$PANEL_PYTHON" -B -m research.act070a.selftest
"$PANEL_PYTHON" -B -m research.act070a.generate_cases --plan PLAN.json --out NEW_CASE_DIRECTORY
"$PANEL_PYTHON" -B -m research.act070a.validate_b_output \
  --case-dir NEW_CASE_DIRECTORY/01_CALIBRATION_4D/C01 \
  --trusted-receipt NEW_CASE_DIRECTORY/A_CASE_RECEIPT.json \
  --output B_RESPONSE_C01.json
```

Each case is independent and contains `input.json`, `chart.svg`, the output JSON Schema, and the forward-neutral KB rule cards. The chart consists of 35 consecutive source sessions through D. Its exact OHLCV values appear in the whitelist. Every plotted position maps to one A-assigned row ID in explicit order. P1–P5 repeat across facts. Each fact has a distinct ID within the case, a locator, and its original availability state. The KB records the user-reported recovery of 106 pages and the limits on page provenance and original review.

A keeps `A_CASE_RECEIPT.json` and uses its trusted digest to validate B's raw response. B receives the corresponding case directory. The digest binds D, exact chart bytes by SHA-256, the ordered chart-to-row map, whitelist facts, frozen upstream SHA-256s, schema and KB file hashes, KB rule IDs, and immutable A status. A custody of the separate receipt supplies the trust boundary. The input digest is a content hash. The validator redraws the chart from the mapped rows and rejects a missing mapping or mismatched bytes. Schema and KB bytes must also match the local frozen versions.

B uses `CANDIDATE` claims of type `KEY_K`, `PIVOT`, `SUPPORT`, `OLD_ANCHOR_INVALIDATION`, or `PHASE`. It supplies prices and positions exclusively through row and field references, with null endpoints for open or inapplicable spans. For abstention it can supply an empty claims list and a closed abstention code. Positive and opposing evidence are explicit lists. A rejects references to `MISSING_SOURCE` and checks chart role, chronology and case identity. B can cite A's B2 day status as counterevidence. Its original `FALSE` or `UNKNOWN` eligibility and absent formal B2 event remain A-owned.

A derives dates for a single-bar key-candle observation with linked price and volume evidence, or an old-anchor close-break candidate with a previously knowable registered anchor and a separately bound same-identity break proof. For the remaining claim types and ambiguous candidate dates, A returns `UNRESOLVED`. The returned dates describe observations. No promotion, pivot confirmation, formal event, or risk-clear verdict is in the protocol.

The source receipt logs one integrity read of each of the four exact approved inputs, zero separate future-source opens, and maximum delivered/reference dates by case. The pinned CSVs span the parent historical cohort. A computes case windows from the D prefix only and packages no forward data. The selftest uses a synthetic chart, calls no models, and reads no market inputs. It exercises the legal candidate and abstention, forged-price attacks, date/reference attacks, promotion and override attacks, chart and hash tampering, and refusal to create an uncertified first test.

Research boundary. `RESEARCH_ONLY=true`, `S_FIT=0`, `B_FIT=0`, `PRODUCTION_ALLOWED=false`, `buy_gate_updated=false`, `orders_sent=false`.
