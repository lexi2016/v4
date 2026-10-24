# HKEX targeted announcement source adapter delivery

This package preserves the exact nine source, test, and control-script bytes from the frozen HKEX live-capture worktree. The seven runtime files are snapshots constructed against the deployed `us-mapping-visible-stocks-api-20261023-r2` release; they are not full-file replacements for the canonical checkout. `runtime.patch` is included as a hashed historical review aid and is not an instruction to apply it to canonical sources.

The change covers three targeted HKEX announcement routes and original owner/store/body integration. It does not connect the announcement selection page, model scoring, or recommendations. The batch was independently reviewed and its adapter tests and deployment probes passed before handoff. This delivery reuses those receipts and does not rerun the business tests or refresh HKEX data.

The deployed local runtime was PID 42989 on port 8873, release `hkex-announcements-api-20261023-r1`. The independent live-behavior review consumed a saved product for HK.00002 and read the directory/body endpoints plus OpenAPI. The exact receipt identities, commands, API calls, source hashes, and limits are in `verification.json`.

Acceptance remains local and scoped: the saved-product result is `PARTIAL`, one issuer only, and acquired late on 2026-10-23; directory exhaustion and historical point-in-time availability are unverified, `NATURAL_VERIFIED=false`, and the live sample does not establish the modern ALL-query nonempty-body path. It is not end-to-end announcement-selection acceptance.

The eight read-only runtime dependencies and their frozen SHA-256 values are listed in `source-hashes.json`; they are not copied into this delivery because they were unchanged dependencies of the deployed runtime. Raw responses, full release trees, runtime outputs, queues, credentials, configuration, logs, private fixtures, `node_modules`, and `dist` are excluded.

Safety flags remain `RESEARCH_ONLY=true`, `production_allowed=false`, `buy_gate_updated=false`, and `orders_sent=false`.
