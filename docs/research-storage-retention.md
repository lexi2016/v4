# Research storage governance V2

Candidate implementation, not deployment or natural-run acceptance. Financial
flags, QFQ computation, formulas, labels, ranking and BUY semantics are unchanged.
`ops/research_panel_qfq.py` remains SHA256
`05e8aa7aa19c1ae998481360d80fb99a39498ffd31c5945caedd5c791daa1fad`.

The current Main's authority already calls `run_with_retention`. V2 also wraps the
actual gate's daily product call and the scheduling executor's derivatives and
chart-recovery calls. These callsites were imported from the active R1 Main,
rather than an older worktree implementation. Deployment must overlay those
three runtime files plus the new governance module onto the exact active Main
inventory; it must not deploy the entire older worktree. The imported unmodified
factor-cache file is an actual QFQ test dependency, not an overlay change.

## Nondeleting defaults

Keep `auto_gc_enabled=false`, `dry_run=true`. Legacy `future_reclamation=true`
may record precreation provenance; it cannot authorize data mutation.
`retention.apply` now only validates a candidate and reports
`DRY_RUN_NO_DATA_MUTATION`. It contains no move/unlink implementation. Explicit
GC enablement raises `GC_BLOCKED_UNREGISTERED_READER_COORDINATION`: actual Reader
leases and exact formal reconstruction have not been established. Old future
ownership receipts remain policy-bound and are not migrated by renaming them.

A user-deleted quarantine directory is a known zero-byte destination only in
nondeleting dry-run. The code verifies absolute nonsymlink ancestors and their
pool device, and never recreates the Desktop path. Permission failures and wrong
file types remain errors. Neither same-disk relocation nor prevented generation
is reported as reclaimed space.

## Configuration and invocation

Retain the existing SHA-bound R1 policy/pins/activation contract. Add:

```json
{
  "auto_gc_enabled": false,
  "dry_run": true,
  "governance": {
    "enabled": true,
    "pool_id": "apfs-container-disk3",
    "pool_identity_verified": true,
    "registry_root": "/ABSOLUTE/stable/state/storage_governance_v2",
    "product_output_roots": ["/ABSOLUTE/current/daily_products/a_share"],
    "debug_output_roots": ["/ABSOLUTE/stable/state/storage_debug_v2"],
    "reserve_bytes": 68719476736,
    "safety_bytes": 4294967296,
    "ordinary_peak_budget_bytes": 171798691840,
    "debug_budget_bytes": 17179869184,
    "product_peak_bytes": 34359738368,
    "own_budget_bytes": 536870912,
    "max_debug_file_bytes": 67108864,
    "max_debug_job_bytes": 268435456,
    "wait_seconds": 0,
    "max_attempts": 3
  }
}
```

The controller verified the current shared APFS container as disk3. A different
machine needs its own actual pool evidence. Directory names or individual
`st_dev` values do not define the shared pool key. Additional volume devices
require an explicitly verified `pool_member_devices` list; current outputs are
on the data-root device. All registered callers must share the SAME registry.

The 32GiB formal-product forecast is conservative, based on existing dated
checkpoints (~0.945GB), versions (~1.049GB), shared history (~10.931GB) and scratch
headroom. It is not a measured peak and does not change debug limits. It must be
configured explicitly. Existing QFQ forecast remains max(minimum, pair*3.5).

Use the active absolute interpreter and the exact policy SHA:

```sh
python -m ops.research_storage_governance --policy /ABSOLUTE/policy.json --policy-sha256 EXACT_SHA status
python -m ops.research_storage_governance --policy /ABSOLUTE/policy.json --policy-sha256 EXACT_SHA project --source /ABSOLUTE/accepted.parquet --output-root /ABSOLUTE/stable/state/storage_debug_v2 --columns ts_code trade_date close
```

`status` does not create a lock, registry, report, timer or trend history. A
missing/corrupt registry does not prevent existing safe reads. The projection
command defaults to three stocks and twenty output dates and reads existing
computed rows. It never recomputes a shortened EMA/KDJ history or ranks a
three-stock universe, never fetches prices, and never changes CURRENT. Larger
scope is refused by this command; formal registered actors retain their original
full scope under their own forecasts.

## Registry, recovery and write boundaries

The small atomic JSON registry and kernel pool writer lock serialize registered
materializers. Claim/reservation updates occur in a short bounded flock
transaction. PID plus process start identity, a per-claim token and wall-clock
heartbeat are recorded. Monotonic time is used only for local bounded waiting.
A live/unknown owner is never stolen. A dead same-identity owner may resume the
same directory through original checkpoint validation; unrelated dead owners
require reconciliation and retain their reservations. Retry attempts are bounded.

Admission subtracts only other unwritten reservations and the task's remaining
forecast from current free space. Tracked allocated-byte growth consumes the
reservation; `.pending` to `.parquet` renames count once. The first exact current/rollback resident paths remain billed. New registered
generation directories remain billed after they age out of CURRENT, while broad
legacy/frozen run roots stay in the separate global ledger. Current paths,
tracked generations and the configured product root are deduplicated by actual
containment, avoiding baseline-plus-written double charging. Actual free-space ratio and the
64GiB+4GiB floor are rechecked at existing write, stock-submit, checkpoint,
Parquet-table and publish boundaries. There is no OS quota. Already submitted
workers drain; no business process is killed.

Scoped module adapters check the caller's active admission on every function,
writer/executor method and Future operation. Unrelated threads pass through to
the original implementation without billing or gates. Participating ThreadPool
work and registered completion callbacks explicitly inherit context; spawned
process callables remain unchanged. Nested adapters reuse existing bindings,
and normal/exception exits restore module and per-Future methods. PyArrow is
never patched globally. Spawned worker writes are bounded by the original parent's
submit/result seams. The existing publication journal and rollback are reused;
bounded control writes are allowed to finish/roll back after a transaction has
started. A committed pair remains READY if registry recording subsequently fails.

Verified reuse checks BOTH panel identities/integrity and exact owner metadata.
Existing computation IDs are authoritative; the outer invocation claim does not
replace the QFQ generation tuple. A stale cheap READY gate does not trigger a
full rebuild: it requires identity reconciliation. SHA verification is cached
only against exact inode/device/size/mtime/ctime evidence.

Governance metadata is bounded (registry <=4MiB, <=512 task records, own-output
budget 512MiB including ownership evidence; precreation evidence also has a
64MiB guard). On exhaustion, new work/detail output is blocked and evidence is
retained. This implementation suppresses output rather than deleting or rotating
protected evidence. Automatic 14-report/90-day trend rotation is not implemented.

## Limits and rollback

Direct calls to the original producer, frozen independent scripts, raw/adjustment
input writers before this wrapper, and helper writes outside registered roots
remain gaps. The active Top200 already reads bounded fields/windows rather than
copying a full panel. Its existing numerical owner is unchanged.

The original paired pointer protocol explicitly cannot provide atomic snapshots
for uncooperating Readers. Tested rollback/recovery is not certification of all
Readers or all publication crash stages. Reader/GC races, exact formal rebuild,
full natural parity and consecutive natural generations remain BLOCKED/NOT_RUN.

Rollback uses the exact prior app/policy/pins/manifest via the controller's
existing binding mechanism; it does not delete data or start a full rebuild.
Disabling `governance.enabled` removes V2 admission; keep autoGC off. Removing both
retention environment fields restores the legacy unguarded caller and is a
separate explicit operational decision. No service or scheduler is changed here.

## Phase2 bounded continuation (2026-11-08; source, not deployment acceptance)

Actual Main QFQ and product calls are sequential. The exact unique-inode logical
resident was85,863,466,983B; QFQ48GiB includes its staging/control allowance,
then its terminal claim releases the reservation before product32GiB admission.
Retained future output is UNKNOWN. At the conservative48GiB-retained endpoint,
product admission has35,878,937B class headroom; another48GiB QFQ can block.
Same-directory recovery keeps its original identity and replaces its reservation
once, but retains a full additional forecast unless exact reusable-byte credit
has been certified. This may conservatively block a nearly completed failed run;
it does not authorize deleting recovery inputs or expanding160GiB.

The real raw-sync authority now enters shared-pool input admission before loading
or downloading. Its forecast is twice exact existing native .day bytes plus the
existing32MiB package limit and32MiB response/control allowance. Protected raw
inputs remain global free-space assets, not reclaimable ordinary residents.
Scoped adapters guard actual imported adjustment metadata/GBBQ serializer
boundaries, without changing their numerical source bytes. Standalone/manual
calls outside these registered invocation scopes and HK remain uncovered.

The task registry is JSON capped at4MiB **exact serialized bytes**. Every new
unfinished task reserves a256KiB mutable control slot before data writes;
checkpoints and terminal records replace its padding. Admission leaves16KiB
margin. Terminal state does not require deleting other tasks or unique evidence.
No daily archive/database copy or pruning of active/frozen/unique records occurs.
At task count/cap, new work stops; a serialized atomic save peaks at old+new JSON
(<8MiB), not one file. Pair manifests have their own4MiB bounded namespace with
128KiB prepublication margin and count toward the existing512MiB own-output
budget. Leases use OS locks, not timeout/PID deletion permission.

New Main/API requests bind one immutable pair manifest, acquired under short
metadata coordination and protected by a generation OS shared lease until the
materialized request ends. Normal Readers do not acquire qfq_publish.lock.
The original publisher holds its existing lock, publishes through its unchanged
owner, then atomically commits one manifest holding both roles/current+rollback.
A crash between commits leaves the previous immutable pair available; explicit
seed/reconciliation under the original owner lock is idempotent. Source caller
adapters replace only a request-local loaded shared Reader's mutable CURRENT
revalidation; its original filtering and numeric/basis code is unchanged.
Streaming/lazy returns require an explicit lifetime contract and are rejected by
the current materialized-entry decorator. Historical direct/frozen profiles keep
their original selection, and their objects remain protected. Unknown historical
readers protect their object scope; they are not claimed covered globally.

`ops/mac_storage_monitor.py` is the exact existing external monitor imported then
patched for its lifecycle. The controller must repoint the existing invocation,
not add a timer. Its explicitly approved **new empty ordinary root** owns only
new reports, keeps14ordinary detailed **runs** and90days of lightweight trends,
protects critical/error/explicit rollback IDs, and supports dry-run. Legacy
history/inventories, including1.113GB evidence, are not rotation candidates.
Detailed64KiB/report, trend8MiB and namespace16MiB default caps suppress writes
when evidence cannot rotate. Non-daily modes code-suppress the old unbounded
per-file collector even if an old path list remains configured.

Object qualification is recorded in `READER_GC_MATRIX.csv` under the original
audit. `retire_candidate` provides a noncurrent/nonrollback exclusive-lease gate
for known immutable generation manifests; it performs no data deletion.
Future successful private Arrow copies may qualify only with original ownership,
source/merge/recovery and object-scope authority gates. Concrete complete formal
panel rebuild certificates are absent; tiny fixtures do not certify a full
panel. No real formal two-generation GC, natural run, deployment or actual
reclaim is asserted by this source change.
