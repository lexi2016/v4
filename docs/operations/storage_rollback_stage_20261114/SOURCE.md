# V4 Stage owner repin and compatible rollback

The builder seals two inactive role sets from the exact deployed inventories and the previously sealed r3 candidate receipt. The forward set reuses the sealed r3 Main and API applications and points Stage at r3 Main. The rollback set uses the previous deployed Main and API applications with format compatibility and points Stage at rollback Main. Both proposed Stage roles preserve the original 14 historical owners and the existing dated transition. Forward adds the preceding deployed Main as historical owner 15. Rollback additionally adds r3 Main as historical owner 16 so its completed artifacts remain verifiable.

Run the builder with the configured `PANEL_PYTHON`, an isolated output root, and the original `CANDIDATE_RELEASES-r3.json`. The expected SHA-256 of the r3 receipt is `9e87231de26130c93ccc2f499bfb3b055a504b379a38406a548cd78d8df7ee63`. The builder validates every cloned inventory and records before and after file hashes, the proposed launcher files, Stage configs, policies, and reader attestations in `PREPARE_RECEIPT.json`.

```sh
PYTHONDONTWRITEBYTECODE=1 "$PANEL_PYTHON" prepare.py \
  --root "$DETACHED_CANDIDATE_ROOT" \
  --forward-receipt "$SEALED_R3_RECEIPT"
```

The rollback source patches apply without fuzz to the old service and the corresponding r3 Store. The rollback Main and API applications differ from their respective original deployed inventories only in `v4/manager_workbench/service.py` and `v4/manager_workbench/store.py`. The old business sequence persists fresh inputs in legacy inline format before reusable-plan lookup. A retry reads its own immutable input first, then its parent, and keeps the logical input SHA. Recovery preserves the bytes of an inherited checkpoint and writes only a reference for a new child. If an old inline checkpoint's companion is missing, recovery can restore it from the validated inline body at its canonical SHA. Missing or corrupt snapshots behind a new reference fail closed. The attempt reader and progress journal use the role's r3 overlay codec so restart can hydrate attempts made before rollback. [Service patch](rollback-service.patch) · [Store patch](rollback-store.patch)

Each Stage application differs from its original inventory in the binding config and one reader file. The deployed Stage reader refused the pinned historical `v4-v192-source-binding-20261112-r3-main` manifest because its inventory omitted `entry_count`. In historical mode only, the candidate accepts that exact manifest SHA-256 `e490d4ca93344ba9a958f03872ed040b8f838c22b806ff718772269d494ed328` and derives the count of 1,039 from its entries. It still checks the inventory aggregate, exact owner identity, required source file hashes, date, and completion witness. Current and dated transition owners use the original strict checks. [Stage reader patch](stage-attestation.patch)

Both candidate storage policies use `dry_run=true` and `auto_gc_enabled=false`. Each binds 85 source refs and references the detached, exact Stage and API proposal files. The prepare receipt separately gives the existing live launcher refs as an activation baseline. Main's proposal binds the candidate policy by SHA and is recorded separately to avoid a circular SHA reference. The builder prepares files and leaves scheduling and activation to a separately authorized operation.

`verify_compatibility.py <candidate-app> store|stage` exercises the sealed role modules. Its Store mode verifies inline recovery, immutable references, collision handling and rejection of missing candidate snapshot bytes. Its Stage mode validates the entire historical owner list, original dated transition, acceptance of the proven omission in historical mode, and rejection with an incorrect identity or outside historical mode. Native policy loading and real artifact replay receipts are separate evidence.

## Permanent release paths

`install.py prepare --root <new-permanent-release-root> --candidate-receipt <PREPARE_RECEIPT.json>` verifies the accepted candidate and its SHA-bound receipts, then stages both role sets under the existing release directory. Main and API application inventories match their accepted inventories exactly. Stage differs only in the owner config. Rollback Stage keeps installed forward Main in its historical allowlist, and the preceding live Main and dated transition retain their archived identities.

`install.py verify --receipt <INSTALL_RECEIPT.json> --sha256 <SHA> --mode forward` checks all source pins and compares the current live plists with the frozen baseline. It checks the planned Stage and API plist hashes against their proposed copies at this step. After switching, add `--live` to verify the literal live files. To project rollback while forward is live, use `--mode rollback --current-from forward`. Both policies keep dry run on and automatic GC off. The scripts do not load or stop services.
