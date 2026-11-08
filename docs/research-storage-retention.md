# Research producer storage lifecycle

Candidate only. Existing artifacts are quarantined on the same volume under the
user's Desktop 待删除文件夹. A move frees zero bytes. The 2026-11-08 user decision
permits permanent reclamation only of future-created, successfully published,
obsolete and unpinned derived artifacts. Raw data, model weights, failed runs,
unknown files and existing artifacts are never permanently deleted by this module.

`ops/research_panel_qfq.py` is imported byte-identically from the active Main app:
SHA256 `05e8aa7aa19c1ae998481360d80fb99a39498ffd31c5945caedd5c791daa1fad`.
The active caller baseline SHA is
`6dc0cd5506e94be6ce0ebdf3cb93d248b3c9438b09a60afe4593dc9a32764b22`.
Only `run_windows_a_formula_authority` changes: its existing rebuild is wrapped
by the retention module. No generation tuple, computation kernel, price field,
formula, schema, PIT interpretation or BUY flag changes. Lifecycle changes must
not be added to the QFQ adapter file, whose full SHA identifies computation.

## Explicit activation contract

Root/controller, after independent review, builds a new immutable Main candidate
from the actual active app and changes only the caller plus the new module. Keep
all other bytes and their inventory hashes. Add the new module to both inventory
lists, update the caller entry, and use the existing guarded release manifest
and Main binding process. API and Stage are separate identities. This document
does not authorize or claim activation, service changes or natural-run success.

Main environment must bind BOTH `V4_RESEARCH_RETENTION_POLICY` (absolute JSON
path) and `V4_RESEARCH_RETENTION_POLICY_SHA256` (exact SHA256). Neither present
means legacy behavior; only one present or a mismatch fails before computation.
The policy must remain available unchanged; a policy change intentionally
invalidates earlier future-ownership claims, preserving those files until an
explicitly reviewed ownership migration. No LaunchAgent edit is made by module.

Minimum policy shape below uses placeholders, not executable deployment defaults.
Positive byte budgets must be chosen from the actual scoped inventory and free
space. `max_managed_bytes` includes managed runs, configured formal roots and
dedicated quarantine; `reserve_bytes` is an absolute byte reserve. A new build
estimates `max(minimum_build_bytes, 3.5 * current_pair_bytes)`. Already-current
reuse uses the existing owner's readiness check and creates no ownership claim.

```json
{
  "schema": "v4_research_storage_retention_v1",
  "data_root": "/absolute/active/data",
  "run_root": "/absolute/active/a_formula_runs",
  "formal_roots": {
    "selector": "/absolute/active/data/selector_ready_panels/data_layer_daily_formula_increment_update_v1",
    "backtest": "/absolute/active/data/backtest_panels/data_layer_daily_formula_increment_update_v1"
  },
  "pointers": {
    "selector": "/absolute/active/data/data_layer_interface_current/CURRENT_SELECTOR_READY_PANEL.txt",
    "backtest": "/absolute/active/data/backtest_panel_interface_current/CURRENT_BACKTEST_BASE_PANEL.txt"
  },
  "quarantine_root": "/Users/lexi/Desktop/待删除文件夹/V4_research_lifecycle",
  "keep_completed": 2,
  "managed_pin_inventory": {"path": "/absolute/reviewed/managed_pin_inventory.json", "sha256": "EXACT_SHA256"},
  "max_managed_bytes": 1073741824000,
  "max_quarantine_bytes": 536870912000,
  "reserve_bytes": 17179869184,
  "minimum_build_bytes": 53687091200,
  "future_reclamation": true,
  "activation_id": "UNIQUE_REVIEWED_ACTIVATION",
  "activation": {"path": "/absolute/immutable/activation.json", "sha256": "EXACT_SHA256"},
  "formal_relocations": []
}
```

The activation JSON must contain schema `v4_research_storage_activation_v1`, the
same `activation_id`, and authority
`FUTURE_CREATED_SUCCESSFUL_UNPINNED_DERIVED_ONLY`. It records the actual user
decision and existing-data quarantine boundary. The module never manufactures
approval. `managed_pin_inventory` is a reviewed explicit projection of registered
V4 consumers and current process scope. It includes typed-end facts, frozen/model
consumers, authoritative feed bindings and recovery inputs. This is not a claim
that undocumented offline consumers or arbitrary files have all been discovered.
A keyword search or missing reference cannot establish that scope. Its shape is:

```json
{
  "schema": "v4_research_managed_pin_inventory_v1",
  "status": "COMPLETE_REVIEWED",
  "expected_main_app_root": "/absolute/new/immutable/Main/app",
  "consumer_scopes": {
    "api": "PINNED", "main": "PINNED", "stage": "PINNED",
    "typed_end": "PINNED", "history_recovery": "PINNED",
    "model_frozen": "REVIEWED_NO_MANAGED_PINS"
  },
  "pins": [
    {"kind": "managed_path", "path": "/absolute/managed/generation-or-artifact"},
    {"kind": "checkpoint_recovery", "usage": "historical_pin", "path": "/absolute/recovery.json", "sha256": "EXACT_SHA256"}
  ],
  "source_bindings": [{"path": "/absolute/consumer/config-or-API-Stage-plist", "sha256": "EXACT_SHA256"}]
}
```

All six scope keys are required, with `PINNED` or `REVIEWED_NO_MANAGED_PINS`;
UNKNOWN blocks reclamation. Root supplies the actual scoped inventory and keeps
the provenance of that review. `source_bindings` are exact SHA freshness watches,
read as opaque leaves; their audit/provenance JSON is never recursively expanded.
API/Stage bindings and Main consumer code/config files must be represented.
The runtime hook requires its actual app root to equal `expected_main_app_root`;
CLI dry-run from a worktree is allowed. A full Main plist SHA would create a
policy→inventory→plist→policy cycle, so it is not used. Main source inventory is
bound separately from the two policy environment fields. All roots must already exist; quarantine is a dedicated
same-volume child under the requested Desktop folder, never a raw-data root.

Optional `formal_relocations` items have `original_path`, `archived_path`, and a
`manifest: {path, sha256}`. They are an explicit reviewed old-path mapping, not
filename inference. Original must be absent, archive inside data root and outside
live formal roots, filename identical; the old stage's exact candidate SHA is
still verified before movement. A mapping-only legacy manifest does not itself
prove file content. Other one-off research candidates outside configured roots
remain outside this mechanism.

## Plan, apply and restore

Use the active V4 absolute interpreter. Planning reads metadata and eligible
artifact bytes but does not move data. Both CLI modes use the producer publication
flock and a separate retention-owner flock; lock files may be created by planning.
The output path must be outside managed roots. A live plan is not a business
acceptance of historical/PIT correctness.

```sh
"/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v4-mac/bin/python" \
  -m ops.research_storage_retention --policy /absolute/policy.json \
  --policy-sha256 EXACT_SHA256 --plan /absolute/audit/retention-plan.json
# Only after independent review/controller authorization of the exact saved plan:
"/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v4-mac/bin/python" \
  -m ops.research_storage_retention --policy /absolute/policy.json \
  --policy-sha256 EXACT_SHA256 --plan /absolute/audit/retention-plan.json --apply
```

Current is matched to one READY pair by exact pointer paths. Rollback is matched
to its baseline SHA pair, not arbitrary date/mtime ordering. Their formal pairs
and symbol checkpoints are protected. Already-current returns before spool use
(unchanged QFQ owner lines2528 vs2679); therefore proven future-owned unpinned
ARROW_V1 buckets may expire immediately after READY. Existing current/rollback
buckets remain intact. All unfinished/failed/locked runs are pinned in full.
Ordinary JSON/snapshots, raw native caches, original archives, quarantine rows,
code and model roots are outside eligible cleanup trees and are never reclaimed.

The former generic recursive audit walker was withdrawn after its bounded real
diagnostic reached10000 documents and mixed actors, commands and historical
environment records with inputs. Failure evidence remains in the Writer audit
directory; no blanket missing-path exclusion replaced it. The live planner now
uses only the reviewed managed pin projection plus exact frozen owner seams:
`qfq_original_checkpoint_recovery_v1` protects its source_run and canonical chunk
mapping; same-asof recovery summaries must match that binding. Known tail-delta,
archive-addition and same-asof repair schemas protect baseline roles and their
direct source bindings. History-retention source_config/source_policy/archive_refs/
accepted_evidence are SHA-verified leaves, matching the owner's `_source` reads.
Publication journal pointer text is decoded only under its exact owner contract;
PREPARED blocks cleanup. Unknown runtime field/schema, reference drift/missing,
or metadata exceeding192MiB/256 runtime documents stops reclamation.

Status projection is limited to current/rollback and unfinished/unknown runs;
completed historical READY receipts outside that scope are not active invocations.
Their old recovery descriptor must be explicitly registered when it is a required
historical consumer. READY/failed status recovery metadata is a `historical_pin`:
the descriptor SHA is exact, source_run/chunks/receipts and original snapshot/core
paths stay pinned, but mutable old snapshot/core bytes are not asserted executable.
This avoids turning D30 provenance into a new invocation against today's cache.
Explicit inventory `usage` is `historical_pin` or `active_input`; omission defaults
to strict `active_input`, unknown values block. Active input verifies exact original
snapshot/core/chunk/receipt bytes; actual wrapper `checkpoint_resume` refs are
always active inputs. The unchanged QFQ `_source` gates still reject an old replay
when any required source hash changed. No blanket hash-drift catch is used.

Old successful runs are eligible only outside these runtime pins. Source SHA drift keeps
the entire affected run, including both spools. A full source SHA can be reused
only when device/inode/size/mtime/ctime match the persisted machine verification;
no unconditional full-history hash or formula recomputation runs daily.

`RESTORE_MANIFEST.json` is fsynced before any rename. It records original and
destination mapping, SHA, bytes, inode and device. Existing objects are only
renamed, never overwritten or unlinked. Repeating the same saved plan resumes an
interrupted transaction; unrelated destination collisions fail closed. A future
reclamation requires an activation-bound prebuild absence reservation and READY
ownership claim for the newly created run and formal generation directories.
Only verified reconstructable Parquet may be unlinked after verified rename and
a durable purge-start journal. Future ARROW_V1 buckets have their baseline-formal
reconstruction check. An obsolete future symbol checkpoint additionally needs
`v4_qfq_checkpoint_reconstruction_certificate_v1`: exact original snapshot and
canonical input identity; ALL direct snapshot `source_files`, symbol `raw_files`
and native-update receipts; exact original code/formula/contract refs and pinned
authority constants; recorded Python/NumPy/pandas/PyArrow identities; and every
actual checkpoint footer/receipt fingerprint equal to `(code,item,identity)`.
Inputs stay outside eligible cleanup trees. Content-addressed raw members are
verified without following `original_ref` audit subpaths. Verification reuses
only exact stat-bound SHA evidence, with at most50000 distinct input refs and
`max_reconstruction_source_bytes` (default32GiB). No formula or history is
recomputed to create this certificate.

Missing, changed, over-budget or unproven checkpoint reconstruction downgrades to
`QUARANTINE_FUTURE_UNPROVEN`; creation ownership alone never permits its deletion.
Formal panels ALWAYS take that quarantine branch: their publication merge keeps
legacy/static baseline context and this task implements no exact formal-replay
proof. Small JSON receipts stay in quarantine with lineage. Failed jobs and reused
paths never receive ownership.

To restore existing data: stop new mutation through the existing authorized owner
control, inspect the exact manifest, require the original path absent, verify
destination SHA/inode/device, and rename that artifact directory to its original
path. Never overwrite a recreated source. Future-reclaimed Parquet cannot be
restored by rename; its computation lineage and small receipts remain. Rollback
of code uses the original immutable Main app/manifest and removes BOTH policy
environment bindings through the existing guarded activation procedure. Do not
alter QFQ source hashes or compatibility gates.

## Verification and limits

Focused tests cover current/rollback and frozen consumer pins, FAILED/RUNNING
preservation, source drift, symlink/hardlink/path/collision rejection, pointer and
receipt changes, interruption before/after rename and irreversible unlink,
idempotence, exact future ownership vs grandfathered files, SHA binding, metadata
bounds, growth/quarantine budgets, reuse-current and unchanged source-hash cache.
Imported caller and QFQ baselines are not a complete canonical runtime package;
other active modules were intentionally not copied into Git by this task.

The budget is a prebuild estimate and stop-new-growth guard, not an OS disk quota
or guarantee of exact output size. Same-volume quarantine alone never bounds
disk use; authorized future reclamation plus headroom checks limits large managed
generation accumulation within the configured byte cap. Immediately reclaiming future READY spools avoids a
third day's unnecessary baseline bucket copy lingering across rotation. With
two ordinary13GB formal pairs and18GB symbol checkpoints, protected future
generation storage is roughly62GB plus the next build's estimated peak; these
are illustrative logical sizes, not a certified filesystem bound. Formal
generations without replay proof still add roughly13GB per ordinary trading day
to quarantine, so long-term capacity is NOT bounded by rotation alone. The
prebuild cap must eventually stop new growth until authorized existing-quarantine
handling changes capacity; no existing-data deletion is implied. Existing-data
quarantine can still occupy substantially more. External/manual producers and indefinitely pinned
generations can still grow; they remain visible/blocked by scope or byte budgets,
not silently deleted. Physical free-space recovery must be measured separately
from logical bytes unlinked (APFS clones/snapshots may retain allocations).
