# Frozen announcement resume and deployment protection

Adds a hash-bound resume button for interrupted Flash tasks, preserves completed/failed parts, and adds an all-target deployment barrier sharing the submission lock. An explicitly bound orphan exception also holds the existing model lock during cutover. The original saved input and pinned authority root are used; capture, prompt, model, validator, and trading gates are unchanged.

Independent pre-deploy acceptance passed: 109 Python tests and 5 frontend tests. Seven legacy Python fixture preconditions fail on obsolete latest-job IDs; the other 109 pass when only those seven are excluded. The frontend build passed; four existing full-typecheck test/fixture errors remain.

The local release `announcement-resume-20261018-r1` was integrated from the then-active release, deployed, and verified through API and rendered UI. The terminal reviewer marks the feature `BEHAVIOR_VERIFIED`, API `API_VERIFIED`, and UI `UI_VERIFIED`.

The authorized manual resume made exactly one model request, lasting 114.404 seconds. It failed with `PART_FIXED_FIELDS_MUST_BE_EMPTY`; the job ended `PARTIAL` and continuation was disabled. This is not complete selection success. The 24 prior successful parts and 15 prior failed parts were preserved. Five historical-success parts remain blocked by source/plan provenance differences. Six zero-attempt synthesis inputs remain pending; their future automatic consumption is unconfirmed. No retry followed the failed canary.

The 15 earlier failures share a prompt contract conflict: the range profile requests `changes`, while the later part instruction requires it empty; the structured schema allows nonempty arrays that the part validator rejects. This delivery diagnoses that issue without changing the frozen prompt or rerunning those failures.

This bounded handoff contains necessary source, tests, documentation, the exact batch diff, and compact verification. It is not a whole-runtime snapshot. See `source-manifest.json` for baseline and file hashes, and `verification.json` for acceptance boundaries. Raw announcements, model inputs/responses, runtime directories, logs, credentials, and build assets are excluded.
