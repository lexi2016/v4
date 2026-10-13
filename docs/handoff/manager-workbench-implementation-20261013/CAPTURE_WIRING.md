# Capture wiring candidate (not activated)

The API submits an initial research task immediately. With capture explicitly enabled, it also submits a separate persisted `CAPTURE_MATERIAL` task and exposes its `/runs/{id}` progress link in the initial task's execution references. The initial task may correctly publish an unassessed version. Capture completion publishes a validated immutable binding at its actual completion cutoff, then submits an independent announcement research task when article material, qualification provenance, model, prompt or rules identity changes. Original submission/window times remain recorded. PREOPEN retains 09:25 and never joins acquisition/model work.

Configuration defaults to disabled. `capture_root` holds original products/cache, `capture_lease_root` holds the source-wide lease, and derived `state_root` holds jobs, bindings and plans. Root overlap with existing owners is rejected. Both processes must use the same configured roots and explicitly granted token. Construction never grants a lease; revoked ownership cannot fall back to the former collector. API/scheduler share persisted minute-slot claims and an acquisition lock. The lease is also checked while publishing/submitting derived work. Acquisition and research pools close in that order, including CLI exceptions.

NEXT_DAY target is the next HK session, while publication dates and the original cutoff remain on the source day. The approved default window is the original two completed HK-session window, open at the first session close and closed at the submitted cutoff. Full raw catalogues and excluded rows remain in the owner product. Mirror source timing remains CANNOT_CONFIRM for official PIT. Source failures remain gaps and cannot become a verified zero selection.

Incremental binding retains each unchanged complete article's previously saved body product through `article_material_refs`. Every referenced product, page SHA, source owner/URL, date/window and body is checked again. The newest full catalogue and product are preserved separately. Matching an old article requires unchanged original listing row, owner, complete body, source page SHA/owner/URL/artifact and gaps. Its previously committed source SHA, availability and evidence identity are then reused as actual input, rather than replacing the new product's SHA. Changed qualification or semantic input identities force reassessment. Exact task identities have a cross-job/process immutable success cache and claim lock; failures cannot overwrite success. The CodexExecutor and isolation profile are unchanged.

The N+1 regression changes observed clock, submitted cutoff, catalogue request SHA, catalogue raw SHA and availability. It confirms that the raw new product's old article SHA changes with listing provenance, while Native consumes the explicitly referenced prior body evidence. Only the newly added article calls Reader/Reviewer. Separate tests require changed owner/ref/prompt identities to miss cache, and qualification source reissue to reassess unchanged article bodies.

## Isolated preparation / capture-only helper

Use the existing Python environment with `PYTHONPATH=.` from this worktree:

```sh
python docs/handoff/manager-workbench-implementation-20261013/capture_wiring_helper.py \
  --config /absolute/isolated/config.json --isolated-root /absolute/isolated \
  --target 20261013 --phase RETROSPECTIVE --cutoff '2026-10-13T14:00:00+08:00'
```

Default preparation performs zero network/model calls, writes and lease grants. All three writable roots must be descendants of the explicit isolated root. A separately authorized real capture can add `--execute-collect --allow-network --max-bodies 1`; it requires an already granted lease, captures the full approved date window, publishes/readbacks at actual completion time, and still invokes no model. The Writer has not executed that network path. The existing daily-only parent canary is distinct evidence and is not substituted for complete production-window input.

For an isolated API candidate, retain the existing manager binding/factory and launch helper; inject this validated config with source roots read-only and all new roots isolated. Do not change V5/V6. The subsequent V7 release closure must include `_vendor/DEPENDENCY_MANIFEST.json` and `licenses/pypdf-6.10.0-LICENSE` as well as Python vendor files, excluding `__pycache__`; unchanged frontend assets may be reused by SHA.

## Activation and rollback boundary

No formal lease, binding, plist, service, network capture or model run was activated in this batch. After independent review, formal cutover must first remove the former API acquisition write routes and exclude the former scheduler hook, prove known writers stopped, then explicitly grant the shared source lease and enable only the new binding. Preserve existing shared producers and US digest. Rollback first disables/revokes new acquisition and drains its capture/research pools; restore the complete prior API/scheduler/config together before enabling any former collector. Keep the new immutable cache/history for audit; do not overwrite prior successful plans or resume both owners together.

Parent real source receipts prove actual protocol/body capture only. This wiring is tested with injected transport and simulated model receipts. Real full-window wiring, real incremental model canary, V7 API/UI, formal activation and natural-slot behavior remain NOT_RUN for this batch.
