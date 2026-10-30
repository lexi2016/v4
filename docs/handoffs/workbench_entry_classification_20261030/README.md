# Default entry and persistent received classifications

This delta follows the reviewed R4 workbench. It changes only default research
navigation/date binding and local classification explanation/filtering.

## Canonical entry and retired HTML

- /research-panel/daily.html redirects to /research-panel/workbench.html and
  preserves its query when the reviewed workbench is exported.
- ISO/compact date is kept. Missing D28/D17 is NOT_MATERIALIZED/CANNOT_CONFIRM;
  no other catalog day is substituted. Date changes close the old day's module
  subscription and clear old context identity before any replacement.
- The old daily source HTML was moved unchanged to
  research-panel/待删除/legacy-daily.html. The explicit virtual
  /research-panel/legacy-daily.html alias reads that fixed hash-bound file so
  its original relative assets still work. Both backup links say 旧版单股归档.
- Root must move the candidate HTML to that same path and replace its static
  manifest entry; do not copy another default daily entity back. The original
  JS/renderer/vendor/archive dependencies remain in use; no package-wide delete.
- The current live homepage has a SHA-pinned compiled navigation injection;
  the task's App.vue does not own that accepted injection. The builder's
  build_homepage_entry checks its exact bundle SHA, index SHA and unique href
  anchor, changes only the research link and emits a new content-named bundle.
  Initial href and click/focus/pointer-entry read the current URL date. No date
  means the workbench selects its latest saved directory day.
- Only the old main-DoI_EeJQ.js bundle may be moved after confirming that the new
  index is its last HTML/module reference. The build receipt names the fixed
  dist/待删除/legacy-homepage destination. Stage logic is unchanged.

## One-time local import

Root's stable destination is:
  /Users/lexi/Library/Application Support/com.lexi.v4.local/state/research/classification/

The Writer builds the review candidate under E/classification. Copy current.json
and only its referenced versions/<content-id> directory to the stable root,
preserving exact bytes. Database references inside the manifest are relative;
the root path can change without altering artifact SHA. Preserve original ZIP/
source JSON evidence separately; requests never read or download those files.

Explicit offline command from the app/source root:
  PANEL_PYTHON -B -m infrastructure.research_classification_view --source-refs SOURCE_REFS.json --output CLASSIFICATION_ROOT

The refs file maps A_SHARE, HK_CONNECT and CDR to exact absolute path/SHA records.
The import makes a read-only SQLite symbol index plus source, evidence, gap and
metadata tables. Identical inputs reuse the existing version; later imports
reuse unchanged markets and import only changed source hashes. No API read or
scheduler imports/fetches sources. Current/index advances after the immutable
database and manifest exist. New classification content invalidates only its
classification view; it does not recalculate a price, event, return or formula.

Create a new private host binding with classification_store_root set to that
stable root. Preserve the old hash-bound binding and OBSERVATION_CONFIG. Root
activates the API-only r2 role; this delta requires no Main restart.

## Read-only interface and identity

GET /api/v4/research/workbench/classifications/HK_CONNECT returns all935 received
historical rows, metadata and qualification exceptions; A_SHARE and CDR remain
separate catalogs. It is research material, not today's executable universe.

Current D29 candidates are mechanically checked by exact complete code and name:
244 of247 bind, including one CDR from its separate source. The three name
conflicts 002694.SZ, 003032.SZ and603007.SH retain both names and get no applied
classification or searchable labels. No fuzzy name join or stock identity repair.

Axes remain separate: main business/industry, official major category, original/
normalized/external trading themes, catalyst/event date, chain/robotics role.
The UI shows source reference date, original publication/read/observation timing,
historical/supplemental provenance, status and gaps. UNKNOWN/empty is retained.
Robot/chip/commercial-aerospace multi-label filters take a deduplicated union
of existing labels/text inside the current view. They never mutate any pool.

The source is PARTIAL: A5575 major5509, original shortline themes nonempty423,
Top200 original themes196; other axes have distinct denominators. HK935 is
667 source buy-list records plus268 historical rule-derived sell-only records;
213 unresolved channel records correspond to136 codes. None is a current BUY
gate. CDR is excluded from A5575. Source publisher rights/usage limits remain.

## Review and deployment boundary

The new tests cover redirect/query/backup/hash safety, actual browser requested-
date isolation, exact join/CDR/name conflict, persistent reads after source
removal, unchanged-market reuse, theme-union/UNKNOWN and read-only HK catalog.
Existing R4 behavior PASS is reused. Root separately stages actual role paths,
checks real homepage/new entry/classification UI and requests one delta review.
Only a real role manifest/activation/API/UI receipt proves installation.
NATURAL/PIT/data-certification and unresolved source gaps are not upgraded.

RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false;
orders_sent=false.
