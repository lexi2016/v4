# 2026-10-05 source synchronization scope

This branch publishes the authorized sanitized source bundle, not a code repair or release.

- Parent: `615d1ce5417ed65ca2c8b736435c5d4596b79b19` (Git history only; not an active runtime baseline).
- Package: `v4-running-source-20261005-sanitized.zip`, 6,676,343 bytes, SHA256 `c7f89eec30a9b44eb974078d2db0a0f42fc79480734cd7ca5fdf863b7de9f1b0`. ZIP itself is not uploaded.
- Exact 1464 package files plus CURRENT_STATUS_ZH.md and this scope note. Existing root README retained.
- 1417 deduplicated source paths; 3075 references across canonical 1354 / API 881 / Stage 840. All 32 shard hashes, source SHA256, byte sizes and Git blob identities verified.
- API is R10; Stage is R3. Canonical includes distinct uncommitted development. Follow README_ZH.md and materialize.py to reconstruct a selected layer into a new directory. Never overlay an entire layer on an active installation.
- Root AGENTS.md is the approved project rule copy, SHA256 `fd790799d7ae8913088eb716ebe29da51c21e57681966240691542978e2d84c0`; no global configuration, permission or hook changes.
- Package safety recheck: no prohibited runtime/dependency directories, no files over 5 MiB, no hard-secret pattern findings. Configurations are sanitized examples; no raw market data, accounts, large responses or plans included.
- CURRENT_STATUS_ZH.md is the read-only report completed before this synchronization. Its NOT_RUN GitHub-write status describes that earlier audit phase; this branch publishes that report without rewriting its historical claims.
- Business tests, dependency installation, service execution, API/UI and natural-session checks: NOT_RUN in cloud. Source hash/CRC validation is not E2E acceptance.
- No merge, production deployment, collection, trading, historical data rewrite or other branch update.

Remote verification will be recorded outside this commit after publication, avoiding a self-referential commit claim.
