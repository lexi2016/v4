# Issue #44 — bounded patch and review record

## Scope
The patch changes only the product-store read bound at the two existing read sites in
`CaptureStore.save_product`: the existing-object/SHA comparison and the post-write
readback. The local contract is 256 MiB, matching the already-existing downstream
consumer bound documented in Issue #44. It does not change `SafeRoot` defaults.

## Invariants preserved by inspection
- JSON encoding and SHA-256 identity are unchanged.
- Immutable content-addressed path `products/<sha256>.json` is unchanged.
- Existing owner/source receipt fields are unchanged.
- Exclusive-owner guard, require-absent creation, conflict errors and readback equality remain.
- No truncation, retry, recapture, model execution, PIT relaxation, or trading-gate changes.

## Reviewer conclusion
Static review: **narrow patch is consistent with the diagnosed failure and scope**. It applies the same explicit bound to both read branches and leaves the shared I/O safety default unchanged.

Independent second-person/agent review: **NOT RUN** (no independent reviewer execution is available in this session). This must not be represented as an independent PASS.

## Verification status
- Patch syntax/context: drafted against the exact `active-source/v4/manager_workbench/inputs/capture_store.py` snapshot from fixed commit `5f92721a3c76619cee4ae254b03167b0ae595cd0`.
- Targeted pytest: **NOT RUN against the actual V4 runtime**; this session has no checked-out runtime tree/environment.
- Local deployment / service restart: NOT RUN.
- New model input / actual model process start: NOT RUN.
- New-job API/UI result binding: NOT RUN.
- Old UI candidates remain old results, not success evidence.

## Required next verification
Apply `capture_store_size_contract.patch` to the canonical checkout whose source SHA matches the Issue #44 runtime binding, run `test_capture_product_size_contract.py` plus existing capture-store tests, then have an independent reviewer inspect the exact resulting diff. Only after those pass should the local runtime be deployed and a single new task be triggered using the existing cached capture product. Preserve the original cutoff/date and keep research-only/trading gates unchanged.
