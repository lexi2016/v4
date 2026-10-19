# Announcement transport recovery

A system memory guard rejection ended the frozen announcement batch while unattempted tasks remained. The recovery entry now admits only the source-bound transport failure, runs exactly one canary, and permits original pending tasks only after persisted strict validation. Existing successful records and evidence are preserved. Four semantic failures are not automatically retried.

Independent review rejected the first candidate for missing current-request drift checks and a long-part copy NameError. The bounded revision passed 15 impacted checks; prior 100 Python, 5 UI and 5 canonical integration checks are reused.

`source/` contains the exact six deployed source and test files. Apply `canonical-preservation.patch` to those sources to reproduce the canonical workspace versions, preserving pre-existing R8 recovery changes that are not newly deployed. Per-file SHA-256 values are in `verification.json`. The release also preserves concurrently deployed mapping changes outside this scope.

The local API identity is verified. Live single-item recovery and pending continuation are separate acceptance stages and were pending at this source handoff. No raw announcements, model responses, credentials, runtime release files or built assets are included. Research only; no BUY or order changes.
