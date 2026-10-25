# Announcement repair source bundle

This source-only review bundle contains 36 restored frozen candidate files, the isolated fixed-fact completeness repair and its focused test, and the offline saved-stream verifier (39 source/test files). Files retain their original bytes; MANIFEST.json records SHA-256 identities.

Independent acceptance covers source recovery, the two saved-stream accounting differences, and the isolated fact extractor repair (17 focused tests, 9/9 quote locators). The original saved model output remains a semantic FAIL because its fixed ledger contained three incomplete claims. The repair does not rewrite or re-accept that historical result.

This bundle has not been integrated or deployed. The independent page, runtime-boundary fixes, live API/UI and natural-slot acceptance remain NOT_RUN. First cutover remains BOOTSTRAP_CUTOVER_BLOCKED. No additional announcement model request was made.

The fixed-fact module under research/announcement-fact-completeness-20261025 is an isolated candidate copy of the existing extractor, not a second deployed producer. Its synthetic tests can run offline. The complete saved-canary regression used a private V4_FIXED_FACT_SAVED_INPUT environment path; raw inputs and model responses are intentionally excluded.

This directory alone does not reconstruct a complete V4 environment: the historical 379-file dependency baseline, runtime state, credentials, raw announcements, model request/response records, logs and build outputs are excluded. Global Codex hook/configuration changes and private rollback backups are also excluded. Existing accepted results and failures remain in local custody.
