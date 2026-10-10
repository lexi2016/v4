# Isolated cloud preview tools

These tools do not collect, refresh, trade, bind external interfaces, or change V4. The web assembler reconstructs the original UI from fixed Git objects and the current V5 SHA-checked overlay. Two missing HTML mount entries are explicit cloud additions. Four original source dependencies come from `7d2b71a91ad4d54f85fe03f5973248af686d7a87`; the source provenance file records every origin. The API DTO addition restores only original TypeScript declarations, without modifying runtime validation.

Required Git objects: `164c010c7eaa1659db9bfed0ff5f123c7a39eefc`, `8342862f05ca9f6516f51b3164b6110651e5af77`, `7d2b71a91ad4d54f85fe03f5973248af686d7a87`. Fetch those exact commits from the private origin if missing. Run from the repository root:

```bash
python3 V5/tools/cloud_preview/assemble_web.py --out /workspace/new-v5-web/apps/web
cd /workspace/new-v5-web/apps/web
npm ci --cache /workspace/npm-cache
npm run test -- src/manager-selection
npm run typecheck
./node_modules/.bin/vue-tsc --noEmit -p tsconfig.cloud-product.json
npm run build
```

The product-only typecheck deliberately excludes tests; it is not a substitute for the full typecheck. Original missing fixtures remain failures; no fixture is fabricated. `cloudActualReadback.spec.ts` requires `V5_CLOUD_WORKSPACE_RESPONSE` pointing to a saved actual gateway response. It verifies the original component and request/DTO/DOM contract in **jsdom**, not a visual browser.

To publish a pre-existing saved plan, supply its actual original-owner `action=read,view=auto` request and expected run. The publisher invokes the owner, requires `consumed=true`, and publishes through the existing generation mechanism into a **new** root. It creates empty announcement response storage so missing products remain 503, not fake empty results.

```bash
PYTHONPATH=V5/src V5/.venv/bin/python -B V5/tools/cloud_preview/publish_read.py \
  --request /PRIVATE/auto-request.json --expected-run ACTUAL_SAVED_RUN \
  --out /PRIVATE/new-publication --frontend-root /PRIVATE/web/dist --release-id FIXED_RELEASE
PYTHONPATH=V5/src V5/.venv/bin/python -B -m v5_shadow.module_api --config /PRIVATE/new-publication/manager.json --port 18897
PYTHONPATH=V5/src V5/.venv/bin/python -B -m v5_shadow.module_api --config /PRIVATE/new-publication/announcement.json --port 18898
PYTHONPATH=V5/src V5/.venv/bin/python -B -m v5_shadow.api_gateway --config /PRIVATE/new-publication/gateway.json --port 18896 \
  --frontend-root /PRIVATE/web/dist --frontend-manifest /PRIVATE/new-publication/frontend.json
```

All services remain loopback-only with the original Host/Origin policy. Commands need separate processes. Configuration/static files are loaded at startup; restart only these recorded cloud processes after an actual change. `run_shadow.py` is not the gateway launcher. No tunnel or public sharing is configured. Container lifecycle may terminate these processes; do not promise durable hosting or parent-thread access to localhost.

## Current recovery and external test fixtures

The frontend current-recovery delta comes from SHA-verified Mac handoff
`e0a6bc36f9563df6a4e0f37d4e16a59e14347227`. Its three source changes are merged
without removing the cloud DTO declarations. Its original three real-receipt
tests remain real-receipt tests; no synthetic data substitutes for the 392 batch.

Original files can now be bound explicitly on either platform:

- `V5_REAL_CURRENT_RECOVERY_RESPONSE`: original manager-read-publication.json for run 5b4feaf7ef7d4d13bec639e90b6d3db0.
- `V5_ISSUE8R2_OBSERVATIONS`: original issue8R2.ownerObservations.json.
- `V5_ANNOUNCEMENT_REVIEW_FIXTURES`: directory containing original ANNOUNCEMENTS_20261001.json and ANNOUNCEMENTS_20261002.json.
- `V5_EASTMONEY_WORKSPACE_FIXTURE`: original 20260929 integration/workspace_after.json.
- `V5_MANUAL_OBSERVATION_FIXTURES`: original manager_current_observation_20261002 directory. The binding SHA and per-file SHAs remain enforced.

Missing originals still fail. The typed runtime JSON loader removes a compile-time
fixture dependency; it does not generate an empty fixture or suppress tests.

For independent **synthetic** current-recovery contract tests, create a new file:

```bash
V5/.venv/bin/python -B V5/tools/cloud_preview/make_synthetic_recovery_fixture.py --out /PRIVATE/new-synthetic-recovery.json
```

Bind `V5_SYNTHETIC_CURRENT_RECOVERY_RESPONSE` to that file for the test run, and
keep `V5_CLOUD_WORKSPACE_RESPONSE` bound to the existing actual cloud response.
The synthetic fixture uses the original backend with empty owners; it is never
published to the preview or counted as real business evidence.

## CONNECT rejection admission

The old direct `python -m ops.us_market_digest` command bypasses the V5 cloud
admission shim and must not be used as the cloud entry. The complete original producer closure (48 pinned source/resource files, including
its exchange calendar) is separate from the smaller read adapter. Assemble and
check it without any collection:

```bash
python3 V5/tools/cloud_preview/assemble_us_collector.py --out /PRIVATE/new-original-us-owner
PYTHONPATH=V5/src V5/.venv/bin/python -B -m v5_shadow.cloud_us_collector --owner-root /PRIVATE/new-original-us-owner --check-only
```

Only after the platform's normal network configuration and source owner are
separately admitted, initialize a private isolated output and explicitly invoke
capture. These are instructions for a later authorized run, not evidence that
cloud collection now works. Do not retry previously refused targets:

```bash
PYTHONPATH=V5/src V5/.venv/bin/python -B -m v5_shadow.cloud_us_collector --owner-root /PRIVATE/new-original-us-owner --init-data-root /PRIVATE/new-us-output
PYTHONPATH=V5/src V5/.venv/bin/python -B -m v5_shadow.cloud_us_collector --owner-root /PRIVATE/new-original-us-owner --allow-network-capture -- --data-root /PRIVATE/new-us-output <original date/phase arguments>
```

The entry verifies every original file before import and after capture, requires
a fresh interpreter and marked output outside source roots, and preserves the
original CLI, store and exit status. The lower-level `cloud_transport` module is
a testing/integration seam; prefer the pinned `cloud_us_collector` entry.

This passes a guarded transport through the original producer's `transport=`
seam. CONNECT 4xx/5xx refusal is raised as an owner HTTPContractError with
`http_status=null`, `proxy_connect_status`, and
`CONNECT_REJECTION_NO_DIRECT_FALLBACK`. Original source bytes, capture windows,
locks, IO, upstream HTTP status handling, parsing, and exit codes stay original.
There is no automatic capture or retry. Previously denied real targets were
**not** requested to test this change; tests use injected synthetic openers.
The entry's `--help` was checked without collection.


The pinned collector rejects extra source files, legacy bytecode, unlisted
packages and symlinks. A dedicated finder restricts original package imports to
the declared modules/namespaces and audits module origins. Verified source bytes
are compiled directly; existing valid-source `__pycache__` files are tolerated
but never loaded or rewritten, including a cache with a poisoned body.
Synthetic success coverage separately exercises five RSS responses plus all
33 quotes/24 industry rows, original publication and original exact-date readback.
It is not evidence of a successful real network capture.

The 689-row original UI test needs BOTH `OCT2_RESEARCH_SELECTION_PROJECTION`
(the original gzip projection) and `V5_ISSUE8R2_OBSERVATIONS` (the original owner
observations JSON); providing the projection alone does not satisfy its fixture.
