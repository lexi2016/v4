# Backend repair candidate — offline results

**Status: `PROPOSAL_ONLY / LIVE_API_UI_NOT_RUN`.** The isolated backend regression suite passes **35 tests**. The same suite against the immutable before snapshot produces **17 assertion failures, no errors**, including the global-manifest counterfactual. This does not establish the unique historical live root cause or constitute deployed API/UI acceptance.

## What changed

The repair is confined to `v4/manager_research/workspace.py`, `workspace_projection.py`, and a new `workspace_identity.py` helper. The exact source preimages for `existing_materials.py` and `infrastructure/research_lane_source.py` were inspected and remain unchanged.

The helper makes a semantic copy only at declared `source_refs` / `input_bindings` locations. It removes only `manifest_sha256` when the reference has the complete original research-owner shape: verified owner/source ID, absolute source root, real source date, exact archive/hourly payload and receipt paths, supported mode/slot, valid payload and receipt SHAs, the expected manifest path, and consistent research-only flags. An explicitly supplied manifest-entry SHA must equal the payload SHA. The original source binding already gets its payload SHA directly from that exact manifest entry.

Unknown, incomplete, malformed, or unsafe binding shapes retain the whole manifest fingerprint. This grants them no new compatibility; the original source readers continue to reject missing/tampered exact artifacts. The generic `digest` function is unchanged, so product seals and saved-plan verification still cover the complete original data.

Every field other than the eligible global fingerprint stays sensitive. Original `source_row`, `original_source_row`, and literal content are opaque to normalization, including binding-shaped objects quoted inside source content. The raw material/card/result objects are retained with the complete manifest provenance.

### Complete identity chain

The main projection now hashes the semantic copy and records component digests. The relation-material extension uses the same interpretation for both selection materials and relation cards. The research-attention extension also uses the semantic card digest.

The original attention projector has internal hashes of evidence cards. Its current deployed source SHA is not proved by the uploaded evidence, so this patch does not replace that module. `workspace.py` calls the original pure projector normally and retains its complete business output. When eligible provenance exists, it makes one additional pure call on the semantic copy and uses only that call's `input_identity`. A failure in that computation propagates; there is no successful-identity fallback. Deadline checkpoints surround the additional call.

The outer identity keeps all original contributions and admission rules in their original order: gated projection, extended research attention, announcement selection input, optional reviewed-announcement input, optional announcement product SHA, optional exact US payload SHA, and the daily mapping artifact identities admitted by the existing cutoff function. Tests change each contribution and verify a changed final identity. The Connect and daily mapping guards themselves are unchanged.

### New plans and historical plans

The semantic contract is explicitly versioned as `CONSUMED_RESEARCH_ARTIFACTS_V1`. The projection identity includes that version. Dynamic readback and the scheduled reuse check also require equal `input_identity_version` values.

Existing sealed plans are not migrated, rewritten, assigned a replacement identity, or forced to `CURRENT`. A historical plan created under the previous contract can require a fresh authorized owner plan. Read-only GET still rereads current owners and applies all existing date, cutoff, product-seal, semantic-version, and exact owner-attempt checks.

## Bounded diagnostics

New workspaces record `input_identity_components` with a versioned schema and a fixed collection of projection, attention, and outer component digests. Validation permits at most 32 component entries, each with a bounded identifier and SHA256 value.

`plan_product.input_identity_diagnostics` compares the sealed saved component evidence with the current read. It exposes `UNCHANGED`, `CHANGED`, or `CANNOT_CONFIRM`, a bounded reason code, the saved/current identity and version, a total changed-component count, and at most 16 changed component rows. Each row carries only a component name and saved/current SHA256 values. No raw articles, raw paths, or source content are included. Truncation is explicit.

Historical plans lacking component evidence return `CANNOT_CONFIRM` for attribution. Mismatched, malformed, or internally inconsistent diagnostic evidence cannot change the consumption decision. Diagnostics never authorize a saved plan.

## Actual verification

The runtime is Python 3.12.14 on Linux. No packages were installed or user environment changed. Test support is drawn from the fixed repository snapshot, with provenance in `reports/test_support_sources.json` and `reports/backend.support_sources.json`. These support files are **test-only; their deployed identity is unverified**. They are not production patch files.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=candidate:test_support/upstream \
  python -m unittest discover -s tests -p 'test_*.py' -v
```

**Actual result: 35 tests passed, 0 failures, 0 errors**, recorded in `reports/backend.final.unittest.log`.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=baseline:test_support/upstream \
  python -m unittest discover -s tests -p 'test_*.py' -v
```

**Actual before result: 35 tests ran, 17 assertion failures, 0 errors**, recorded in `reports/backend.final.red.log`. Earlier focused RED/GREEN logs preserve the incremental sequence. The initial missing-dependency bootstrap errors are separately recorded in `backend.bootstrap.log` and are not counted as regression RED proof.

| Group | Tests | Verified behavior |
|---|---:|---|
| Projection | 9 | Global-only invariance; content, availability, source/date/path/payload/receipt sensitivity; complete versus invalid bindings; versioned components; generic seals unchanged |
| Relation extension | 2 | Material and relation-card provenance normalization with raw content retained |
| Attention | 5 | Global-only invariance through material cards and stock evidence; identical raw business output/provenance; receipt/time sensitivity; failed semantic projection propagates |
| Outer identity | 3 | Every outer contribution and optional admission remains effective; global-only same-run/product readback |
| Saved-plan readback | 9 | Repeated `CURRENT` reads keep exact saved bytes; changed material remains stale; bounded/legacy/invalid diagnostics; version mismatch; missing attempt, tampered product, exact date/cutoff guards |
| Original source guards | 7 | Real local exact archive reads; unrelated registry update; tampered payload/receipt/entry, missing receipt, exact-date mismatch; valid changed consumed payload |

The source-guard tests use temporary JSON fixtures, the original `ResearchArchiveStore.read_exact`, the exact `ResearchLaneSource`, and the exact `existing_materials._read_archive`. They do not mock these guards or call a live owner. The plan tests use a local filesystem transport fixture and the production `_read_plan`, `validate_attempt`, `verified_plan_attempt`, and `_readback_plan` functions. Fixture receipts and products are explicitly synthetic and are not evidence for any live run.

All three modified/new Python runtime files also compile successfully. The full external repository suite, real Manager service, Mac owner, API, browser, deployment, and natural-session gates were not executed; they remain `NOT_RUN`.

### Independent review: malformed mode

The independent integration review identified that an unhashable `mode` such as `[]` raised `TypeError` during set membership testing. This shape is not emitted by the original owner reader, but contradicted the helper's conservative malformed-shape contract. A regression subcase was added to the existing invalid-binding test before changing runtime code.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=candidate:test_support/upstream \
  python -m unittest discover -s tests -p test_backend_identity.py \
  -k incomplete_or_invalid -v
```

The actual focused RED was **1 test with 1 error**, specifically the reproduced `TypeError: unhashable type: 'list'` in `_complete_research_binding`, recorded in `reports/backend.red.malformed_mode.log`. This is a reproduced runtime defect, not a dependency bootstrap error. The repair adds a string type check before mode membership testing. The malformed binding now retains its complete fingerprint and remains identity-sensitive. The final full suite was rerun after this change: **35/35 passed**, including the new subcase. The current test file was also replayed against the immutable baseline: **17 assertion failures, no errors**. The final logs above contain these refreshed runs.

## Additional attention cost

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=candidate:test_support/upstream \
  python tests/benchmark_backend_identity.py --rows 1970 --repeats 3 \
  --output reports/backend.attention_benchmark.json
```

Before the final malformed-mode type check, 1,970 synthetic material cards/source refs for one issuer produced a median of **0.365 seconds** for the original pure attention call and **0.831 seconds** for the repaired attention stage: **about 0.466 seconds additional, 2.28× this isolated stage's cost**. All returned business output matched after removing only `input_identity`; input objects were unchanged. The benchmark made no owner-reader or network calls.

The retained benchmark used `workspace_identity.py` SHA256 `0346db36ff99e4e323e1256854673ff3d4c8c32977b33c700108af914b605525`; the other two runtime hashes match the final table below. The subsequent type check changes malformed non-string mode handling only; all benchmark fixtures use supported string modes. The original JSON measurement is preserved and timing was not rerun after this small guard change.

This is a synthetic pure-computation measurement, not live API latency or a timeout acceptance. The extra work is a deliberate limitation of preserving an unmodified, deployment-unverified attention module. Real owner-environment performance remains `CANNOT_CONFIRM`.

## Exact runtime source identities

| Runtime file | Before SHA256 | After SHA256 |
|---|---|---|
| `v4/manager_research/workspace.py` | `7a4875f1ab5ba46ac6c18bdaffe2c103a136734fda276fbee918163332844bb0` | `a6d6f067f04a3b543a8436e3080c9f7831e812a2cd10bbe16b783d23692ed33a` |
| `v4/manager_research/workspace_projection.py` | `027d855613e675e1f569b401b9a8344e40766b88c31e987e791d05a0b3a2f200` | `06b1e5cc770f22db8e111aa61fec9ba1f6ef8b7da5dca3da9a32995203634b17` |
| `v4/manager_research/workspace_identity.py` | New file | `3c0680ed3996c754ebf0849830e2cd820ebc32d5e01e196ec0e125b5e439062b` |

Machine-readable table: `reports/backend.source_sha.json`. Backend-only diff: `reports/backend.runtime.patch`. The root integration worker owns the combined application/rollback package and independent review.

## Remaining evidence limits

The retained historical counterfactual demonstrates a broad invalidation contributor. The original old manifest bytes and live GET body are still unavailable, and no post-fix live run was executed. The historical changed field and the sole live cause remain **`CANNOT_CONFIRM`**. This repair neither repairs missing research inputs nor establishes a successful target-date selection or natural run.

Throughout: `RESEARCH_ONLY=true`, `production_allowed=false`, `buy_gate_updated=false`, `orders_sent=false`.
