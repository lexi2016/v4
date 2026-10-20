# US_MAPPING wiring candidate, 2026-10-20

Status: PREPARED by the sole Writer; independent review and deployment are pending.

The three source files were byte-identical between worktree baseline `e24a0f2bc038aed9afd1117b07bf1cd884ff4e46` and active API release `announcement-transport-recovery-20261020-r6` before this patch. `PREPARED.json` records exact before/after SHA-256 and the allowlist. No runtime, Git, service, scheduler, provider, authoritative data, or frontend writes were made by the Writer.

Changes:

- Keep source-relation rows separate from display catalog/factor rows; catalog data continues through its own original provenance-aware projection.
- Retain source owner/SHA/session on relationship rows and emit actual missing-source/relation/membership diagnostics. A valid monthly research pool can be evaluated while formal target eligibility stays CANNOT_CONFIRM.
- When the US-close handoff has partial owner bindings, bind only its missing exact-date security master. Preserve every existing pin; retain date, cutoff, artifact SHA and identity checks.

Strict V1 remains PAUSED_NOT_EXECUTED. Numeric rules, relation grades, ETF background-only policy, catalog applicability, research/PIT boundaries, BUY safety and orders are unchanged. The existing test that expected a catalog placeholder to generate an invalid legacy C path now expects separate catalog retention and no synthetic C path.

## Writer validation

53 focused tests passed. The new boundary canaries initially gave 6 failures / 3 passes, reproducing the missing source fields, catalog aliasing and missing master binding. A test fixture was then corrected to include the existing required production safety flag; final guards include tampered master bytes, late capture and wrong date.

A further 37-test old diagnostic/priority/display set gave 28 passes / 9 failures. Identical test source against unmodified active r6 code gave the same 28 passes / 9 failures, each failing at US_MAPPING_EXACT_DATE_BINDING_MISSING. These old fixture failures are preserved, not expanded into this repair.

Run from the candidate worktree:

```sh
PYTHONDONTWRITEBYTECODE=1 '/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python' -m pytest -q tests/manager_workbench/runtime/test_us_mapping_wiring.py tests/manager_workbench/engines/test_us_mapping.py tests/manager_workbench/runtime/test_strict_us_selection.py --basetemp=/tmp/v4-us-mapping-wiring-review-focused
```

Use a new empty `--basetemp`; the first invocation without it encountered unrelated historical pytest temporary-directory cleanup permissions. No historical temporary paths were changed.

## Frozen offline replay

The input is the actual saved derivative `3f281b06fc2723809a57a4b42a04dc727d9cb9bc99cc8bc8800f84676fcc87c2`, anchored to run `52d6d87a1fe547a484b189448d0ddfb7` (US20261019, HK price20261016, target20261020). `replay.py` blocks network and calls only the deterministic lane plus the existing read-only exact-date master loader. It does not submit a job or load HK history. Raw derivatives remain outside the source tree under `/tmp` and must not be committed.

| Replay | BENEFIT | RISK | OBSERVATION | UNMAPPED | UNASSESSED | Identity ready/gap | Fake catalog C paths |
| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| Active r6, original frozen batch | 0 | 0 | 0 | 31 | 667 | 0 / 698 | 1003 |
| Candidate, original frozen batch | 5 | 0 | 3 | 33 | 657 | 0 / 698 | 0 |
| Candidate, existing HK16 master added | 5 | 0 | 303 | 379 | 11 | 690 / 8 | 0 |

Every replay retains 698 unique monthly stocks and 1003 unique catalog relation IDs. Catalog candidate qualifications remain 218 DATED_WEAK_PEER and 192 PENDING_REVIEW, with no adopted/active transmission and no signed HK return. Nonzero counts are not an acceptance criterion. The five BENEFIT rows are daily research mappings, not strict selections.

The master-enriched run deliberately has a different input SHA. The only added owner is the existing HK16 security master; input evidence references and industry identity derive from that owner. No quote, relationship, monthly membership, catalog source pin or source price changed. Exact original/new identities and remaining blockers are in PREPARED.json.

Reproduce baseline by setting `--code-root` to the recorded active r6 root and omitting `--bind-master --config`. Reproduce candidate without master by omitting those flags against the worktree. The output path must be a fresh directory outside the code root:

```sh
PYTHONDONTWRITEBYTECODE=1 '/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python' docs/handoffs/us_mapping_wiring_20261020/replay.py --code-root /Users/lexi/.codex/worktrees/us-mapping-wiring/v4_app --input '/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_workbench/manager_workbench/input_snapshots/3f281b06fc2723809a57a4b42a04dc727d9cb9bc99cc8bc8800f84676fcc87c2.json' --snapshot '/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_workbench/manager_workbench/snapshots/52d6d87a1fe547a484b189448d0ddfb7.json' --bind-master --config '/Users/lexi/Library/Application Support/com.lexi.v4.local/config/us-industry-observed-api-20261018-r1.json' --output /tmp/v4-us-mapping-wiring-review-replay
```

## Candidate deployment application plan

After independent Reviewer acceptance, the separate deployment owner must re-freeze the then-current active release and check these three files against the recorded before SHA. Apply only the three source edits to that release's complete preserved dependency tree. Do not deploy the worktree wholesale or replace unrelated calendar/announcement changes. If the three-file baseline drifted, stop and compare the scoped diff before applying.

Replaying the old job/checkpoint alone preserves the old missing-master input and produces only the original-input candidate result. Publish a new uniquely identified derived input/run through the existing snapshot validation/save/API contract if the accepted master-enriched result is to be shown. Keep old run/checkpoints intact. Read back saved run identity, input SHA, source SHA, 698/1003 completeness, counts, strict pause and safety; then verify that the API and reloaded browser reference that same new run. Never label the offline lane file as deployed/API/UI verified. Natural-slot verification is not established by this offline replay.
