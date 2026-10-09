# Real announcement binding: test-only next candidate

Verified production remains `bb61f2ec259c0140d0065de14b109a0b41ebf1c3`.
Mac reports 8 targeted tests PASS, real US09 plan run
`2c0e63535fe24083b6cb18e150cf4020` saved/read independently MATCHED, followed by
316 full-suite PASS / 0 FAIL / 0 ERROR / 0 SKIP (74.049s). No cloud rerun.
The new branch contains only tests and this audit; no production or capsule
bytes change. The ongoing preview remains on fixed bb61f2e.

## Direct findings

| Step | Finding at bb61f2e |
| --- | --- |
| Path/count admission | 694 manager + 64 material files fit the existing 8192-per-binding count; declared announcement/handoff prefixes and material blob/index paths are supported. Reuse the original exact relative paths and SHAs. |
| Snapshot size | The actual 21,861,605-byte corpus fits, but manager `_snapshot` incorrectly permits 32MiB for **all** files and 128MiB per group. The approved announcement contract is 32MiB only for `announcement_agent_runs/[0-9a-f]{32}/evidence/body_corpus.json`, 16MiB otherwise, 64MiB per group. This is an over-admission defect, not a reason to truncate the corpus. |
| Private copy | Every declared byte is written at the same relative path under a temporary group root. All 624 handoff references must be included; source files are not mutated. Direct original handoff readers see these private files. No generic 16MiB JSON serializer is applied to the raw corpus copy. |
| Original reader version | `announcement_analysis.py`, `workspace_announcements.py`, `announcement_source.py`, `announcement_catalog.py` match the already-verified announcement capsule byte-for-byte. Do not replace them or switch to an older validator. |
| Original consumption | `workspace_announcements.read_selection_inputs` calls `read_reviewed_analysis_references`, then `read_analysis_consumption`. An existing product invokes `service.get_announcement_analysis(target, publication)`; `announcement_analysis.read` invokes `service.get_announcement_date_catalog(target, publication)`. Neither method is present on the manager adapter service. This is a concrete missing binding. AttributeError is not caught by this original consumption path. Empty inputs in prior tests never exercised it. |
| IO enumeration | `OverlayIO.files` now delegates to the original private SafeRoot for announcement markers; read_bytes/directory follow the same routing. Durable plans retain their own root. This protocol passed the existing Mac tests, but real 758-file consumption remains unverified. |
| Output | Worker/API limits remain 16MiB. Actual composed workspace size has not been measured. The existing announcement API passing does not establish the size of the full manager workspace. No truncation or generic size increase is authorized. |

Reader hashes (both capsules):
- announcement_analysis.py: `b60b8c0c663b203d2ece5a5b451eb41ca296396b2db3630dff4a92a8566f373f`
- workspace_announcements.py: `ea259666727b71c78760d666f3fe7f90350829bdce5f2b55745927528546af04`
- announcement_source.py: `4e5a03048c3791ef65a4ef4eef37c75f5fc30ebb41615984e302b2b6d6666f2b`
- announcement_catalog.py: `25b07260dbe6591a6b26c3560d1873fe2e01fd76edd07a55d977bb80b0696a68`

## Minimal next implementation after independent regression evidence

1. Apply the existing exact-path announcement input limit helper to manager
   snapshots and restore 64MiB per group. Keep 16MiB worker/API output limits.
   Do not change the already-verified announcement bridge or reader capsule.
2. Bind two thin service methods to the original `announcement_analysis.read`
   and `workspace_announcements.read_date_catalog` using the same private
   service/store/material roots. Do not import full service.py, fabricate
   analysis DTOs or bypass original handoff, judgment, receipt or cutoff gates.
3. Reuse the existing request's manager/material roots and all 758 raw SHA pins.
   Use a separate initialized V5 plan root and an actual aware composition
   cutoff after all real source/review/import timestamps. First read with
   target 20261008, explicit publication 20261007 and view=dynamic. This is an
   as-of historical recovery, not proof of a 10/8 preopen plan or natural run.
4. Explicit manual refresh keeps original MANUAL_REFRESH, then a second adapter
   read must return the same saved plan and terminal attempt. Preserve the
   33 selected / 54 watch / 75 unassessed observations and their original gaps;
   these counts do not establish formal target-date eligibility.
5. Target09/publication08 remains NOT_IMPORTED with nullable unknown counts.
   The original default source window may retain older products with their own
   dates; never relabel an 08 product as the missing 09 analysis. The explicit
   09/08 regression prevents that substitution.

## New regression candidate

`tests/test_manager_announcement_binding.py` contains six tests:

- Accept the exact real corpus path/observed byte size without truncation.
- Reject ordinary and lookalike paths above 16MiB.
- Reject an announcement group exceeding 64MiB while each file is legal.
- Feed the actual expanded package through the production adapter and original
  workspace consumption; verify source immutability, original counts, date
  binding and output size.
- Save a real manual recovery plan and independently read the same plan/attempt
  and consumed announcement identity.
- Keep explicit missing target09/publication08 unimported and counts unknown.

The size fixtures are valid JSON padding for byte-boundary tests, not business
fixtures. The three real-owner tests require the existing expanded request:

```sh
# Reuse the existing V5_ANNOUNCEMENT_REQUEST_PATH pointing at the 758-file package.
PYTHONPATH=V5/src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s V5/tests -p 'test_manager_announcement_binding.py' -v
```

Expected unverified failures on unchanged bb61 production: overly broad file and
group limits, and existing-product consumption hitting the missing service
method. Report actual ERROR separately from assertion FAIL; an import/fixture
error is not evidence that original consumption reached its business gates.
Only AST, diff and source-byte comparisons were performed in the cloud.

## Actual missing inputs/evidence and retained next tasks

- This cloud workspace has no original 758-file input package; its exact
  request and data remain in the existing Mac task. Reuse them, do not recollect.
- Target09 announcement analysis is genuinely absent. Nothing in this candidate
  creates it or upgrades the old 9/30 master/unknown eligibility.
- Real composed workspace size, complete original cutoff consumption and saved
  announcement identity await that same Mac's regression run.
- After this owner binding, retain run lifecycle/idempotent dispatch work:
  exact input/cutoff/source identity, latest attempt versus latest success,
  duplicate suppression, terminal failure recovery and real daily scheduling.
  A MANUAL_REFRESH with natural_verified=false is not daily completion.
- Later improve check_manager_plan_request.py to persist the full independently
  read envelope with its SHA and plan identity, enabling publish_generation
  without another read. Current publish_workspace_read performs another read;
  it is not a pure publisher of an existing envelope. Never substitute the raw
  plan document for the original ordinary GET payload. No script change here.
