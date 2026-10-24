# US–HK selection remediation handoff

The approved implementation uses the existing V4 entry and data owners. `ACCEPTANCE.json` records scoped acceptance and runtime status; `ISSUES.md` separates repairs from unresolved material. `SOURCE_MANIFEST.json` binds 166 source/test/calendar files. `RUNTIME_REQUIREMENTS.json` identifies the retained role runtimes and 21 explicit immutable-base dependencies: this is not a standalone-checkout certification.

Verified core source commit: `451df46ac91e58e55b83f76bc2daa48934b90fa7` on `lexi2016/v4`, branch `codex/us-hk-selection-closure-20261023`, parent `c4ba0640ffe09b89ad72a211fb3be42da5a533ff`. The local worktree baseline is separately `4e00084d8ef9c606bfff2892dcab35515423c776`. These identities are not interchangeable. Later helper/runtime receipts supersede only their own scope.

Frozen strict policy: primary specific-company positive relationship; primary US return at least 1%; prior completed HK close between MA20 and 1.1×MA20; five-session return at most 15%; twenty-session mean turnover at least HKD20m; stable primary-return/turnover/code ordering followed by Top10/theme3 caps. Unknown price, currency, amount, adjustment, historical availability or target eligibility is PENDING. ETF context cannot qualify or veto a stock. A strict research pass does not establish efficacy or authorize orders.

`ZERO_RESULT_DIAGNOSIS.json` explains the exact Oct22 replay: 670 research candidates, 397 primary US returns below 1%, 100 quotes pending and 173 passing that return gate. All 670 still lack necessary strict relationship and frozen HK-history/readiness proof. Final states are 397 REJECT and 273 PENDING; strict0 is incomplete/NA. The original saved version retains its five BENEFIT observations and is not rewritten.

Recorded checks below are reproducible entry points, not instructions to repeat already accepted identical work. Run from the source root with the retained test runtime identified in `RUNTIME_REQUIREMENTS.json`; it is distinct from the actual API, scheduler and HK-child runtime. Exact historical commands, setup failures and reviewer-only adversarial harnesses remain in the local SDD receipts. Raw inputs, logs and temporary harness directories are intentionally not uploaded.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD:$PWD/upstreams/v3_shared_data" \
  /Users/lexi/Desktop/学习/v4_app/.venv/bin/python -m pytest -q \
  tests/manager_workbench/test_us_hk_compact.py -k repair_r2
```

Recorded backend R2 result: four PASS, nine deselected; an independent four-test/eight-API-case repair check also PASS. Earlier unchanged five-finding, 122-test and R1 evidence is reused within its original scope, not relabelled as a new whole-suite run.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD:$PWD/upstreams/v3_shared_data" \
  /Users/lexi/Desktop/学习/v4_app/.venv/bin/python -B -m pytest -q -p no:cacheprovider \
  tests/manager_workbench/test_us_mapping_replay.py \
  tests/manager_workbench/test_us_mapping_replay_metrics.py
```

Independent replay coverage: 30 PASS across the original 18 passes and the bounded rerun of 12 reviewer setup errors after its scratch parent was created. The real CLI Oct22 and two PREOPEN cases each ran twice without checkpoint reuse and matched the recorded semantic hashes.

```sh
cd apps/web
node node_modules/vitest/vitest.mjs run \
  src/manager-workbench/__tests__/us_mapping_selection.spec.ts \
  --testNamePattern='renders short legacy compact|keeps the full legacy summary|disables short saved-card' \
  --reporter=dot
```

Independent frontend repair2 result: four PASS/seven skipped, plus one reviewer-owned exact 15,126-byte old-response render case PASS. Component acceptance does not establish deployed browser acceptance.

The historical CLI is `ops/replay_us_mapping_selection.py`. It consumes the frozen local inventory, a fresh isolated output directory, explicit run IDs and `--deterministic --workers 1` for the canary. The accepted inventory SHA is `714314d500ae66f5f428ac08629ae92946d7a8506acd4cb87b1433ec2aafa6ed`; final freeze `c0ccd2145ba27b4c3eeb78de027585ab099007f1ee4190f554155701c16ff698`; 101-disposition aggregate `2371276a4efa96537a0937607e7f43762106a01111f1dcc9f7eaca960941a4ec`. Eighty-seven real engine cases completed; 14 missing-input receipts were inherited unchanged. Coverage is 8/60 sessions, PIT-evaluable dates0, labels read0, actual returns all NA. No profitable or executable strategy claim follows.

Panel accounting retains 1,479,081 input dispositions and an inactive 1,037,084-row/719-code derived candidate. Real strict field readiness remains PENDING. Historical provider frames discarded before this repair cannot be recreated; prospective capture preserves full SDK frames on the same existing producer/provider path. Source original bytes and old versions remain preserved.

Deployment is separately gated on exact role inputs, independently reviewed helper behavior, prepared candidate/import/build/rollback evidence and the actual service readback. `NATURAL_ACCEPTANCE.md` defines two fully subsequent natural cycles. A test, manual retrospective, healthy port or unknown zero cannot substitute for those receipts. Safety stays RESEARCH_ONLY=true, production_allowed=false, buy_gate_updated=false, orders_sent=false.

`RELEASE_HELPERS.json` records independent helper repair2 PASS with 30 targeted checks, source hashes, exact case names and limits. Original admission/build findings and the real Store-root, control-framing, SHARED and scheduler inventory counterexamples are closed within that scope. No actual candidate build, service cutover or data-pointer write is implied by this helper PASS.

Current runtime integration snapshot: the single frontend build and SHARED candidate have independent acceptance. API r1 passed identity/import checks but is explicitly blocked from activation because its retained Store45a lacks the merger keyword used by service. API r2 adds the unchanged baseline Store3717; no frontend rebuild is required. HK731 artifacts materialized without SDK changes, but its strict readonly canary refused the original SDK file logger before native compatibility could be certified. No service cutover or business publication has occurred. RELEASE_HELPERS.json records these distinct scopes and failures.
