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
