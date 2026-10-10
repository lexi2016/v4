# M05 independent final review

## Verdict

**REVIEWED / BEHAVIOR_VERIFIED** for the bounded read-only engineering behavior described here. The hourly research lane uses the frozen owner, only falls back on `FileNotFoundError` when both preview inputs are present and SHA-bound, and isolates enumerated source-data rejection shapes from healthy lanes. No blocking issue remains in that scope.

This verdict does not establish natural verification, point-in-time correctness, or an OS-enforced sandbox. No commit, push, deployment, service operation, or production-store operation was performed.

## Identity and frozen bytes

- Pinned source: `lexi2016/v4`, `v5/module-isolation-20261008`, commit `02dbca5353a22c2e9ca55c1250b2cf9279800949`, tree `d3d92e0a959d4534a603d55fa0b8058cc6ef2e6d`.
- The local reconstructed candidate HEAD is `c8ef453b2bf7f7c083e06fe2bf3bdb0c7da304c9`, not the pinned GitHub commit. The source tree and relevant restored base blobs were verified against the pinned tree; the candidate should not be represented as a checkout whose local commit equals the remote base.
- Final product hashes: adapter `ab023e461aa816064347d5619e07276d635f24db5d7aacf693034d2903a72472`; source manifest `f9b9ebc9fd6a6b08c81f31399c187026aa2cf7259c521a6a02e3c1e82d7f6dee`; tests `f1f3fb47fa7e683da403fc8f7d2ac5830cb50777b0536ea6a4ea2e48b10cfdb6`; docs `71408fc4f2c41ea64aa39b4329e3b855be0be0ecc77dd309abc5af90c3ade6b2`.
- The 40-entry source capsule matches its declared byte sizes and SHA-256 values. Its canonical identity is `d0fddbcaa1d5eb22f50edd5d651976b8bc2643122bc951b31733448dea8e23e4`; frozen `hourly_pool.py` and `research_store.py` hashes are `d4f808dab2639b02c08cf2619057cad4454f72b1e9b95703805360c7f8f56dad` and `4460d35b5d22b2f80bac7699f532d033fd514b57ddebc33bff6242d14e6f9dcc` respectively.

## Independent checks

- Using the pinned Python 3.14.6 environment, I independently ran `test_sha_bound_schema_invalid_hourly_isolated_from_five_healthy_lanes` and `test_sha_bound_hourly_json_root_shapes_isolated_from_five_healthy_lanes` against the final hashes above: **2/2 passed** (`review/M05_FINAL_P1_INDEPENDENT.log`). The probes bind the altered payload bytes through the manifest and receipt, demonstrate that the same valid preview pair produces one `RAW_SOURCE` row through the frozen preview owner, and verify the invalid hourly lane is rejected while all five healthy lanes remain accepted (`PARTIAL`, `row_count=5`). Covered cases include invalid schema, JSON list/int roots, article and stock-pool shape, article fields, source-count shape, and a non-iterable dedupe declaration.
- I independently reran `test_worker_boundary_violation_is_never_optional_input_error`: **1/1 passed** (`review/M05_EXPECTED_ERROR_BOUNDARY_INDEPENDENT.log`). The final adapter uses finite, research-specific exact error sets. Unknown `ValueError`, arbitrary runtime errors, and `WorkerBoundaryViolation` remain fatal; it does not broaden the fallback catch. The bounded adapter diff is saved at `review/M05_ADAPTER_DIFF_FINAL.diff`.
- An independent AST check compared the frozen validator's 42 literal `ValueError` messages with the exact adapter allowlist; none are missing. Dynamic message forms were checked against the finite article-field, timestamp, stage-evidence, and string-list enumerations (`review/M05_VALIDATOR_ALLOWLIST_AUDIT.log`).
- Writer's final pinned full run is **29/29 passed**, log `evidence/M05_FINAL_FULL_PINNED.log` (SHA-256 `82e7fda63c81af64a2df5f9277b6691167ed8f611811de24a1a087169f8cbada`). The final writer receipt binds the current product hashes and that log in `evidence/M05_FINAL_WRITER_RECEIPT.json`.
- The preserved wrong-date full-worker case uses a usable SHA-bound preview/selector pair. A misfiled archive remains `CANNOT_CONFIRM` with `row_count=null` and the exact manifest/receipt refusal; it does not become a preview result. A healthy hourly lane does not read preview bytes. Empty unavailable inputs remain `CANNOT_CONFIRM`/null. The Mac UTC exception remains bound to the exact system UTC alias and physical timezone-database target; `PYTHONTZPATH` cannot redirect it to an input root. The guard is explicitly documented as Python-level protection, not an OS sandbox.

## Archived owner differential and limits

I independently verified and replayed the archived normal input: 65 regular files (32 hourly payload/receipt pairs plus manifest), no symlinks, inventory SHA-256 `4aacbd14687a312671a01a5cc39f53ed2c3b59551232474ebe7d8695eee2d71c`. The archive contains no preview or selector. Full canonical artifacts, including row order/scores/IDs, and source SHA matched the frozen owner:

| Replay | Rows | Artifact SHA-256 | Owner source SHA-256 | Scope |
|---|---:|---|---|---|
| 20261009 / signal 20261008 | 211 | `0a7f3a0103209d3166135d546c0f5261df124084a080c1ed32d32e703b0845b2` | `bd2da8a8729c82d9d0c6f510c190d2960b154c8b8eb1f6a4d912a622de8c7bae` | Archived normal-window replay |
| 20261012 / signal 20261009 | 152 | `588cf0ac73f23c29bf0628372dabfe7a4f8cce4f2fa0aa02beefbc218c58c916` | `c391fcdd213b183b6f3e04d82b4d9955b1831d5d1c82b3a58ef760499b1dd78c` | Friday-only bytes; incomplete Monday window |

The recorded differential was run against adapter SHA-256 `705534230375dc0fd237acb5c203c84f5bcfd2c405210caee85aef4e2f13426d`. The final adapter adds finite invalid-input refusal classification; the successful owner path was not rerun against the later classifier-only SHA. The final full test run and independent targeted boundary runs are against the final adapter SHA above. The normal-path evidence is therefore reused as bounded replay evidence, not restated as a final-SHA differential.

The 20261012 archive has no Monday artifact and cannot verify a complete Monday window or its 09:00 boundary with real data. Real preview fallback is also unverified because the archive lacks the preview/selector pair; only the frozen preview owner was exercised with a synthetic, valid pair. Natural and point-in-time verification remain false. V1.9.2 verified-empty compatibility remains a separately documented contract gap; the checked V1.9.2 non-empty path is the verified scope.
