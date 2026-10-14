# Flash announcement script facts experiment, 2026-10-14

Research-only temporary experiment. Canonical V4 source and the manager workbench were not changed or integrated. No production permission, BUY gate change or orders.

## Scope and identity

Source root: /Users/lexi/Desktop/学习/agents调试/助手/qwen_flash_next_20261013/pipeline_canary
Baseline private handoff commit: 7652a0bcc28fc2fd8411b3180cff03307a88545b
Runtime: Python 3.12.13, oMLX 0.7.0, xgrammar 0.2.3, tvm-ffi 0.1.11 with the official oMLX torch import stub. Explicit model qwen3_8_flash_next. The original 27B is retained. No global model or runtime configuration change in v9.
Current manifest SHA256: a2f1832743851db0405c7891f47c6d930e7cebcb1325a6ecdad99bf7170f688c
Frozen gold SHA256: 92ce3d0c1b1aae060b123c2bb63d6f9172e2ae4937c1cf3d0c120731d97461a9
Frozen pressure source manifest SHA256: c1807c43904ddbf9d3fee5f77a4bd57eddf6252d53dbd0c363cd3c28d4aaee65

Six fixed real announcement inputs and a frozen pressure cohort of 29. Overlap one, 34 unique total; pressure adds at most 28 new requests. Sources captured on 2026-10-13. The upstream archive has 277 complete bodies and 26 failures; this experiment does not repair capture failures or represent all 277.

## Implemented division of work

Deterministic scripts parse fixed facts, preserve exact source quotations and calculate ratios only when the matching denominator is present. Unknown data remain CANNOT_CONFIRM. Scripts own facts/changes and input PIT provenance; the model owns business judgments. Original raw model responses are retained without correction.

Single queue concurrency, Thinking OFF, full bodies preserved, structured JSON output. External lookup is only for a specifically missing material fact; results remain untrusted. The fixed gold is not supplied to the model and never rewrites outputs. Machine matches do not imply semantic correctness.

The final v9 changes only request-specific temperature to 0.0 for decision_simple_facts. Installed oMLX accepts zero and uses argmax when forced sampling is disabled. Global temperature remains 1.0; the legacy profiles do not receive the override. Other sampling controls, prompt, schema, parser, source bodies and gold stay unchanged.

## Independent offline verification

Earlier unchanged parser/runner tests and source receipts were reused. V8 independent checks covered provenance and frozen gold projection; six focused checks passed.
V9 independent Reviewer reran four focused tests, all passed, with no blocking P0/P1/P2:

- test_new_simple_workflow_plan_counts_all_34_and_starts_a_fresh_pending_queue
- test_executor_request_uses_one_structured_simple_reader_and_sends_the_full_body_once
- test_temperature_override_is_simple_profile_scoped_and_legacy_request_is_unchanged
- test_simple_workflow_profile_has_a_fresh_root_and_preserves_old_profile_hashes

Run with PYTHONDONTWRITEBYTECODE=1 and the runtime Python above, python -m unittest test_automatic_canary_server.AutomaticCanaryServerTests.<name> -v.
No background or command-line model requests were used for these checks.

## Visible live measurements

All live model starts were performed through the temporary Codex in-app browser test UI. Each final six run used one attempt per article, no retries.

| Variant | Six total wall seconds | Semantic result |
| --- | ---: | --- |
| v5 legacy baseline | 184.731 | failed |
| v6 script facts | 133.445236 | 4/6 PASS |
| v7 judgment prompt | 118.938056 | failed |
| v8 program provenance and frozen gold | 121.275064 | 3/6 PASS |
| v9 request temperature zero | 44.662294 | 6/6 PASS |

V9 wall includes one-time fixed-fact preprocessing 0.013566 seconds plus visible phase 44.648728 seconds. Model requests total 44.539 seconds. Machine gold matches all six classification, ledger, PIT and reference checks; independent fresh business semantic review passed all six.

The same prompts had already been run in v8, and v9 first nonempty content latency was 0.139 to 0.901 seconds. Each request reported prompt_tokens minus cached_tokens equal to seven; the prefixes were warm. The 44.66-second result must not be attributed entirely to temperature or extrapolated to unseen announcements. Resident model conditions are not a cold weight-load benchmark.

Earlier failures are retained: unsupported cash-flow/materiality claims without a financial baseline, invented authority and overbroad source-silence conclusions, and incorrectly treating absent underlying payment details as preventing classification of an administrative cover announcement. Correct repetitions of source names, dates or amounts are not errors. Unchanged gold and source facts are reused; only changed outputs require fresh semantic review.

## Source byte identities

| File | Before SHA256 at baseline | Current SHA256 |
| --- | --- | --- |
| batch_runner.py | 057781017060db0088a1a4f14216295ba9a0dd3c36af0c9dd89ae2845d48beb1 | 2ee696489990f7ba9d3813a79be5a8494fcea53b82b06d32a94927b79f3f1aa2 |
| automatic_canary_server.py | ce1451b0b84de3d4dfcff46a75485a16fe3066cd5aedfee88a48387d4d1c2551 | 35e49f52720ba98f08985d2e18e0715b100fd26b6812377ce5b157e3363f0519 |
| simple_fixed_facts.py | new | 33424d9688878b805c9ada3e44f48b19b2e9c380821d4509e85300e252f0c903 |
| test_batch_runner.py | a2f0d7e6fc8738a2387167fed414c8de97af2a982f7bbcc0c9e683979f63095e | da847b713149147f440201b835b93f2d914e9e62c740020173fa780e1e6c9aea |
| test_automatic_canary_server.py | 27311aba96e18dae9787b19aac859c78ee7a13bde2bdca5bd33844f5b37f6866 | b7314996d80c9136539dfd9357b035f50b96021a41fea78b3992229e999bc470 |
| test_simple_fixed_facts.py | new | aec2ad04ac638cefed3f00468b60763164312113f98ad4e3ba4aaa88dcf77d8f |

## Status

IMPLEMENTED and independently offline REVIEWED. New six live semantic result BEHAVIOR_VERIFIED 6/6 PASS.
Pressure 29 completed after the visible six gate: 28/29 mechanically SUCCEEDED (one reuses the already verified overlap), 1 FAILED with ANNOUNCEMENT_EVIDENCE_INCOMPLETE. The 28 newly scheduled requests each ran once, with no retry. Phase wall was 478.336896 seconds, new model request time 477.854 seconds; Independent review reused the verified overlap and reviewed only 28 new judgments: 24 semantic PASS, 3 semantic FAIL, 1 validator-blocked. The complete 29-item cohort therefore has 25 usable PASS, 3 semantic FAIL and 1 validator-blocked. The failed contract announcement original raw is retained; its signed-contract characterization is source supported, not delivered revenue. The validator predicate causing ANNOUNCEMENT_EVIDENCE_INCOMPLETE remains CANNOT_CONFIRM; the output is not usable while validation is unresolved. Total union has 33 success, 1 failure, no pending items. UI completion and machine matches cannot authorize this gate by themselves.
Not integrated, not deployed, no API/UI acceptance of canonical V4, natural slot NOT_RUN.
No raw source bodies, answers, gold dataset, queue state, runtime credentials or configuration are included in this Git handoff.

## Pressure quality verdict

REVIEWED FAIL for the complete pressure cohort. The three substantive errors are an undisclosed treasury-share purpose conjecture (HK.01357), an incorrect company name (HK.00738), and an incorrect percentage denominator that confuses the buyback authorization cap with outstanding shares (HK.02299). HK.02656 is separately validator-blocked despite a source-supported raw contract judgment. No answers, standards or frozen sources were altered to obtain a pass. No further prompt stacking or unchanged-input retries were performed.

The investigation/audit/suspension status in HK.02898 retains source attribution; the proposed auditor appointment in HK.08619 retains its approval condition. Six canary PASS does not establish unseen-cohort reliability. The current pipeline cannot be reported as fully reliable autonomous announcement selection. These candidates have not been integrated or deployed. The script/model division improved factual ownership and bounded queue execution; free-text judgment still admits factual hallucination and the validator has an unresolved failure.
