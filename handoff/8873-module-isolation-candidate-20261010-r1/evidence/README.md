# SYNTHETIC_ONLY release evidence

This run exercises supplied test helpers and the actual existing Python builder/integration primitives. It does not call a native publisher, launchctl, service reload, HTTP health check, or Mac API/UI. The label and port in synthetic metadata are declarations, not proof of a running service. Shared locking, exact-base verification, candidate construction, inverse-delta preparation and isolated plist mutation are exercised.

## Observed run

Started: 2026-10-10T15:11:53.294409+00:00

Actual command (this run's paths):

```sh
/workspace/scratch/a245cda1e07c/testenv_final/bin/python -B /workspace/scratch/a245cda1e07c/analysis/generate_synthetic_evidence.py --code-root /workspace/scratch/a245cda1e07c/work --fixture-root /workspace/scratch/a245cda1e07c/analysis/scenario-fixtures-run2 --evidence-root /workspace/scratch/a245cda1e07c/analysis/synthetic-evidence-run2
```

`run-summary.json` contains the outcome and exact counts. There are three independent fixture scenarios: A → B → latest B → reverse A (including deletion of A's added file); same-G A/B candidates with stale-B rejection and rebuilding B from A; and B → A.

Each candidate directory contains original manifest/delta/build/plan JSON bytes, their source-path/SHA provenance, full app inventories, static/state inventories, and non-target preservation checks. Commit receipts are explicitly synthetic helper receipts. Initial owner contracts are synthetic fixtures with approval_id SYNTHETIC_TEST_ONLY. No real owner is approved by this run.

## Artifact and portability rules

This export contains JSON evidence, this README and the runner. It contains no app/dist directory, plist file, complete environment, credentials or real owner product. Synthetic plist paths and hashes appear as evidence; plist contents remain only in the fixture directory. Static and state entries are hashes and inventory metadata of fixed synthetic bytes.

All original receipt bytes, absolute run paths and SHAs are preserved. The export is an evidence record, not a relocatable active release. Moving these JSON files does not rebind their embedded paths; never rewrite paths while retaining old hashes. Re-run the script with an explicit source root and NEW, disjoint fixture/evidence roots to generate new paths and new SHAs:

```sh
/absolute/path/to/python -B /absolute/path/to/generate_synthetic_evidence.py \
  --code-root /absolute/path/to/work-or-full-after \
  --fixture-root /absolute/existing/parent/new-fixtures \
  --evidence-root /absolute/existing/parent/new-evidence
```

Use the supplied test environment with pytest available. Roots must not already exist, must have existing canonical parents and must not overlap. The runner prevents subprocess/network calls and explicitly roots all fixture/evidence paths in its two new directories. This is not a general filesystem syscall sandbox. No natural-language business/API/UI verification or Mac service continuity is claimed. Safety remains RESEARCH_ONLY=true, production_allowed=false, buy_gate_updated=false, orders_sent=false.
