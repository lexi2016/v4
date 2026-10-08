# Issue #28 — independent candidate source review

Reviewer identity: `/root/independent_review`, separate from the candidate authors. Review date: 2026-10-08. Repository baseline: `lexi2016/v4@00524e9050fe212f87911b56eea1c2db719dd94b`.

## Decision and scope

**No unresolved Critical, P1 or P2 candidate-code defect was found within the bounded scope reviewed below.** The auction, HK and release changes are suitable to take forward for adaptation against the actual owner files and another exact-package review. The pool batch correctly reuses the frozen implementation and adds regression coverage without a new business-source delta.

**This is not a deployment review, an installation receipt, merge permission, or proof of live behavior.** Actual HK scheduler/shared-source/store closure remains `CANNOT_CONFIRM_ACTIVE_DEPENDENCY_CLOSURE`. The real release identity, plan and review scope have not been migrated or accepted. Mac, complete application integration, live API/UI and natural execution remain unverified. No formal `DEPLOYABLE=READY` decision is issued here.

I read `AGENTS.md`, `evidence/README.md`, `evidence/SOURCE_MANIFEST.json`, `work/IMPLEMENTATION_PLAN.md`, `delivery/OPEN_ITEMS.md`, `delivery/LUNA_MAX_NEXT_STEPS.md`, each batch's explanation, changed files, relevant unchanged consumers/validators, and the actual test/scaffold implementations. I freshly ran the focused checks, inspected their assertions and failures, and independently checked source identities and patch replay. I did not operate GitHub, services, collectors, business data, BUY/model/manager/Vibe code, or any other producer.

## Findings by severity

| Class | New actionable candidate defects | Disposition |
| --- | ---: | --- |
| Critical | 0 | No finding in the reviewed paths and scenarios. |
| P1 | 0 | The reproduced source defects are addressed in the candidate bytes; the P1 runtime evidence gaps below remain open. |
| P2 | 0 | No additional candidate correction requested. Existing issue-level P2s were not promoted to resolved. |

No author correction was requested during this independent review. This result is limited to the changed behavior and explicit inherited code needed to assess it; it is not an unreviewed blanket PASS for the application or the full external HK cutover utility.

### Open evidence and integration gates — separate from candidate-code findings

| Priority / boundary | Exact reference | What remains required |
| --- | --- | --- |
| P1: actual HK caller and dependencies | `delivery/OPEN_ITEMS.md:13–24`; candidate `delivery/hk/after/active_producer_reference/ops/materialize_scheduled_preselection.py:113–129,191–198` | Actual scheduler `infrastructure/scheduling/executor_registry.py`, its forwarding parameters, the loaded shared-package root/`shared_data/hk_0_2.py`, and producer/Stage store dependencies with current SHA identities. Canonical test dependencies cannot establish those identities. |
| P1: real HK source and capture | `delivery/OPEN_ITEMS.md:26–28`; candidate `delivery/hk/after/active_producer_reference/domains/preselection_materializer.py:516–571` | Verified real 10/7 price and 9/30 eligibility source trios, run IDs, hashes and original capture evidence. Synthetic publisher fixtures prove the adapter contract, not source availability or historical PIT. |
| P1: release package migration | `delivery/release/source/blocked_candidate_ops/api_candidate_install_r2.py:178–198,306–348`; `delivery/release/RELEASE_REPORT.md`, “Exact-pin contract migration required” | Bind the final guard/path in the real identity, regenerate the identity SHA/helper hashes/plan and exact 21-field scope, and obtain a separate independent real-package review. Keeping the old identity digest in the source candidate is deliberate fail-closed behavior; the old plan/19-field review cannot install it. |
| Integration/acceptance | `delivery/LUNA_MAX_NEXT_STEPS.md`; batch reports' NOT_RUN sections | Full current-owner imports on Mac Python 3.14.6, original singleton Stage canary, live 8873 API/read-only UI readback of the same run/SHA, and separately proven natural execution. |

## 1. Auction: field transmission, persistence and ranking

The two builders remain distinct. The active Stage builder adds `prev_close_price` at `delivery/auction/after/active_stage_reference/stage_center/_live_collectors_parts/selection_builder_registry.py:31`; canonical adds it at its own `.../canonical/.../selection_builder_registry.py:309`. Forward/reverse patch replay proves each hunk is bound to its own preimage; canonical was not copied over the active variant.

The shared selector change at `delivery/auction/after/active_stage_reference/stage_center/_selection_parts/a_auction.py:46–54,90–114` normalizes the baseline, rejects nonpositive/unparseable/nonfinite values, leaves unknown `qmt_gap_pct` and `current_change_pct` null, and supplies a reason. The final daily percentage is written after `**card`, so the inherited generic last/open fallback cannot overwrite null with an apparent zero. A genuine 100→100 observation remains 0. The canonical selector is the same explicitly mapped after-image.

I verified that the positive 100→105 assertion runs through real imported `SourceResult`/`AcquisitionPlan`, the production builder facade, selector, `SelectionStore.publish`, a fresh `read_verified` call and the read-only consumer. It checks baseline 100 and both percentages 5 in the original envelope and persisted consumer response. Missing, null, empty, zero, negative, text, NaN, infinity and boolean baseline cases assert null plus the correct missing/invalid reason after storage. Missing auction price has a separate reason. The tampered-manifest case exercises actual rejection of changed persisted price evidence.

The persistence claim is specifically the existing verified-envelope contract. The historical support publisher stores the complete row in `selection_envelope` (`work/auction/frozen_test_support/handoff/v4-running-source-20261005/canonical/stage_center/_selection_parts/store_publication.py:116`); verification reads and checks that envelope (`.../store_verification.py:38`); the consumer deep-copies complete rows (`.../consumer.py:184`). The 12-column V1 CSV remains unchanged and does not itself contain the baseline. Its `lane_evidence` retains the reason. V2 nullable percentage decoding is covered for `None`, 5 and 0. An isolated old V1 CSV alone is not claimed to reconstruct the original price evidence.

The score call, coefficient implementation, clamp, stable descending sort and Top-10 boundary were not changed. Restoring a legitimate baseline necessarily changes the formula's input. The reviewed regression explicitly checks the synthetic −5/0/+5% ranking and unchanged tie behavior; the report openly records the score/rank effect. No real 171-row ranking or existing 10/8 selection artifact was recomputed.

The API result is three clearly labelled AST-only projection checks after actual store/consumer readback. These do not execute the full `create_app`, middleware or live HTTP endpoint. The real module-import tests use pinned historical support and an explicitly substituted 527-byte namespace helper; they cannot certify the current Stage dependency closure.

## 2. HK: monolithic owner, independent dates and strict lineage

The actual monolithic adapter accepts `eligibility_source_date` and forwards it as `expected_eligibility_source_date` only when distinct from the price signal date (`delivery/hk/after/active_producer_reference/domains/preselection_materializer.py:430–451`). Legacy equal-date reader signatures continue to work. The CLI independently accepts `--hk-signal-date` and `--hk-eligibility-source-date` and forwards them while A retains the original `signal_date` (`delivery/hk/after/active_producer_reference/ops/materialize_scheduled_preselection.py:117–129,194–195,262–267,296–297`).

The projection takes the security-master and D1 identities from the verified source objects. It preserves run, artifact, manifest and receipt hashes and the original timestamp, including microseconds and offset. The capture decoder is at `.../domains/preselection_materializer.py:412–427`; the split-date provenance projection and required-field/hash rejection are at `516–571`. It does not fabricate a new capture clock, loosen the strict Stage validator or add another data owner.

The positive fixture uses the frozen canonical security-master/HK publishers, their real verified reader, this complete monolithic adapter, real frozen pool storage and the exact unchanged active validator body. The actual CLI function also materializes the output. The assertions verify price date 20261007, eligibility date 20260930, target 20261008, original capture identity, 100 unique rows, stored-trio integrity and unchanged source bytes. A's independent date remains 20260930. Equal-date compatibility is separately covered.

Negative cases exercise stale provenance, all three source-trio tamper cases, absent verified fields and hashes, missing Stage provenance, stale row dates and wrong eligibility capture date. The active validator remains SHA `92e8fb2be06e6530c33f3cf2f5b44f29b0bcf7875e6a5902260f8be4c814f735`; its calendar/identity/capture checks at `baseline/source/active_stage_reference/stage_center/_runner_parts/hk_input_validation.py:127–235` were not changed. The baseline test still reproduces `HK D1 split-date eligibility provenance missing`.

This is a meaningful body/adapter/CLI/storage test, with explicit limits: the absent `_namespace` import is substituted in memory, and the shared reader/store dependencies are canonical test references rather than proven active-owner bytes. Unrelated A/research factories are named synthetic seams. The wrapped absent-source ENOENT remains a zero-row `CANNOT_CONFIRM` with the original error reason; the pre-existing classifier was not relabelled as a valid empty selection.

## 3. Release: exact guard bytes and recoverable partial failure

The installer requires the guard path/SHA in the recovery identity, final-plan writer artifacts and exact reviewer scope (`delivery/release/source/blocked_candidate_ops/api_candidate_install_r2.py:178–187,306–348`). Recovery's JSON identity requires the same fixed digest, and its receipt checker rejects missing pins, altered scope and supersets (`delivery/release/source/blocked_candidate_ops/api_candidate_recovery.py:60–87,185–238`). Both paths use `reviewed_guard_bytes` and `import_reviewed_guard` (`97–128`), which read a regular file without following its final symlink, hash its bytes and compile that same verified buffer. The test replacing the disk path after hashing confirms that replacement code is not executed.

The final reviewed guard digest is `1fd041a3da7f21893ecc70b9d4d0d79936b58cc884cbc17367711917ba798367`. I independently checked that both helper constants and the delivered guard file match it. Recovery checks the guard before service probes. No blanket rehash-to-approve behavior is introduced.

At `delivery/release/source/external_guard_reference/hk_calendar_candidate_cutover.py:452–469,567–575`, an install-link error followed by any restore-link `OSError` produces structured claim/recovery details and a bound drift receipt when receipt storage is available. The installer and recovery wrappers retain those details. If the receipt cannot be persisted, the error still identifies the claim and reports that failure rather than inventing a receipt digest.

`read_claim` and `restore_claim_no_clobber` (`472–518`) enforce the same-directory private claim shape, regular-file read and expected SHA, snapshot the verified bytes, preserve mode, fsync the snapshot and publish by exclusive hard link. The claim remains. Existing files and dangling symlinks are preserved, including a competitor appearing at the final link. Recovery validates the failed install/rollback phase, exact active path and both intended/retained digests before service access (`api_candidate_recovery.py:259–290`). It proves label absence and port freedom before restoring and follows the original baseline/candidate state machine before bootstrap (`293–372`).

The 25 focused tests cover both failed installation and failed rollback, structured wrapper propagation, drift, path redirection, tampering, symlink rejection, mode, competing paths and retry. The 26 supplied tests retain their original behavioral assertions while adding guard pins to the fixtures. Those 26 run with a synthetic small package because real Mac manifests/plists/inventory and old review receipts were not supplied. In particular, the named old FAIL-receipt test uses an explicit parser fixture; it does not reread the real historical failed review.

I additionally exercised two lifecycle edges independently:

1. A successful claim link followed by an injected ENOSPC when writing the restored receipt leaves the exact baseline/claim intact, performs no bootstrap, preserves the original failed-CAS receipt, and succeeds on a subsequent ordinary baseline recovery.
2. A double-link failure reached through the complete `recover_baseline` → `SystemRecoveryOps.atomic_restore` path returns the candidate claim/receipt; a retry restores that candidate snapshot, performs the original candidate-to-baseline transition, and bootstraps only the exact baseline through the fake service protocol.

These extra results are recorded in `logs/INDEPENDENT_EDGE_PROBES.json`. All actual filesystem/guard operations were in temporary directories. No host launchctl/lsof or real service recovery was performed. The external guard's unrelated HK apply/rollback command flows were not judged.

## 4. Pool: preserve A while supplementing exact target-date HK

I verified the reused app, domain facade and original test SHA identities against the stated frozen `4ad7cc52257b49470b3004ebfee9649af43189dd` after-images. There is no new pool implementation.

The four new scenarios run the original route/helper AST and domain/storage logic behind a local FastAPI test app. Local A contains two rows; the configured source intentionally contains a different A row and 100 synthetic HK rows. The positive case confirms that only the two local A rows survive, HK is supplemented, limit/offset affect the page rather than full counts, repeat reads retain the same input fingerprint, and original artifact/manifest/receipt bytes do not change. Wrong **target** date, tampered manifest SHA and tampered receipt SHA prevent supplementation while preserving A.

The route path reviewed is `delivery/pool/isolated/reference/apps/api/v35_api/app.py:4908–5053`, including the real pending-commit/read-lock/snapshot handling and merge of only the missing HK pool. Exact configured-pool checks are at `3910–3982`; pagination is computed from complete arrays in `_preselection_response_from_pools` before slicing. The tests do not replace the route body.

The harness supplies the absent namespace helper and a fixed catalog and does not execute full original `create_app`. I therefore confirm isolated route/storage regression, not current API deployment, the historical 178-A canary, complete Stage input integration, or strict HK producer/PIT qualification. The API display fallback and the unchanged strict Stage validator remain distinct contracts.

## Fresh execution evidence

Interpreter: `/workspace/scratch/29f34dd56853/issue28/work/test-venv/bin/python`, CPython 3.14.7 on Linux. Pytest runs used bytecode suppression, plugin autoload disabled and cache-provider disabled. Release tests used byte-identical copies under `work/review/release_tests`, with `RELEASE_SOURCE_ROOT` pointing to the delivered source; this kept their temporary directories away from the delivered test tree.

| Fresh check | Result | Review log |
| --- | --- | --- |
| Auction canonical candidate | 24 PASS | `logs/auction_canonical_after.log` |
| Auction active Stage candidate | 24 PASS | `logs/auction_active_after.log` |
| Auction active Stage baseline | 18 expected FAIL / 6 PASS | `logs/auction_active_before.log` |
| HK candidate | 19 PASS | `logs/hk_after.log` |
| HK four baseline probes | 2 expected FAIL / 2 PASS | `logs/hk_before.log` |
| Pool isolated route/storage | 4 PASS; one disclosed Starlette deprecation warning | `logs/pool.log` |
| Release focused candidate | 25 PASS | `logs/release_test_release_regressions.log` |
| Release supplied tests on candidate | 26 PASS with synthetic package | `logs/release_run_existing_suites.log` |
| Independent release lifecycle edges | 2 PASS, counted separately from the suites | `logs/INDEPENDENT_EDGE_PROBES.json` |

Auction's 24 cases are the same suite for two owners, not 48 different cases; each variant consists of 21 real module/storage cases and 3 AST API projections. Baseline auction failures include the positive 100→105 and missing/invalid-baseline assertions. Baseline HK failures are the unsupported eligibility keyword and unrecognized CLI options, not an unrelated infrastructure failure. I did not independently rerun the author's canonical auction baseline or release baseline suites; their old logs remain author evidence rather than fresh independent results.

Concrete replay entry points from the issue root:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTEST_ADDOPTS='-p no:cacheprovider' work/test-venv/bin/python delivery/auction/reproduce.py --repo-root work/auction/frozen_test_support --owner canonical --phase after --log-root work/review/replay-auction
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTEST_ADDOPTS='-p no:cacheprovider' work/test-venv/bin/python delivery/auction/reproduce.py --repo-root work/auction/frozen_test_support --owner active_stage_reference --phase after --log-root work/review/replay-auction
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTEST_ADDOPTS='-p no:cacheprovider' work/test-venv/bin/python delivery/hk/tests/run_focused.py --issue-root . --owner-root delivery/hk/after/active_producer_reference --support-root delivery/hk/test_support
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 work/test-venv/bin/python delivery/pool/isolated/run_route_tests.py
RELEASE_SOURCE_ROOT=delivery/release/source work/test-venv/bin/python -B work/review/release_tests/test_release_regressions.py
RELEASE_SOURCE_ROOT=delivery/release/source work/test-venv/bin/python -B work/review/release_tests/run_existing_suites.py
```

The precise commands actually executed and their return codes are in `INDEPENDENT_SUMMARY.json` and `logs/release_fresh_commands.json`. For the auction baseline change `--phase` to `before`; for the four HK baseline probes use `--owner-root baseline/source/active_producer_reference --baseline-focus`. The copied release scripts have the same SHA as the delivered scripts and can be recreated by copying `delivery/release/tests/*.py` to a temporary review directory.

## Byte identity and replay

`logs/INDEPENDENT_BYTE_AUDIT.json` contains the full reviewed after paths, SHA-256 values, sizes and patch hashes. All **27** source-manifest baseline files matched SHA-256, byte count and Git blob SHA-1. Both auction patches, the HK patch and the complete release patch passed `git apply --check`, forward after-image comparison and reverse preimage comparison in temporary copies. No baseline or candidate source was changed by this review.

Key reviewed business-source digests:

| Source identity | After SHA-256 |
| --- | --- |
| Auction canonical builder | `7fa71ee1a4b96f6f53d49467fcb296969104e851949234849fd256a5372d5725` |
| Auction active Stage builder | `409274a2adace19f22ef6d19cdbc7e5291b58fd9944d39239abbffd90ab1f6e4` |
| Auction selector, both explicit owner copies | `defb01fca7d0a067bf214e794810fac7d19fdbd3fbcd78b8263fe93603952e93` |
| HK active monolithic materializer | `521a66cd5018806197d99e40f7261f817345d3951761ccc280f89d25a8214110` |
| HK active materializer CLI | `9ef7d07fa3fafbb8a63637fe80edb2488e795f52a48baf2abaec135468d0acfe` |
| Release installer | `3ddeb297d36f7b825103b8462cd610a14613b73ef95f6940f5a93498339733d6` |
| Release recovery | `8a162ce38478c292bf811c827c7616909a91a23a2bb3a1f95c71f208f9a08741` |
| External release guard | `1fd041a3da7f21893ecc70b9d4d0d79936b58cc884cbc17367711917ba798367` |
| Reused pool API | `435dcedd3beb43bf4a0ccb35ff6fc033ba536a940990c36f5f23358f5492b590` |
| Reused pool domain | `f209ceb037515586883dc669d830fb44afcf778b67971951bde69c5eab8b67a0` |

Pinned test-support records were also checked independently: auction/HK support records and pool's 25 Git-blob-pinned files match their indices. `logs/SUPPORT_BYTE_CHECKS.json` records the exact checked bytes. Namespace/catalog seams remain labelled test support; matching their historical hashes is not proof that they are loaded by the active owners.

## Behavior explicitly declined to judge

| Behavior | Status / reason |
| --- | --- |
| Actual HK scheduler forwarding and loaded shared/store closure | `CANNOT_CONFIRM`; current-owner files and runtime identities are absent. |
| Genuine 10/7 price availability, 9/30 capture authenticity, historical PIT | `CANNOT_CONFIRM`; no original business trios/capture witnesses were inspected. |
| Mac Python 3.14.6, actual APFS/launchd/lsof recovery behavior | `NOT_RUN`; Linux file operations plus in-process service fakes were used. |
| Current full Stage/API dependency imports and complete repository suite | `NOT_RUN`; incomplete source slices and disclosed helper substitutions. |
| Full API create_app/startup/middleware, live 8873 endpoint/UI reload | `NOT_RUN`; API projections and isolated route HTTP tests have explicit reduced scope. |
| Real 171/178-row auction results, real 178-A/100-HK canary, immutable existing results | `NOT_RUN`; synthetic fixtures only; existing results were not overwritten. |
| Full Stage aggregation/candidate-input integration and real singleton selection | `NOT_RUN`; no Stage runner was executed. |
| Natural-slot validation or historical execution identity/PIT repair | `NOT_RUN`; no schedule, old receipt or timestamp was rewritten. |
| Existing A coverage/news quality/historical-close P2s | Still open as recorded in `delivery/OPEN_ITEMS.md:34–42`; outside these minimal deltas. |
| Unrelated full HK cutover CLI, manager/model/BUY/Vibe changes | Not reviewed or operated; no such change belongs to this candidate scope. |
| Installation, merge and deployment permission | Not issued; this document is a source review only and cannot satisfy the release installer's independent exact-package gate. |

`RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false; DEPLOYED=false`.
