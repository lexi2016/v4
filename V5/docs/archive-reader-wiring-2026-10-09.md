# Archive owner wiring candidate

Scope: original R10 ResearchLaneSource + ResearchArchiveStore + HourlyResearchStore
in a separate process/capsule; no change to US mapping, manager algorithms, V4,
thresholds, qualification, quote units or close-finality gates.

Frozen source is commit 8342862f05ca9f6516f51b3164b6110651e5af77, api variant
resolved through its manifest snapshot_path. All 90 source files preserve exact
manifest bytes. The separate capsule prevents its three older US dependencies
from replacing already verified manager/US modules. No collectors are invoked.

Optional request.inputs.archives uses the existing `{root,files}` input schema:
root must be absolute, separate from manager/materials/us/output; files map
relative paths to raw SHA256. Required manifest.json remains byte-identical;
allowed files are research/archives/YYYYMMDD.json,
research/hourly/live/YYYYMMDD/HHMM.json and corresponding receipts/ paths.
The manager pins/copies all supplied bytes before starting the archive child and
reads original inputs again after the manager result. Existing 64 MiB per-input
set and 16 MiB per-file limits remain; oversized input fails, never truncates.

Mac authority: /Users/lexi/Library/Application Support/com.lexi.v35.local/state/data.
Original ledger provenance is its sibling dispatcher. The archive worker does
not read the ledger; original artifact_binding reports that binding policy.
US remains on its separate v4 root. Do not select artifacts by desired symbol.
Supply the complete exact-window daily/hourly file set and receipts; preserve the
original manifest rather than manufacturing a filtered one. A manifest-listed
missing payload/receipt remains an original reader rejection. Other dates may
also produce diagnostics when their files were not supplied; only original
workspace context.source_dates are consumed in the plan.

Original read_exact/list_slots/artifact_binding execute in the child. The parent
proxy transports their validated payloads, bindings and error type/message; it
does not validate bare JSON as an owner product. Original workspace then performs
projection, material/PIT filtering, relation evaluation and plan persistence.
Input acquisition timestamps remain untouched. Newly available input requires a
new actual cutoff/run, never insertion into the old 12:23 plan.

archive_readback reports validated artifacts, rejected artifacts/slot lists,
supplied raw file hashes and reader capsule pin. Binding paths use stable declared
source provenance rather than transient cache paths. This is verified file-set
coverage, not complete-source or full-market proof; source_origin_verified and
natural_verified remain false. No accepted relation is promised.

Python read-only/network/process guards and original SafeRoot protect the private
reader execution; this is not an OS sandbox. Original root is never passed to the
child. Plan refresh/readback and ordinary API remain the existing manager path.

Mac validation (cloud only parsed AST and checked frozen SHA/diff):

```sh
cd /absolute/v4/V5
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_manager_archive_reader.py' -v
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_manager_plan*.py' -v
```

Seven synthetic tests target archive/hourly original validation, missing slot
receipt, semantically wrong receipt despite matching raw hashes, source mutation,
root separation, stable repeated identity and same-run plan save/readback. They
are test fixtures only. No cloud runtime RED/GREEN is claimed. Mac should first
confirm the new test fails against the previous manager adapter (archives input
rejected), then verify this fixed candidate. Existing successful independent Mac
UI 58/58 is unrelated and is not added to these test counts.

Real Mac run must report exact file selection, bytes before/after, original
semantic rejects, window coverage, plan/attempt readback and natural=false. The
historical full relation trace accepted zero; archive integration restores real
coverage and honest rejection, not a guaranteed nonempty recommendation list.

## Supplied Mac snapshot for this candidate

Use the existing isolated snapshot, no new collection:
`/Users/lexi/Documents/Codex/2026-10-08/task/V5-archive-input-20261009T065822Z/research-data`.
Set request.now to `2026-10-09T14:58:22.011193+08:00` for this snapshot's
reported cutoff (or an explicitly recorded later actual evaluation cutoff).
Original plan window is October 7–9, focus starts October 7 16:10.
Map the 65 research-data relative paths to raw hashes from the existing evidence;
do not include the evidence or authority-data directories in this input group.
32 payloads + 32 receipts + original manifest total 3,153,007 bytes.
Manifest SHA: cc8796973cc0818b04b6c35e14fb4a307d391fc312169dccba903ca6894305f0.
Snapshot index SHA: 50070217277ae55bbcc6fe99f0cd18d48eedca0dd6284a708cc3fec084628f69.
Mac reports original readers 32 VERIFIED / 0 FAILED and 1,735 undeduplicated
articles, stable source/copy hashes and no new slot during capture. That receipt
does not prove material projection, relation acceptance, PIT, or target eligibility.
The old authority-data master index is deliberately not bound by this change.
