# Nondeployable backend reference boundary

The complete observation validation and immutable snapshot routes are included as sanitized reference source. They are not byte-identical to production: imports are redirected to public primitive shims, all write authorization is denied, and private unit-evidence pins are absent. See SANITIZATION_MANIFEST.json.

The host must independently provide authenticated owner access, same-origin policy and scoped DB/R2 capabilities. Caller headers or request JSON are not trusted authorization. This package provides no opt-in flag that turns its authorization shim on. A reviewed host adapter must replace the shim before any real deployment; this repository change does not authorize such deployment.

Expected host storage interfaces: D1-like prepare/bind/first/all/run, R2-like put/get/body. Read access is also a host-controlled boundary; the exported router is not a public server. Parent tables research_admissions and research_days must already contain independently committed parent identity; included schema creates only the new observation table and no source/seed records. No real database IDs, content-addressed source objects, initial records or credentials are included.

Unit-evidence config is intentionally null. Optional conversion with unconfigured evidence throws TRUSTED_VOLUME_EVIDENCE_NOT_CONFIGURED. Supplying a matching claim in payload does not configure trust. Empty/absent overlay remains unknown. Actual trusted values and supplier evidence are private host inputs, not published fixtures.

Synthetic validator tests are executable without a database. The stub denies every write, including requests claiming owner-private and platformBoundaryConfirmed. There is no claim that this public package is a runnable production Site or a substitute for the deployed system's private integration tests.
