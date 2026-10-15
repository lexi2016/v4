# Live scheduler identity and inheritance review

```text
schema_version: v4.oversold_daily_scheduler_live_identity_review.v1
status: PASS_LIVE_IDENTITY_INHERITANCE
reviewer_identity: /root/oversold_daily_review
observed_at_utc: 2026-10-15 18:28:30 UTC
active_release_id: zsxq-pdf-ocr-scheduler-20261016-r4
active_release_manifest_sha256: 4710696eb61e60ac5dbd1ea56aa2e7a3762d9c1f9170d206b4dc0beac4769e91
```

This read-only check confirms the current LaunchAgent process identity, the r4 manifest chain to the independently reviewed oversold r1 candidate, byte-for-byte inheritance of the six reviewed files, and the manager-workbench config hash. It does not re-review the recovery helper or claim scheduler output behavior.

## Active process evidence

Read-only `launchctl print gui/<uid>/com.lexi.v35.scheduler` returned 0 and reported state `running`, PID `32762`, plist path `/Users/lexi/Library/LaunchAgents/com.lexi.v35.scheduler.plist`, program `/bin/bash`, and working directory `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/zsxq-pdf-ocr-scheduler-20261016-r4/app`. The active plist SHA-256 is `e347c7a08037948a1d1a40e392f8ad95ce28a2555306a94dcb17513346a82d72`.

The plist selects release `zsxq-pdf-ocr-scheduler-20261016-r4`, that same application root, and manifest `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/zsxq-pdf-ocr-scheduler-20261016-r4/release-manifest.json`. `ps` confirmed PID `32762` is running the configured interpreter from the selected V3.5 runtime with module `ops.run_v35_macos_scheduler_daemon`; `lsof` confirmed its actual cwd equals the selected application root. The manifest on disk hashes to the active selector SHA above.

The r4 manifest `base` points to `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/oversold-daily-auto-20261016-r1/app`, manifest SHA `d9750660f989198e9000b1686801ac514def52e27c5dff75c93bdccb3a4a05d6`, and staged-plist SHA `91d83bd16af4b7932fb07007651339ee3978aa8a293d72e25e828962c8403072`. This is the candidate identified as `PASS_RUNTIME_RELEASE` in [`RUNTIME_INDEPENDENT_REVIEW_R2.md`](RUNTIME_INDEPENDENT_REVIEW_R2.md). The active manager config selector remains `/Users/lexi/Library/Application Support/com.lexi.v4.local/config/manager-workbench-v7.json`, SHA-256 `65684e5eb7657390747c089db74047d6a2c67d7f5de1bd3fe757a62f120965ca`, matching the frozen expected hash.

## Six-file inheritance check

For each path below, the SHA-256 in `runtime_exact_delta.json` (`candidate_sha256`), the bytes under the active r4 app root, and the r4 manifest's `application_inventory.entries` hash are identical. All six checks passed.

| Path | SHA-256 |
| --- | --- |
| `v4/manager_workbench/scheduler.py` | `0672296a340ae84d6bfb48b77b8d23566ea32b4fdb27edc505ea3abb4d785990` |
| `v4/manager_workbench/inputs/source_bindings.py` | `4e9339675d544a5f57e0fe6c5bc5522fba7b9aac6fdc21d6967082cfb7729edb` |
| `v4/manager_workbench/service.py` | `338544fc7876170e05566b5df90c31058a275fa8076f6474b80ab2bd7e19997e` |
| `v4/manager_workbench/store.py` | `493df1a72bf4c4a533ae533ce5fc0185c9d9536d01c4e88082270908c8b1aa18` |
| `v4/manager_workbench/oversold_daily.py` | `1a88ac9c1bb3e1a2d68fff350a69204a65b7ebb782f27512bb4fc1c45f9b0583` |
| `upstreams/v3_shared_data/shared_data/hk_daily_supplement.py` | `62513b42bcd133d3c447b9b797b81c19f43a306c9544ce97a11447db93b54e9e` |

No identity, inheritance, or config-hash mismatch was found. No tests, recovery command, service control, network request, or active-state write was performed. API/UI readback, the next scheduled output, and natural-slot behavior remain `CANNOT_CONFIRM` in this review.
