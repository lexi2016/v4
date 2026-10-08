# V5 shadow milestone: review-fix candidate

Status: IMPLEMENTED_NOT_TESTED. No deployment, real-owner admission, natural run, or visual acceptance is claimed.

The preceding product baseline b0532fef13888749acca296b25244dc2ebc0b9ca passed 68 tests on the Mac's isolated locked environment (Python 3.14.6, pandas 2.3.3, pyarrow 24.0.0). That result does not cover this candidate. Review tests at bcffbcc5c84e2f766296ae258aa0aab8d36dac63 have not run: the original Mac execution transport failed. The user explicitly authorized implementation from the static review while deferring execution until the Mac recovers. No cloud replacement test was run.

## Changes and remaining evidence

1. Synthetic input identity: stream-hash the actual file map before and after the original reader, reject changed or falsely declared identities. The map uses relative paths and SHA-256, canonical JSON. Bounds: 2,000 files and 2 GiB total. This is not an OS snapshot or an owner read lease. OWNER_VERIFIED input remains rejected.
2. Dependencies: compare actual distribution versions and import origins to the fixed lock. Record the observed environment JSON and its hash. A mismatched or missing environment cannot attest the lock. Python's major/minor floor remains; no patch-version pin was added.
3. Index/reference binding: match the requested cache key and target date to the cached reference; match the CLI-requested run to the actual reference and result.
4. Failed attempts: CANNOT_CONFIRM, FAILED and PARTIAL are separately archived, never cached as complete successes. Existing successful artifacts remain intact. Completed and valid-empty immutable snapshots remain idempotent.
5. Master cutoff: inspect the original reader's security-master witness captured_at. Missing/naive/unparseable time or a time after research_cutoff is rejected in the V5 wrapper. Frozen vendor code and the two selection gates are unchanged.
6. Directory durability: create directory components in sequence and fsync their parent links before publishing visible references. This needs the targeted ordering regression and further fault/concurrency testing; it is not a claim of a physical power-loss experiment.
7. Source execution: launch the worker with a fresh empty bytecode-cache prefix. Use the new source-bundle entry script run_shadow.py for the outer CLI or read-only web viewer, so V5 imports cannot silently select timestamp-based caches from the source directory. Direct python -m imports are not the source-only launch contract.

Runtime identities add optional dependency-environment observation fields. Old artifacts lacking those fields retain their historical key/readback interpretation; they do not become newly verified environments.

## Mac continuation

Reuse the existing isolated test directory and locked interpreter. Apply only the fixed candidate delta, verify byte identities, and retain all original failure logs and assertions.

1. Run tests/test_review_guards.py (10 cases). These tests were authored before this repair but their RED execution was blocked; do not fabricate a RED result.
2. Run the full unittest discovery command over tests. At this revision there are 78 intended cases: the preceding 68 plus 10 review regressions.
3. Report every failure, warning, skipped case and actual dependency version. Do not edit product code or weaken assertions to pass locally.
4. Retain the existing visual-acceptance blocker separately. HTTP/HTML tests are not a browser screenshot/refresh acceptance.

Source-bundle entry points (use the actual isolated interpreter):

- python -B run_shadow.py check --composition COMPOSITION_JSON
- python -B run_shadow.py run-shadow --composition COMPOSITION_JSON --request REQUEST_JSON --output-root PRIVATE_SHADOW_ROOT
- python -B run_shadow.py read-result --output-root PRIVATE_SHADOW_ROOT --target-date YYYYMMDD --run-id RUN_ID
- python -B run_shadow.py web --output-root PRIVATE_SHADOW_ROOT --port UNUSED_LOOPBACK_PORT

The web service is read-only and loopback-only. Starting it is a separate explicit local test action; this candidate does not install a service, choose an occupied port, or take over V4.

## Still outside completion

Actual Mac verification of these changes, multi-process/fault coverage, real-owner snapshot admission, real volume-unit proof, browser visual acceptance, automatic daily scheduling, independent multi-module environments and production cutover remain outstanding. Existing documentation describing earlier phases is historical and must not override this status.
