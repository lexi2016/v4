# Isolated candidate preparation

Status: `ISOLATED_RUNTIME_UI_ACCEPTANCE_PASS`. Independent review receipt is recorded separately below. Nothing activated or deployed.

Frozen source: `c06db9db262b9c756d8401dcfc43b70d34c6f3ef`.
Reviewed entity changes: `97ff8531d`, `5419e52dd`, `8f39cdf67`, `c06db9db2`.
Inherited runtime manifest: `8f93397a31986a1871276ee90b7f4d89e2a31d5691eeb6ea529e0cbea67a481b`.

`ops/prepare_tech_debt_candidate.py` creates a new directory directly under
`/private/tmp`, containing `baseline/app`, `candidate/app`, independent manifests
and `evidence/static-receipt.json` plus `candidate-code.diff`. It refuses an
existing output, non-packaging commits after the frozen business commit, changed reviewed modules, an inherited
inventory mismatch, ambiguous patch context, deletions and non-allowlist deltas.
Its manifests keep `module_role=api`, truthful path identities and preparation
status. The official runtime inventory functions and
`dispatcher.validate_release_identity` validate both copies; the newer role
validator is not used.

Packaging HEAD may descend from the frozen business commit only through this
batch's explicit ops/tests/docs allowlist. Every business module and the complete
evidence file set must still match the frozen commit's blobs byte for byte,
including working-tree changes. Provenance records `business_source_commit` and
the actual `packaging_source_commit` separately; top-level `source_commit`
continues to identify the frozen business code.

The candidate starts from the inherited app, applies the official three optional
tech-debt overlay passes, and transplants only reviewed entity-filter hunks.
It preserves runtime optional-import fallbacks, snapshot recovery and the pool
assembler's scope calling convention. The preserved skill module's actual name
is `infrastructure/research_workbench_skill_r2.py`. Copies exclude `__pycache__`,
`*.pyc` and `*.pyo`; the official evidence-directory overlay now does likewise.

From the isolated source worktree, using the project's absolute Python with
`PYTHONDONTWRITEBYTECODE=1`:

```text
python -B -m pytest -q -p no:cacheprovider --basetemp=<new-test-temp> tests/test_apply_tech_debt_overlay.py tests/test_prepare_tech_debt_candidate.py
python -B -m ops.prepare_tech_debt_candidate --runtime-app <inherited-app> --source-root <frozen-worktree> --output <new-private-tmp-directory>
```

Recorded preparation result: 19 packaging tests PASS; 33 allowlisted app deltas;
full inventories, identities, unchanged frontend/non-delta files, no deletions,
11 inherited unique modules and no bytecode caches PASS. First pytest invocation
passed all cases but exited during cleanup of unrelated old pytest temp files;
using an isolated `--basetemp` resolved the test-environment failure without
altering old files.

Candidate entity tests ran with `PYTHONPATH=<candidate-app>`, candidate app as cwd,
`--import-mode=importlib`, `-p no:cacheprovider` and isolated `--basetemp`:

```text
python -B -m pytest -q ... <source>/tests/test_a_share_code.py <source>/tests/test_a_share_entity_filter.py
python -B -m pytest -q ... <source>/tests/test_tech_debt_candidate_protocol.py
```

The first command returned 49 PASS and two TypeErrors: those two tests directly
call the source branch's newer private `pool_store_class` signature. The second
command verifies those two cases through the retained scope protocol with the
same reviewed row/pool fixtures and actual candidate assembler; 2 PASS. It does
not patch the assembler or its response. The other 49 passing cases were not rerun.

HTTP, UI, independent review, natural execution, activation and deployment:
`NOT_RUN` by Writer. The controller owns subsequent isolated runtime validation
and Git synchronization. Raw data and runtime artifacts stay outside Git.

`RESEARCH_ONLY=true`, `production_allowed=false`, `buy_gate_updated=false`,
`orders_sent=false`.

## Controller acceptance completed on 2026-11-01

Candidate (retained, not activated):
`/private/tmp/v4-isolated-acceptance-20261101-writer-r1/candidate/app`.
Candidate manifest SHA-256:
`12e55bec59a077257ba0a0aa4403fab806ae07a5cfb06b5bacd4d77c85dd9b79`.
After all HTTP/UI reads its full inventory remains 1324 entries,
`d685ec81693ce11135704d39096eec6fd694ed0744f5a7e352b32a1c4a5d0839`.

The controller ran baseline/candidate on loopback 18873/18874 with the same
APFS-cloned inputs, plus a third HTTP process on 18875 for explicit regression
fixtures. The macOS process sandbox denied all writes under the user's home
and snapshot business-file writes. Only snapshot import-lock owner/mutex/temp
files were exempted. An official lock acquisition and an attempted RW open of
the catalog proved that distinction. All three temporary ports are now closed.

38 paired samples are comparable: `system_date=20261101`,
`date_catalog_sha256=029dcce96e26fcc4780ec83523fdc7f1e5c4f420e4e23e9d10fe1a988e2d2ae6`,
`selection_latest_sha256=e3302f70b8d2f8b2ad031c7b00cb531d8107f1fd3e4904cc80a8b8ac7d960a70`.
The catalog digest is explicitly a typed input-generation descriptor, not a
native file hash: the native catalog file is absent and its official fallback
clock is recorded, alongside the explicit source catalog/receipt/raw SHAs and
root manifests. Capture verifies content-file hashes before and after the run;
lock churn is excluded precisely, never by skipping business files.

28 responses are identical after the recorded cross-instance identity/clock
normalization. The other 10 contain only the contracted quarantine, count/page
or historical-annotation changes. A research-lane read diagnostic's
`update_diagnostic.observed_at` was separately checked as an ISO clock value
with less than 120 seconds skew; no business-field changes were hidden.
There are no unclassified changes and no new status errors. Existing responses
remain 409 for the two dated HK backfill probes and 422 for manager_selection,
mw_reviews and rg_authorities; those are inherited gaps, not repaired here.

- 20261030 pools: 643 -> 642; only research-pool code 261029 quarantined.
- 20261102 pools: 593 -> 591; only 261029 and 261030 quarantined.
- Every retained pool/aggregate row, field, order and published rank matches the
  baseline over complete pagination. Each date retains all 100 HK rows.
- Actual bound 20261030 research lane: 447 -> 445 (261029, 261030).
  20261101 lane and hourly artifact: 482 -> 481 (261030).
  Retained rows and their order/values match exactly. Original archive bytes
  are unchanged; this closes the earlier real-data evidence gap.
- Three historical stage responses add only the explicit invalid-entity note;
  selected rows, scores, missing_symbols and pre-existing diagnostics remain.
- Synthetic inputs published with official stores exercise real HTTP routers:
  an all-invalid pool returns ALL_ROWS_QUARANTINED with 1/0/1 counts, and saved
  archive/hourly mixtures preserve HK.00700 and 600519 while isolating 261029.
  Synthetic artifacts are labeled QA inputs and remain byte-identical.

The built-in browser verified the candidate badge, eight stage cards, SOP,
research desk and pool display. The research pool's visible first ranks are
1,3,4,5, with no A.261029 code cell. The complete stage-page network record has
one single-stage and one eight-stage batch request, GET only, no failed request
or runtime exception. Other long-lived network records truncated and are kept
as incomplete evidence; the research/sop/pool checks rely on their HTTP captures,
DOM/screenshots and empty browser error logs. No claim of a complete research-page
network trace is made. Agent-created tabs were closed and the original 8873 tab
was verified preserved; no held native input was used.

## External configuration change observed during acceptance

The controller did not write the online plist or invoke launchctl mutations.
Another operation changed only V4_WECHAT_ARCHIVE_ROOT at 18:56:55, from the old
V3 archive path to the V4-owned state/data/research/wechat_archive/articles path,
and the online PID changed 33574 -> 92334. Reverting that single value in memory
reconstructs the exact initial plist SHA, proving the complete plist delta.
Initial SHA: f390eab840f8c6871985c79b88c8fa748c43539bc934fd6994464451408d0dd5.
Current SHA: 5fd55f6d0cfeacfafd173bc8e76c87883e35894f80f6a0774ec5ed97cb8a562e.
Do not reuse the old plist CAS pin for a future cutover.

Only the affected configuration surface was rechecked: a new frozen copy of
the 23 index files (22 records), their unchanged original absolute archive-root
bindings, and read-only access to the current archive under the sandbox. All
1076 real archive files were content-hashed before/after; no binding was rewritten.
Four baseline/candidate HTTP bodies match exactly: nonempty materials READY (1),
mentions READY (48), the empty selected date NOT_INDEXED (0), and bound material
detail READY. The current-configuration research UI loaded without console errors.
The online app/release/manifest remain perf-runtime-repair-20261101-r1,
manifest SHA 8f93397a31986a1871276ee90b7f4d89e2a31d5691eeb6ea529e0cbea67a481b,
healthz 200 and execution identity verified. Online plist/PID did change externally;
this report does not claim otherwise.

## Local evidence and remaining execution boundary

Detailed artifacts, private paths and raw responses stay outside Git:
`/private/tmp/v4-isolated-acceptance-20261101/controller/` contains
`acceptance-classified.json`, both full captures, `fixture-http-results.json`,
`wechat-config-r2-receipt.json`, `external-config-change.json`, screenshots/DOM,
`post-validation.json` and `reviewer-final.json`. Writer/static/source-SHA receipts
are in `/private/tmp/v4-isolated-acceptance-20261101-writer-r1/evidence/`.
These are retained for the pending deployment decision; failed sandbox/capture
attempts are also retained. No raw inputs, captures, screenshots, runtime packages
or frozen research data are uploaded to GitHub.

Only packaging/capture tools, focused tests and this compact handoff are committed.
Independent Reviewer has read-only ownership; its final verdict is the separate
reviewer-final receipt. Activation, formal release-path/plist preparation, actual
cutover, post-deployment API/UI and natural-time acceptance are NOT_RUN. Moving
the package to a new app root requires path-bound manifest regeneration and
identity validation there. Future cutover must preserve the latest WeChat binding,
recheck the current plist CAS and use a prepared rollback plus job-unload polling.
This batch makes no performance, research-quality, PIT or trading-eligibility claim.
