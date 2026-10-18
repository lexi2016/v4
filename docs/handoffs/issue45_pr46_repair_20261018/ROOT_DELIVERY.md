# Issue 45 candidate repair delivered

The candidate source repair and independent offline behavior acceptance are complete. The code remains on Draft PR #46; no merge, deployment, service operation, notification, or trade was performed.

- Repository / branch: `lexi2016/v4` / `codex/issue45-us-close-repair-20261018`
- Source baseline: `a56dbdaff45f887e7f8dbb38047a66d09fe5b1db`
- Incoming PR head: `579c71d997424d058ff6ebffee911eeb7cf92bbb`
- Verified repair commit: `2bc6f66b64e3d0b13b8b907339684fd6711a9411`
- Independent result: `REVIEWED=PASS`, `BEHAVIOR_VERIFIED` for frozen source and offline consumer scope; no unresolved P0/P1/P2 findings.
- Focused tests: **7 passed**. Frozen baseline: **228 passed, 3 preserved known failures, 1 explicit out-of-scope deselection**.
- GitHub readback: all 14 changed source/test/document/verification files matched exact bytes and expected hashes at the fixed repair commit. See GITHUB_SYNC_RECEIPT.json.

## Resulting behavior

The existing dispatcher date contract resolves Shanghai 2026-10-17 04:15 to US session 20261016 and HK target 20261020. Owner receipt validation rejects missing or conflicting required identity without inventing optional fields. The existing US_MAPPING lane pins artifact, receipt and cutoff identity, keeps new input pending behind an active old-input job, and recovers exact retryable jobs after cursor persistence failure. A saved partial plan is not marked consumed merely because it exists; its associated successful job must justify consumption.

The consumer preserves the complete existing overlay as non-selectable observations and keeps its relation counts separate from 33-symbol quote coverage. Independent offline execution against existing runtime owner files preserved all 667 catalog stock records and 1,003 unique relation identities, including closure counts 757/221/25 and research-use counts 985/10/5/3. Seven field hashes and use_scope matched; all overlay decisions remained UNASSESSED. 649 stocks have relation rows and 18 catalog stocks have no relation row. Quote coverage was 33/33 with 0 assessed because Connect membership was not supplied to this canary.

## Evidence and remaining boundary

Read INDEPENDENT_REVIEW.md/json for exact commands, file hashes, scope and known failures. verify_real_overlay.py provides the read-only reproducible consumer check with explicit source/config/owner-root parameters; no full overlay or raw quotes are embedded or uploaded.

The independently inspected running API LaunchAgent uses the existing us-hk-recovery-v2r1-20261016-r2.json configuration, with a valid relation root and matching owner-file hashes. A retired path in another local default configuration is not evidence of a broken currently loaded configuration.

The candidate source was exercised in an isolated copy and pushed to the PR branch. Canonical business files and runtime releases were not overwritten. Candidate live dispatch, API/UI, notifications and natural-slot behavior remain CANNOT_CONFIRM until a separately authorized rollout and its acceptance. Issue #45 remains open; this result does not assert that the online automatic selection chain has recovered.
