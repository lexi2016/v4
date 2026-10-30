# Public framework maintenance SOP

This is a non-sensitive engineering guide for the public framework namespace only. It contains no private user schedule, research evidence, live endpoint, owner identity or source-admission configuration.

## Read before modifying
1. Read `MAP.md`, `graph.json` and `impact_examples.json`. Source links are pinned to the stated public commit; they are not links to a private working tree.
2. Treat import/global/SQL edges as static candidates. A test import is not a test execution result. Unknown fetch targets or aliases remain unknown.
3. The supplied shell intentionally has no default API or renderer. Empty unbound state is correct; do not add fake charts to hide missing integration.
4. Public backend writes always fail closed; the volume trust registry is deliberately null. A request cannot supply its own authorization or trusted source pin.

## Diagnose a problem
|Symptom|Inspect|Expected boundary|
|Blank shell|Explicit same-origin host configuration and `shell/workbench.mjs`|No network calls while unbound|
|Wrong date or delayed result|Identity, immutable revision, token/abort checks in shell and pure modules|Missing identity clears stale state; no fallback to another date|
|Unknown quantity|Original unit and evidence configuration|Unknown is not zero; do not guess a multiplier|
|No interactive chart|Externally supplied renderer and projection adapter|No renderer implementation or real projection is shipped|
|Unexpected affected modules|Reverse import/global dependencies in graph|Graph is not a complete dynamic call graph|
|Storage write denied|Public authorization shim and host-storage contract|Denial is intentional; never weaken it using caller flags|

## Change safely
1. Use the repository's explicitly authorized collaboration branch and namespace. Do not overwrite another contributor's stock-renderer implementation or protected base paths.
2. Bind the change to an exact source commit and file hashes. Update interface contract and synthetic tests before changing consumers.
3. Run `node --test tests/*.test.mjs` from the framework package. No dependency install is needed for its current tests.
4. Test missing data, wrong identity/date, out-of-order response, authorization denial, bounded input and immutable-history conflicts. UI changes additionally need actual viewport screenshots; unit-test success is not visual approval.
5. Refresh this **public-subset** graph from only the public package sources. Never publish a full private-system graph as a substitute. Keep source commit and graph digest together; fail if a referenced source hash changed.
6. Use normal non-force commits and expected-head checks. Respect explicit permission denials; record the exact action and result rather than trying another route.
7. Public repository synchronization is not production deployment. Release requires separate authorized preview, review and deployment gates. Keep accepted source and release receipts independently versioned.

## Backup and history
Create an immutable manifest of path, bytes and SHA256; check the authorized destination for duplicate content before upload. Preserve earlier versions. Read back remote metadata and, where available, content hashes. A successful upload request alone is not a complete readback verification. Do not change sharing permissions or include credentials. No private destination identifiers are included here.

## SOP edits are documentation, not execution
A future owner-only SOP editor must use a fixed document allowlist, text-only content, immutable revisions, expected-version compare-and-swap, idempotency and audit history. Editing a document must never execute its command snippets, alter code, deploy a release, change authorization or send orders. Rollback creates a new revision; it never erases history. This public package does not implement an authenticated SOP write service.
