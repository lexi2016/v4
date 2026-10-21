# Announcement calendar and task binding

The manager workbench now uses one native calendar for the target Hong Kong date. The replaced saved-date dropdown, old text-date adapter, catalog loading state, API helper and catalog type have been removed. Selecting another date clears the previous fixed plan identity and reads that date without starting capture or model work.

Announcement execution eligibility is bound to the current job and preprocessing report. A historical delivery remains readable without hiding the new task’s FIRST action. Same-job duplicate execution and CONTINUE identity checks retain their accepted behavior.

`source/` contains the nine necessary source and test files as an overlay on the `manual-backfill-button-20261020-r2` runtime baseline. It is a delivery record, not a second application. `canonical-integration.patch` records the exact four-file canonical integration while preserving its pre-existing differences; it is not an additional runtime overlay. Other current runtime features and historical business results are preserved. The previously prepared R9 release was not activated because its base had been superseded.

See `verification.json` for independent acceptance, release identity, actual browser execution and preserved input hashes. Raw announcements, model responses, operational state and generated bundles are excluded. This remains research-only with no BUY gate changes or orders.
