# Candidate boundary and rollback

This batch is independently ONLINE PASS. The owner pointer and reviewed API/scheduler plists were installed with controlled graceful reload; all original before plists and five actual base roots remain available for rollback. Final roots: API r4, shared/scheduler r3, materializer/reviewcore r1. Independent candidate R2 and online gates both passed.

Before any activation, acquire the shared API release lock and the agreed scheduler cutover lock; CAS both original plist SHA and every selected candidate/base code inventory. If a parallel release has changed either binding, stop and rebase the HK deltas. Read actual running process cwd, selected environment and healthy QUEUED/RUNNING jobs. Drain healthy work; do not cancel it. Preserve manager state, A roots, safety flags and the scheduler's old Review Core shared namespace.

Install only the prepared owner admission pointer and the two staged plist bindings under the authorized activation scope. Gracefully reload API and scheduler once. Scheduler PID changes must be reported. Verify all five exact runtime source roots, the same resolver bytes, manifest/inventory identities, normal/audit canaries, invalid queries, stale-cache rejection, typed model HOLD and the frozen A hash/artifact/run/status. Never reuse old HK cache to fill the 100-row shortfall.

On any failure restore only the two original plist byte files and the admission pointer's prior state (currently absent), then gracefully restart the original API/scheduler bindings. Keep all original market files, old releases and old caches. Do not reset data, manager roots, models or A state. Repeat the A read-only control and report the failed/new and restored identities. Do not claim UI or natural-slot acceptance from these checks.

The exact seven superseded never-activated candidates listed in SUPERSEDED_CANDIDATES.json were moved by same-volume rename after independent ONLINE PASS and launch/process checks; CLEANUP_RECEIPT.json records their new paths and preserved identities. Current live and rollback releases remain in place.
