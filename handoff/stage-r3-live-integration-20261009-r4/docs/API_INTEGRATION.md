# R4 API research read integration

## Result and scope

The current Issue32 API source was recovered exactly from GitHub blob
`f2cdb61eb5689f70bf9f9508e96a0262c0af7389` at feedback commit
`137431f5de3917ff4526784351f5638e115061e5`. Its 324648 bytes have SHA-256
`5d344dfe902db37f81e06d1d401e9a7e20ae910d8f7647b732ae2b3ba4f019e5`, matching the
Mac read-only preflight. `SOURCE_MAP.json` records all exact before/after bytes.

The delivered API change adds an optional approved research reader to the existing
ordinary Stage route. It reuses the accepted R3 `consumer.py` and
`execution_evidence.py` without changing their bytes. The Stage owner, selection
algorithms, acquisition sources, STRICT gates, normal history root, manager routes,
and ensure routes are outside this delta.

The Chat result is source implementation plus offline verification. The real Mac
manifest content was not supplied to Chat; its fixed SHA and reported A/HK run IDs
are trust anchors for the delivered Mac preparation command. No real canary data
was copied, moved, fetched, re-produced, or written into state. No plist, live
source, service, release pointer, or remote deployment was changed.

## Read and root contract

The ordinary route stays `GET /api/v3/workbench/stage`. The configured
`stage_center_selection_root` continues to own date catalog/history and every
unrelated date/stage request. The existing `_APPROVED_EXACT_STAGE_BACKFILLS` map,
its namespace resolver, and its original row/safety/SHA checks are unchanged.

The optional reader only intercepts `20261009 / STAGE_0930_0935`. The exact approved
backfill is `85e29661ecd848fe9b8344ea59279e86`, with A selection
`run-2688466a1ae4464ba7237f0b` and HK selection `run-cfbdc9b36a7308da178d193a`.
The ordinary request returns both markets. An explicit request containing the
same backfill and one approved market returns only that market and retains the
existing `BACKFILL`, `HISTORICAL_BACKFILL_READ_ONLY`, and `WATCH_ONLY` response
contract. Missing paired parameters still return 422; unknown exact identities
still return 404 through the original route.

The opt-in consists of two release-owned files:

- `stage_center/approved_research_read.json`
- `stage_center/approved_research_read.sha256`

Both absent means disabled. A partial pair, malformed sidecar, changed digest,
invalid shared evidence, source drift, or namespace violation produces 409 for the
approved target. Unrelated dates do not inspect the research tree. The sidecar is
exactly 64 lowercase hexadecimal ASCII characters followed by one newline. Both
files must be regular files without any symlink path component. The pair is
generated, reviewed, and inventoried together as part of the candidate delta.

For an isolated application invocation only, `create_app` also accepts
`stage_center_research_binding_path` and `stage_center_research_binding_sha256`.
The request API has no path or approval-override parameter.

The research selection and receipt roots are derived from the SHA-pinned manifest
and must use its exact immutable `selection/backfill/<id>` and
`receipts/backfill/<id>` namespaces. The binding records the unchanged normal root;
runtime must still be configured with that exact root. Overlapping history/research
trees, copied-state substitutes, guessed roots, and symlink namespaces are not
accepted.

## Evidence checks

The fixed manifest SHA is
`9b5df949141ed1533cb7a71e2c46bebe341bea663f5f966bda16225754e89857`. It binds the
original owner receipt SHA, immutable owner-history SHA, output paths, R3 source
map, Stage candidate source manifest, Stage module source observations, and real
HK selection ID. The delivered approved tuple separately pins both market IDs.

Preparation and runtime verify the manifest/owner/history identities and their
explicit research/replay safety fields. The original R3 owner-history reader
validates the archived receipt and write-clock contract. Stage module files must
match the source map and the manifest's declared paths and hashes. The API app
pins the new helper SHA; the helper checks its own loaded and current source,
the loaded R3 consumer/evidence file origins and exact R3 hashes, and the API app
source observed at import. Values copied into binding JSON cannot replace these
independent code and manifest anchors.

Each A/HK lane uses the original `SelectionStore._verify_run`, original R3 trio
binding, owner-declared run/artifact/algorithm/raw-source identities, actual trio
byte hashes, separate canonical JSON hashes, and the exact latest-entry binding.
The original immutable selection schema requires its three safety flags to be
false; it does not require an invented `RESEARCH_ONLY` envelope field. The latter
is required on the pinned manifest, owner receipt, and returned payload.

A damaged market trio becomes `CANNOT_CONFIRM` with no rows or substituted run.
Its healthy sibling remains visible. The new ordinary branch retains
`PARTIAL_WITH_ROWS` when HK observation rows exist while the A lane fails, even
though the existing HK presentation correctly withholds a formal selected count.
The original history projection is otherwise unchanged.

Responses expose exact binding/manifest/owner/trio/module hashes under
`research_read_binding` and each canonical selection market. Existing R3
`execution_evidence` retains its verified-selection and owner-history evidence;
`execution_verified` and `natural_verified` remain false. Research-source
limitations, stale universe, membership uncertainty, formal D1/PIT restrictions,
and source coverage remain the original R3 projection.

## Preparation interface

`tools/prepare_research_binding.py` exposes:

```python
prepare_research_read_binding(
    *, manifest_path, history_root, api_after_root, api_source_root, output_root
)
```

The equivalent CLI flags are `--manifest-path`, `--history-root`,
`--api-after-root`, `--api-source-root`, and `--output-root`. Every path must be
absolute. `api_source_root` is the exact current API support tree, verified against
the active `app.py` preimage SHA above. `api_after_root` contains the four reviewed
R4 API files; their exact hashes are frozen in the preparation tool. The tool
uses a fresh read-only child process to combine those explicit source roots for
original helper imports. It never imports the API application or starts a
collector. The trusted `_BUILD` child contract is reusable by the release
coordinator for an independent readback comparison.

`output_root` must be new, have an existing parent, and be outside all read source,
history, and immutable candidate roots. The binding pair must be absent from the
current source and reviewed overlay. Successful preparation writes only the two
files above plus `PREPARATION_PROOF.json` in the new output tree, all mode 0644.
It returns the proof's byte SHA and two standard change-set rows:

```json
{
  "path": "stage_center/approved_research_read.json",
  "before_sha256": null,
  "after_sha256": "<actual generated byte SHA>",
  "before_mode": null,
  "after_mode": "0644"
}
```

The proof includes both generated file identities, current/after API source
identities, the complete hash-bound evidence document, and the unchanged normal
history catalog/latest pointer observation. Status is `PREPARED_NOT_DEPLOYED`.
There is no production binding JSON or sidecar in this Chat after tree: those
bytes depend on the real Mac manifest and are generated by this command during
the authorized Mac application/verification phase.

## Verification and reproducibility

Final Chat results: **47/47 new API integration/preparation/legacy tests** and
**82/82 unchanged R3 API-reader regression tests**, with zero failures, errors,
or skips. Commands, platform, source scope, JUnit, and logs are in `evidence/`.
`evidence/TDD_RECEIPT.json` preserves the initial missing-route failure and the
subsequent concrete contract failures resolved during implementation.

The integration suite exercises both markets, 19 synthetic normal-history dates,
other stages, old exact-backfill response equality, market-specific trio tamper,
shared evidence/source/config tamper, namespace isolation, sidecar syntax, absent
and partial binding pairs, and pure reads. The preparation happy path runs a fresh
subprocess against real helper code and writes/read-verifies the two generated
delta files. Synthetic approval substitution exists only in test support; the
production CLI and API expose no fixture mode.

```sh
python -B -m pytest -q -p no:cacheprovider tests
python -B tools/export_research_binding_fixture.py --output /absolute/new/output
```

Relocated test runners can set `R3_PACKAGE`, `R4_API_AFTER_ROOT`,
`R4_API_BEFORE_ROOT`, `R4_API_TOOL_ROOT`, and `R4_API_TEST_ROOT` to the actual
packaged sources/test support. The exporter creates fresh
`workbench_response.json`, `consumer_response.json`, and `FIXTURE_RECEIPT.json`
from the same real immutable stores and original owner receipt writer. The exact
current API route and its unchanged projection helpers execute from parsed source.

Full FastAPI application startup/HTTP, actual Mac preparation, integrated source
application, 8873 behavior, and natural execution are **NOT_RUN** in this Chat
environment. The offline route harness supplies only the unavailable FastAPI
exception/query wrappers; it does not claim a running HTTP service. Previously
accepted R3 Mac/18873 results remain separate historical evidence.
