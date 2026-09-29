# F5 RFF issue #2: bounded truth-join repair

## Scope and source

Source baseline: `c24892e57cf4a568bc96095748974abe28b3112f`.
The repair branch starts at `73c6f2684017556c529616cba6bd288951ce88e9`, whose sole change from that baseline is the added `CHAT_REPAIR_PROMPT.md`. No old ZIP is used. This is a source-only repair, not authorization to resume execution.

Only one runtime file changes: `research/hk_burst_f5/batches/full64_rff_logistic_r1_20260927/src/rff_worker.py` relative to this slice. The historical XENDCG helper/owner, score-aware wrapper, frozen evaluator, L04 completion code, model, controls, contracts and resource policy are not modified.

## Defect and fix

The historical helper compares the null-y count after a left join with the count over the entire truth table. For A/B/C/D with labels 1/0/1/null, the legitimate A/B/C subset has zero null labels rather than one. Conversely, equal null counts do not establish key membership.

RFF now owns a small local `_join_truth` and no longer imports that symbol from the historical helper. It validates required and unambiguous columns, non-null composite `(code, session_id)` keys, uniqueness on both sides (including truth keys outside a subset), and explicit membership for every left key. Missing keys fail with `RFF_TRUTH_JOIN_UNMATCHED_KEY`; duplicates fail with `RFF_TRUTH_JOIN_DUPLICATE_KEY`. It then assigns outcome arrays in left-row order to a copy of the left frame. All pre-existing columns, score bits, index and row count are retained. Legal unknown y/first_exact values are not filled or recoded. The required `label_status` and `episode_state` checks remain.

The two worker call sites and the entire execution body are unchanged except for removal of the old import. The resource trace remains admissible inside candidate_output. L04 containment checks are unchanged; this repair does not disable them.

## Executed synthetic verification

Command from repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  research/f5-rff-r3/research/hk_burst_f5/batches/full64_rff_logistic_r1_20260927/tests/test_rff_truth_join.py \
  -v --tb=short
```

The first RED run against the old worker binding was **24 failed / 4 passed**, including a reproduced `CANDIDATE_TRUTH_JOIN_DOMAIN_MISMATCH` for the A/B/C Top3. These are regression cases, not 24 distinct production defects. After the patch, all 28 cases passed. One additional frozen-worker-body check was then added: the final run was **29 passed, 0 failed, 0 errors** (1.75 seconds in this Linux environment).

Coverage includes full grid, Top3 excluding the null label, subset including the null label, empty subset, preserved order/index/score bits, nullable label dtypes, actual missing keys (including null-count cancellation), duplicate left/truth keys, off-subset duplicate truth, missing keys, ambiguous columns, required metadata and composite keys across sessions.

The integration tests execute the actual worker AST statements from `candidate_frame = _join_truth(...)` through the in-memory `metrics` dictionary. They exercise both joins, candidate arm/probability metrics, both frozen control comparisons, paired metrics, denominator guards and gate assembly. The score-aware wrapper and frozen metric function bytes were checked against their baseline SHA256. Only machine-specific metric loading and control artifact I/O/hash access are replaced by synthetic in-memory fixtures. Calibration bins in the test fixture are `[0, .5, 1]`; no real settings or signed contract is loaded or changed. Negative cases prove both full-grid and Top3 missing keys stop before the evaluator.

The worker's fit/predict/truth-decode/input-reading and output-writing statements are not compiled into the integration test. The full worker is never invoked. No synthetic metric dictionary is written as a real `METRICS` or completion receipt.

Local tests use the complete exact worker, score-aware wrapper and frozen metrics files reconstructed from GitHub content and verified by SHA256. For the historical helper, only the exact safe function/class extracts (`CandidateError`, `_join_truth`, `_deep_equal`, `_top3_identity`) are compiled, not the full historical worker. The repository test reads those same functions from the full unchanged repository file. The local historical excerpt is test-runtime-only and is NOT part of this patch.

Environment: Linux x86_64, Python 3.13.5, pandas 2.2.3, NumPy 2.3.5, scikit-learn 1.8.0, pytest 9.0.2. No packages were installed or rebuilt. This is not Mac execution, GitHub CI evidence, a full project-suite run, full-owner startup acceptance, or a complete L04 integration test. Broader tests were not run because training/recovery is outside this authorization.

## Identities and signed history

Runtime worker before SHA256:
`cecff1218a60c3c67405168b742f40ba76286efbd2435d8f31703375c640619d` (26,856 bytes).

Runtime worker after SHA256:
`3ea10757a81207147e5cfb9e68e69750a0579786153e7ce58ccf342a3184058c` (28,369 bytes).

New test SHA256:
`1ff18ce9e67932dacfafcbb8b32b2ccd49ce3cc8db22d6e753b9426691a2f825` (14,943 bytes).

`SOURCE_IDENTITY_DELTA_ISSUE_2.json` is the candidate overlay. `SOURCE_MAP.json` remains the historical snapshot; do not mistake its old worker hash for the patched candidate identity. No active or historical binding, run spec, review, release or result receipt has been rewritten. The delta is NOT a signed binding.

Any separately authorized future binding must change `code_files.rff_worker.sha256` to the after SHA and recompute aggregate source identity using the exact complete `code_files` object and actual paths. The worker checks canonical JSON SHA256 against payload `source_code_sha256`. A new aggregate hash is intentionally not invented from sanitized share paths. Resolve derived signed identities through the existing owner/contract interfaces; never overwrite old signed artifacts or reset consumed counters.

## Remaining unknowns and stop condition

The issue records one real fit, one full-S prediction and one truth decode already consumed. This task consumed zero of each and did not read or modify real market inputs, scores, labels, models or sealed prediction bytes. It provides no model-performance conclusion: retain `CANNOT_CONFIRM` for research performance.

The real exception is recorded, but there is no saved real traceback or first-join success marker. The synthetic Top3 traceback proves the code defect, not the exact stack location of the historical real failure. Do not relabel the synthetic stack or an earlier prefit failure as that missing real traceback.

Mac acceptance, separately authorized saved-artifact recovery, actual source/contract rebinding and successful real L04 completion remain unexecuted. No resume command is provided here. The future no-default-4-thread/3-GiB/1800-second requirement is a separate task; no resource cap changes are mixed into this join patch.

`RESEARCH_ONLY=true`, `production_allowed=false`, `buy_gate_updated=false`, `orders_sent=false`. No deployment, BUY gate or order mutation. Future F5 training coordination remains in the user's designated new conversation, not the old thread; the shared URL is not treated as an API thread identifier.
