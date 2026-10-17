# V4 Issue 45 source baseline

This branch contains the complete canonical source files required to continue the Issue 45 repair at their normal repository paths under `ops/`, `contracts/`, `infrastructure/`, `v4/`, and `tests/`. The code is the application source; it is not a bootstrap-only package and does not depend on a hidden local checkout.

Start at [`docs/handoffs/us_hk_source_baseline_20261018/README.md`](docs/handoffs/us_hk_source_baseline_20261018/README.md) for the source manifest, dependency requirements, focused test command, updated runtime identities, and unresolved acceptance boundaries. Use [`UPDATED_CHAT_PROMPT.md`](docs/handoffs/us_hk_source_baseline_20261018/UPDATED_CHAT_PROMPT.md) for the bounded four-breakpoint implementation task.

The source files in this branch are already present at their canonical paths. The `staging/` export/provenance cache exists only on the source machine; it is not included in this remote branch and does not need to be read. After starting a new isolated checkout, edit the canonical source directly and run the documented tests from the repository root.

Install the focused test dependencies from the repository root:

```sh
python -m pip install -r docs/handoffs/us_hk_source_baseline_20261018/DEPENDENCY_MANIFEST.txt
```

The handoff is a source baseline, not a completed business repair. API/page behavior, complete owner-overlay consumption, notifications, and natural-slot acceptance remain separate checks.
