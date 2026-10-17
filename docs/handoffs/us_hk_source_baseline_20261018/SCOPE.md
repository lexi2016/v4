# Issue 45 source-baseline scope lock

```text
GOAL: Export the complete, importable source and test dependency closure needed to continue Issue 45 from a GitHub checkout, with per-file provenance and a reproducible focused-test environment. This handoff prepares the source baseline only; it does not repair the four business breaks.
WRITER: /root/issue45_source_baseline_writer (sole writer for this handoff directory).
REVIEWER: /root/issue45_source_baseline_review (independent, read-only reviewer).
ALLOWED_PATHS: docs/handoffs/us_hk_source_baseline_20261018/{SCOPE.md,SOURCE_EXPORT_MANIFEST.json,DEPENDENCY_MANIFEST.txt,README.md,REMOTE_ROOT_README.md,UPDATED_CHAT_PROMPT.md,WRITER_RECEIPT.md,staging/**}; /tmp/v4-issue45-baseline-* for isolated verification.
FORBIDDEN_PATHS: canonical business source outside this handoff; release copies; live configuration; services and schedules; raw market data, full recovery overlay, account credentials; global hooks; other projects; prior handoff files; root integration records ROOT_DELIVERY.md, ROOT_LEDGER.json, GITHUB_SYNC_RECEIPT.json; reviewer-owned INDEPENDENT_REVIEW.md/json.
PASS_SIGNAL: Every staged file has a verified source path, SHA-256, and size; exported modules and focused existing tests run from an isolated copy with PYTHONPATH/PYTHONHOME unset and no canonical source path; dependency requirements parse and resolve in dry-run; baseline and runtime identity differences, excluded tests, and unresolved verification limits are recorded.
STOP_RULE: Stop at the bounded dependency closure. Do not fix business behavior, include unrelated source/data to force a broader suite green, change source/tests/config/services, commit/push, or claim runtime/API/UI/natural acceptance.
```

Canonical worktree at export: `/Users/lexi/Desktop/学习/v4_app`, `HEAD=55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054`; it was dirty before this handoff. The source snapshot was taken from the current worktree, not reconstructed from `HEAD`, and must not be described as a GitHub commit until the controller verifies and syncs the exact files.
