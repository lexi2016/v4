# Writer handoff: US mapping natural scheduler fix, 2026-10-21

State: IMPLEMENTED / PREPARED, not independently accepted, not activated. PREPARED.json binds final local r4, source/config/manifests, commands and frozen-input checks. Controller owns review dispatch, Git sync, activation and natural verification. Writer performed no commit, push, service action, collection, model POST, or official business-state write.

## Frozen behavior covered

- Existing catalog/display list separation and catalog-placeholder exclusion reach the actual scheduler through exact accepted hunks, together with already accepted source provenance/blocker fields. The exact D-1 master can fill a partial owner dictionary without changing the frozen US owner.
- A fixed observed policy template fills only missing dated classification bindings. Exact-date pins win; corrupt SHA, late/unknown capture evidence or malformed explicit pins fail closed. The original 10/14 source date, captured time, three owner hashes, PARTIAL status, UNKNOWN source_asof and non-PIT meaning remain. The adapter refreshes only the precise frozen EXACT_DATE_BINDING_MISSING result; other frozen failures remain visible.
- PREOPEN retains an executed PARTIAL lane when evidence filtering accepts zero rows. It records prior run/input/coverage/gaps, row filter counts, source reasons and excluded evidence gaps. No prior pre-cutoff execution remains NOT_RUN. Verified subsets and inclusive cutoff keep the original gate.

The runtime parent and Git base differ. Canonical Git already held yesterday's wiring fixes. The new canonical diff contains three source files (native, source_bindings, service), two existing focused test files and this handoff. The actual scheduler overlay changes five allowed files. Its native history/TDX and source-binding history/TDX implementation remain the original scheduler bytes. Neither inputs file is copied wholesale from API/Git. RUNTIME_OVERLAY.diff is the exact runtime diff; OVERLAY_SPEC.json is the hash-guarded reproducible form.

## Writer checks and limitations

COMMANDS.json lists commands, outcomes and local log SHA. Real parent reproduction: 2 new-behavior failures, 1 existing override test pass. Actual r2 targeted run: 61 passed, 2 failed. Both failures reproduce identically against the unmodified actual parent: the retained parent calendar lacks next_session; the old native oversold fixture has COUNTS_MISMATCH before reaching freeze. These historical failures are preserved. R3 had 3/3 incremental tests, but independent review subsequently found two blocking edge cases (INDEPENDENT_REVIEW_R3.json). R4 fixes only explicit pin presence handling and optional reason metadata. R4 incremental verification passes 24/24; all other independently valid checks are reused. This is Writer evidence, not final acceptance.

The retained, independently reproduced r3 actual-input offline canary uses source run e6feeeb310bf40fda91e1561f285d908 and frozen input SHA 1488f9594fd952a607e92d5f7f628341805a83bf9c4377c34ad2a189d1685b58. All frozen US pin fields remain equal, including quote identity/session/capture time. It resolves the exact 10/20 master (692 identities), keeps the 10/14 classification (695 source items), produces 698 unique research rows and 1003 catalog dispositions with no synthetic legacy catalog paths. Counts: BENEFIT/RISK/CONFLICT0; OBSERVATION308 (including C_WATCH303 and SMALL_MOVE_WATCH5); UNMAPPED379; UNASSESSED11. Five medical stocks are OBSERVATION/C_MAPPING_OBSERVE_ONLY. No medical relation state changes; none of eight relations becomes ADOPTED. Formal target eligibility remains CANNOT_CONFIRM; strict V1 remains PAUSED_NOT_EXECUTED.

The actual prior PREOPEN source has 1063 rows: accepted0, incomplete-decision1040, missing-evidence1003, unverified-or-late-evidence60 (reason counts overlap). The isolated freeze records PARTIAL and retains exact SOURCE_AVAILABLE_AT_UNKNOWN and CONNECT_MEMBERSHIP_TARGET_EFFECTIVE_PERIOD_UNCONFIRMED gaps. Official input and source snapshot SHA remain unchanged. Raw plans, complete config, full canary summary and release bodies remain under ignored local_only.

Read-only parent/idle guard passed for PID72933 with the exact original cwd/config/plist, no active workbench attempt/child/socket and 16 finished dispatcher claims. It is point-in-time and must run again at actual activation. Controller accepted the single existing .DS_Store discrepancy in the historical parent manifest; it is preserved exactly. See DEPLOYMENT_PLAN.md.

## Independent review

Use the final candidate import root, not the canonical Git tree, to inspect runtime behavior. Run only the r4 affected scope (24 cases); the full 61 passing ordinary cases and two historical failures were independently established on r3 and are retained:

    PYTHONDONTWRITEBYTECODE=1 '/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python' docs/handoffs/us_mapping_natural_fix_20261021/run_checks.py --code-root '/Users/lexi/.codex/worktrees/us-mapping-natural-fix/v4_app/docs/handoffs/us_mapping_natural_fix_20261021/local_only/us-mapping-natural-scheduler-20261021-r4/app' --review-fixes --basetemp=/tmp/v4-natural-independent-r4-review

The retained frozen replay command is COMMANDS.json entry r3-actual-frozen-replay; no duplicate full frozen replay was run for r4. Independent review reproduced the same r3 summary SHA. R4 only changes the two malformed-input branches covered by incremental tests. It blocks network socket connections and never calls submit/tick/collection/model execution. Source/context is read-only; only the new isolated freeze is persisted.

Review PREPARED.json and REVIEW_FIXES_R4.diff with source/test hashes. R4 differs from the immutable r3 app in exactly source_bindings.py and service.py; the other 939 physical files are unchanged. R3 remains REVIEWED_FAIL and is never relabeled as accepted. The independent r3 ordinary-path canary is reused only within its recorded scope.

## Required remaining states

Independent Reviewer receipt, controller Git remote readback, scheduler activation/loaded-runtime identity, first actual post-release natural execution, and next trading-day09:25 source/filter lineage remain pending. Today's existing09:25 result must not be rewritten. DEPLOYMENT_PLAN.md gives preparation, parent/idle guards, lifecycle and conditional rollback. A changed/bad source pin remains CANNOT_CONFIRM. No source, membership, medical relation or selection threshold may be promoted to close a gap.

Initial direct pytest/helper imports generated previously absent untracked canonical __pycache__ files. Controller explicitly instructed retaining these test byproducts and excluding them from Git; no cache is part of the source/overlay acceptance scope.

## R4 review repair

R3-P2-1: all supported explicit entry points now distinguish key absent from key present with malformed value. Owner, top-level date and nested US date null/list/scalar values fail closed before any lower-priority pin or template. An absent nested key can still use the fixed template. R3-P2-2: diagnostic reasons accept lists of strings and an optional string reason; null, scalars and non-string list members are ignored for aggregation and cannot crash freeze. Evidence and cutoff acceptance conditions are unchanged.

Fixed reproduction on immutable r3: 11 failures and 7 passing controls. Final r4 affected suite: 24 passed. The initial red test collection missed a pytest import, was corrected before the successful reproduction, and is retained in the command ledger. No full-suite rerun, model/network call, release activation or official state write occurred in this repair round. R4 still requires independent incremental acceptance.
