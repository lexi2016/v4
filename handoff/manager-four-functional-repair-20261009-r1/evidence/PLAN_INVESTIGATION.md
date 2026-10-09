# Plan owner → saved product → GET readback investigation

## Fixed input and evidence boundary

- Package repository: `lexi2016/v4`, pinned commit `74478a0e62be215c8527ccc9a14b89b51042d014`.
- Editable target: only `package/code/r2_chat_patch_target` bytes, subsequently copied to the isolated application assembly.
- The R1 announcement, R3 20260930, and actual-owner 20261009 source groups remain separate references. No reference bytes are silently substituted for the target.
- The four evidence JSON files do not establish four code bugs. The observed plan identity mismatch (`5df99128…` saved vs. `7c5d9f18…` current) correctly returns `STALE_INPUTS_CHANGED`.
- Real Mac source/root/state, owner rerun, deployment, live API/UI and natural execution remain `CANNOT_CONFIRM` / `NOT_RUN`.

## Existing contract traced in R2

1. `ManagerResearchJobService.refresh_workspace_plan` forwards the same service instance, store, reader fields, clock and `workspace_date_bindings` into the original workspace owner.
2. `workspace.get_workspace(... include_saved=False)` reads original owners and readers, applies the existing HK Connect gate, screen, announcement and US projections, and computes the input identity.
3. The original Connect `gate_workspace` adds `scope.identity` and calendar applicability to input identity. Research material diagnostics also bind the scope identity. No new identity algorithm is needed.
4. `_daily_mapping_plan_reference` consumes the existing mapping product only when its original status is consumable and its `generated_at` precedes the plan cutoff. Its artifact SHA is included in the plan identity. The latest run cannot be replaced by an invented US mapping algorithm.
5. The original owner persists an immutable run product plus same-date latest product, seals the owner attempt, validates the persisted product, and validates its exact terminal attempt before returning.
6. Dynamic GET reuses the saved cutoff only for an exact full date binding. It still re-reads all owner inputs. `_readback_plan` compares input identity, semantic version, cutoff and date bindings; `verified_plan_attempt` validates the exact run journal. A changed identity cannot be consumed.
7. GET must remain read-only. `CURRENT` means that the sealed research product and its owner attempt are currently verifiable. A `PARTIAL` owner result with missing independent channels is not a completed selection or a coverage-backed empty market.

## Confirmed minimal repairs

The current R2 workspace directly calls `read_scope(context)`. Root and HK-reader work add an explicit per-service Connect authority binding using the existing five owner parameters. The workspace must forward `getattr(service, '_workspace_connect_binding', None)` to this original reader. The reader's existing scope identity then propagates naturally into the plan identity. Explicit empty/invalid bindings fail closed; no environment fallback is allowed for an explicitly supplied binding.

The plan assignment changed exactly this one call in `workspace.py`. A test with an explicitly invalid service binding first failed because the unpatched workspace reported ambient `ROOT_NOT_BOUND` instead of the original reader's `ROOT_INVALID`. After the one-line forwarding change, it passed. No plan algorithm, persistence, SHA validation, cutoff or stale comparison was changed.

HK-reader investigation separately confirmed a V1/V2 metadata mismatch in `connect_selection.filter_cards`: the old function removed `available_at` but retained the V2 reader's changing `read_at`. The filtered material-discovery cards enter `build_workspace` input identity. Thus nonempty input cards could change plan identity while the source artifact and persisted capture/publication timestamps were unchanged. HK-reader's fix removes only `read_at` and preserves persisted `available_at`.

This defect is reproduced in isolated synthetic R2 code. It is **not** proof that this was the cause of the saved/current identity difference in the real 10/09 receipt; the original owner payload/state is not available here.

## Executed deterministic checks

- Same manager store and original US reader: original mapping owner → original plan owner → exact persisted run/product/attempt SHA → router GET `CURRENT`.
- Unchanged source after wall-clock drift stays `CURRENT`; GET does not write manager state or call producers.
- Changed original source or Connect authority identity returns `STALE_INPUTS_CHANGED`, `consumed=false`.
- Calling the original owners again with the current valid inputs creates a new verifiable product; subsequent GET becomes `CURRENT`.
- Different target/selection/publication binding cannot consume the saved dynamic product.
- Tampered product/attempt or missing exact owner attempt cannot be consumed; security flags remain unchanged.
- Nonempty original archive → original exact master → native issuer classifier → Connect card → original plan owner: changing only V2 observation `read_at` keeps the same input identity and `CURRENT`.
- For that nonempty card, changing the consistently sealed publication's persisted `available_at` changes plan input identity and preserves `STALE_INPUTS_CHANGED`, even when codes, artifact SHA, run ID and existing scope identity are unchanged.

The regression fixtures are explicitly synthetic and isolated. Router-only checks must not be described as actual `create_app` injection tests; root owns that separate verification.

The nonempty archive fixture uses `domains.research.build_research_archive`, `ResearchArchiveStore.publish(mode='REPLAY')`, `ResearchLaneSource`, `publish_hk_security_master`, and the original classifier. No source reader, material classifier, product builder or plan owner is replaced by a test implementation. The clocks and source file locations are explicitly fixture-bound. Missing independent channels and archive acquisition-time gaps stay visible; one synthetic card is not a fully accepted selection.

## Results

Command from `four_gaps/app`:

```text
/workspace/scratch/21926b793c00/four_gaps/test_env/bin/python -m pytest -q tests/test_manager_four_plan_owner_readback.py --junitxml=../plan/plan_regressions.xml
```

Observed: **13 passed**, exit **0**, **2.51 seconds**. One existing Starlette TestClient/httpx deprecation warning remains. Raw output is `plan/green_plan_regressions.log`; JUnit is `plan/plan_regressions.xml`.

An independent counterfactual process loaded only the exact fixed R2 `filter_cards` implementation while retaining the current real readers and owners. The nonempty plan stability test then failed with different input identities after `read_at` advanced. No shared production file was reverted or overwritten. The explicit counterfactual log is `plan/red_nonempty_plan_r2_filter_counterfactual.log`; it is not a live-process receipt or an all-R2 application run.

Earlier setup attempts are not product failures: the default Python 3.12 environment lacked Starlette; reusing a broader prior test fixture introduced an unavailable optional `ops.daily_materialize` import; a first source-change fixture used immutable `publish` rather than the owner's actual CAS `replace`. Those fixture/environment issues were corrected without changing production source behavior.

The project-wide suite and actual `create_app` integration are coordinated by the root task; this subtask does not claim their status.

## Additional observations, outside this repair unless later reproduced and admitted

- Scheduled idempotency compares input/semantic identity but does not explicitly compare `date_bindings`, unlike dynamic readback.
- Historical GET calls `read_history(service, date)` before setting the requested date binding. This requires separate date-query analysis before claiming parity with dynamic GET.
- Dynamic readback validates the exact saved attempt but overlays the latest attempt for runtime reporting; this can intentionally expose a later failed owner. Do not change it without deciding which displayed field is intended to report which run.

Real owner state, Mac integration, live API/UI, deployment and natural-run acceptance remain unverified.
