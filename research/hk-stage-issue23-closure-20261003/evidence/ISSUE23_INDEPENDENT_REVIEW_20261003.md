# Issue23 independent review receipt

Reviewer: independent read-only reviewer identity. Scope: the Issue23 frozen SCOPE.md. No source files, fixtures, pins, candidate packages, or services were changed by this review.

## Diff and SHA

The frozen handoff preimages match their declared SHAs:

- research/mac-source-handoff-20260930/source/canonical/ops/stage_service_overlay_contract.py: a9ac2c1270b349152eaa56ca305aa42ab48abe2f43515f452a691e572ba24681
- research/mac-source-handoff-20260930/source/tests/tests/test_stage_service_overlay_closure.py: 3877ce2c865d6bea671e0982800b55656d978c78697e43553f048643736bbefd

A unified diff against those preimages shows only the two intended runner SHA substitutions: 648fe7af52df1b4eba31802361f9af2d03decbbebb3286ecc7a5dc0b06523205 to 7e6e958df4d64a8f7324d96bb09548f29c9da3ba206a4548420fa021da47d34f, once in each allowed file. Current file SHAs match the handoff post-patch values:

- ops/stage_service_overlay_contract.py: 54e0d66e907d296a56a5886e9e7fc1920d22461a9a6a4b88423c0862708a5f91
- tests/test_stage_service_overlay_closure.py: 2ad2e98b6784eb4beba9f50a1a7d01073183272b24ff36b4c3f16d3d56cfa850
- stage_center/runner.py: 7e6e958df4d64a8f7324d96bb09548f29c9da3ba206a4548420fa021da47d34f

Both target source files are untracked in Git; Git has no tracked or HEAD versions. The diff above is verified against the supplied frozen handoff preimages, not a Git commit.

## Independent regression evidence

Command, using the service Python and an isolated pytest temp root:

    /Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python -B -m pytest -q -p no:cacheprovider --basetemp=/tmp/issue23-review-20261003-a1 tests/test_stage_service_overlay_closure.py::test_complete_strict_cohort_is_packaged_with_exact_source_identity --tb=short

Result: one failed in 0.05s. At tests/test_stage_service_overlay_closure.py:144, _copy_strict_source compares repository stage_center/consumer.py bytes with the frozen pin: expected 9e3a864c74eaec6c616b911b09c167c8cb407db8435343c1b522de4f4c9459eb; actual 865c2ea8183e5e6aeb9145ce2bfbb3e5b442825904b14c47fe024593a9205489.

This is actual workspace source drift, not fixture or monkeypatch preparation. For closure-map paths the helper reads REPOSITORY_ROOT / relative at lines 142-147; tests/fixtures/stage_overlay is used only for non-closure entries at lines 149-154. The monkeypatch at lines 201-207 changes only offline Git and runtime-probe functions. Current stage_center/consumer.py is Git-modified and its source diff contains substantive consumer changes. Its current SHA exactly matches the reported actual value.

One mechanical pass over all 50 entries in STAGE_SERVICE_RELEASE_CLOSURE_SHA256 found 4 mismatches and no missing files:

| Path | Expected | Actual |
|---|---|---|
| ops/_run_stage_center_nodes_parts/node_entry.py | 54defb0f45adbafcf4b661611f41d0b43d89abf492d89d587c28962eff9b36fe | 2343cd5e250aaa05acc698ba2daf34220f13ffb5543c655df799fdb3bd7fe464 |
| ops/_run_stage_center_nodes_parts/stage_dispatch.py | df6221a177d82f0fd683896b3ef21cd66cd7a8a4b6c6c8b95571f277108d52fe | 06548184a4b09b0ae94053f2308eefb3bf5c31afc9f04abaeb805db7cebe8adb |
| stage_center/consumer.py | 9e3a864c74eaec6c616b911b09c167c8cb407db8435343c1b522de4f4c9459eb | 865c2ea8183e5e6aeb9145ce2bfbb3e5b442825904b14c47fe024593a9205489 |
| domains/task_status.py | 047cfb2b6a8c165857b2841f137a86c9587a1a6e81199efdf71d508d05589300 | 42a355b113a07b6d0c6c42b995ec9a123ca8608e74f8a6d11258a6bd130ebb97 |

No other closure pin differs; the runner pin now matches the source.

## Runner-only overlay behavior

In ops/stage_service_overlay_contract.py:168-187, closure SHA validation checks only paths selected in overlay_paths. At lines 190-215, strict publication requires the complete nine-file strict cohort, which includes stage_center/consumer.py. In ops/build_release_candidate_stage.py:580-618, an explicit overlay uses the active effective config unless it selects stage_center_tick_config.json; strict mode then rejects an incomplete cohort before closure hashes run.

Therefore an explicit runner-only overlay under an effective non-strict config is not blocked by the consumer pin itself. A strict effective config blocks a runner-only overlay through the complete-cohort rule and requires consumer as a cohort member. An automatic strict overlay selects the full overlay closure and checks its closure pins. No candidate or exact build invocation/receipt exists in reviewed evidence, so the intended candidate effective config and final acceptance are CANNOT_CONFIRM.

## Verdict

- Diff scope and the two post-patch SHAs: PASS.
- P0: none observed in the two-line pin patch.
- P1: no newly introduced behavioral or security defect established; runtime behavior remains CANNOT_CONFIRM because no candidate or runtime verification occurred.
- P2: frozen PASS signal is not met. The independently rerun strict closure test fails on current workspace source; the mechanical closure-map check found four exact mismatches above. Do not refresh those pins within Issue23 frozen scope.
- REVIEWED: FAIL for batch acceptance. TESTED: one focused test independently run and failed. Full closure suite: not rerun by reviewer. Candidate build, service switch, API/UI, and natural behavior: not performed and CANNOT_CONFIRM.

Minimum Chat issue: confirm which source state is authoritative for the strict closure. The two runner pin edits are exact, but strict closure currently contains four out-of-scope source/pin mismatches, so frozen acceptance cannot pass on this workspace. This review did not change or refresh any additional pin.
