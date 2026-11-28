# ACT-071B Phase 2

This module builds ACT-071R scheme B first-test cases using the frozen ACT-071A V1.1 builder, schema and validator at base `f15b2232afa6cb60a714bf08c1f7669a4d7dd812`. ACT-071B signs new cases only.

## Reader boundary

`research.act071b.generate_cases.execute` takes a verified, frozen all-A stock-code roster and a lazy `load_sessions(stock_code)` callable from A's governed canonical V4 Reader. Each projection contains exactly `date,open,high,low,close,volume`, with ascending unique actual stock sessions filtered through 2026-11-06. Earlier sessions may support window warm-up. The source identity includes `panel_path`, `manifest_path`, `generation`, `panel_sha256`, `manifest_sha256`, `price_basis`, and `volume_basis`. A verifies the actual Reader, partition manifest, A-market, price and volume identities in its file access audit.

The certified 57-stock CSV is pinned by exact SHA-256 and read directly. Both legacy Beijing aliases are also excluded. Stock order is ascending SHA-256 of `ACT071R_V1.1:` and canonical code concatenated. Candidate D is inside 2017-10-19 through 2026-11-06. Each supplied stock session has a zero-based index measured from the first actual stock session in the Reader projection. An invalid or nonpositive-volume projected row cannot be used or bridged by a selected window.

Each proxy uses D candle direction and the change in volume from the immediately prior observed session. An exact suffix feasibility search selects the earliest lexicographic eight-date tuple with two of each proxy category and disjoint windows `[s(D)-34,s(D)]`. Only mechanical rejection permits continuing to another stock. The B2 day eligibility formula is recomputed from D's actual candle independently. Historical-vintage PIT stays `CANNOT_CONFIRM`, P4 is `UNBOUND`, and the four structural event chains stay `UNKNOWN`.

## Handoff

Pass a fresh `output_root` under A's artifact directory. The workflow writes the eight case directories, isolated ZIPs containing the same exact five case files, the trusted `A_CASE_RECEIPT_FIRST_TEST_8D_V1_1.json`, and `selection_and_skip_audit.json` with the candidate order, predecessor decisions and all 28 pairwise checks. If the eligible source has no feasible stock, the audit records exhaustion.

A retains its receipt and audit. Each case's digest binds both image hashes, whitelist, D and pinned V1.1 schema and knowledge versions. D and its prior session are the only bar sessions used for signed non-chart observations. Use the frozen CLI with the package paths to verify each response:

```sh
"$PANEL_PYTHON" -B -m research.act071a.validate_b_output \
  --case-dir "$OUTPUT/02_FIRST_TEST_8D_V1_1/T01" \
  --trusted-receipt "$OUTPUT/A_CASE_RECEIPT_FIRST_TEST_8D_V1_1.json" \
  --output "$A_HELD_RESPONSE_JSON"
```

Targeted synthetic checks run with `"$PANEL_PYTHON" -B -m research.act071b.selftest`. They exercise the exact search oracle, an unusable-session barrier, stock order and skips, package membership, scope integrity and two frozen validator roundtrips.
