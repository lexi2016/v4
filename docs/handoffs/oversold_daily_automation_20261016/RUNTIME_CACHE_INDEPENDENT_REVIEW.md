# Independent runtime-release review

```text
status: PASS_RUNTIME_RELEASE
reviewer_identity: /root/oversold_daily_review
writer_identity: oversold_daily_writer
candidate_release_id: oversold-daily-cache-20261016-r1
candidate_release_manifest_sha256: 03f1c61fe881039b286bd4d0d9acbcb29d32593747e7c0119b8e3c261237bfb2
candidate_staged_plist_sha256: 12fec20f665af3ce0a20ffd2c989684ff580c36ae2d932fdc285bb798e93d137
recovery_helper_sha256: 558014d5364fb589817958918916b7325338728019439567ff0310a0c95b6128
behavior_verified: PASS_PREPARED_PLAN_AND_MOCK_CHECKS
activation: NOT_AUTHORIZED_NOT_PERFORMED
```

## Findings

P0: 0. P1: 0. Blocking P2: 0.

Nonblocking P2 boundary: `SCHEDULER_CACHE_CUTOVER_PLAN.json:11-16` lists the pinned independent source-repair review as an activation requirement. The current source review is present, has status `PASS_CACHE_FIRST_REPAIR`, and its SHA-256 is the pinned `fcd4541507fd76baa3b49de27d150f01f902e3eb611a78c6a9504786d617cab8`. The activation core verifies the candidate preparation receipt, candidate manifest/plist hashes, manager-config and active-plist CAS, and a distinct candidate-manifest-bound runtime review (`scheduler_release_cutover.py:312-342, 352-359`), but it does not itself recheck the source-review path/SHA. This does not invalidate the current prepared candidate or this review: the source evidence was independently verified and the runtime review is bound to the exact candidate manifest. Whether a future operator separately enforces the plan's source-review prerequisite before activation is `CANNOT_CONFIRM`; activation remains not authorized.

## Frozen identity and delta

The candidate manifest on disk hashes to `03f1c61fe881039b286bd4d0d9acbcb29d32593747e7c0119b8e3c261237bfb2`; its staged scheduler plist hashes to `12fec20f665af3ce0a20ffd2c989684ff580c36ae2d932fdc285bb798e93d137`. The binding pins the r4 base manifest `4710696eb61e60ac5dbd1ea56aa2e7a3762d9c1f9170d206b4dc0beac4769e91`, active plist preimage `e347c7a08037948a1d1a40e392f8ad95ce28a2555306a94dcb17513346a82d72`, and manager config `65684e5eb7657390747c089db74047d6a2c67d7f5de1bd3fe757a62f120965ca`. The active plist still matches the saved preimage; the candidate remains staged.

I independently compared the release manifests' physical inventories. Each contains 1,029 entries (908 files and 121 directories); exactly the two authorized source paths differ. The other 1,027 physical entries match byte/mode inventory rows, agreeing with the declared non-delta digest `f7f36aafc7bd7d48d06e63b16d6f700a2b7b2da850ecc5970de057a6dc35a44f`. The application inventory has 855 file entries and agrees with its release manifest. The two changed source hashes are the values pinned by the binding and candidate manifest.

## Wrapper and identity checks

The candidate-bound cutover adapter checks the binding SHA and reviewed core SHA before delegating to the shared cutover implementation. The activation and rollback paths require explicit authorization references; activation additionally requires the exact candidate-bound independent runtime review, and rollback requires a matching successful activation receipt and the exact candidate-plist CAS. The wrappers did not bypass those core gates.

Read-only live inspection verified the currently running *base* scheduler: launchd PID `32762`, r4 app root, configured interpreter/module, plist selector, manifest selector, manager-config selector, and process cwd all matched. This is not evidence that the candidate is active. A mock of the candidate recovery identity validator accepted a dynamically supplied PID `54321` with candidate selectors and rejected a wrong launchd program (`/bin/zsh`); it wrote no files and started no service. The candidate's actual live PID identity remains `CANNOT_CONFIRM` until a separately authorized activation.

Focused wrapper checks returned:

- Activation default: `PREPARED_ONLY`, `launchctl_called=false`.
- Rollback default: `PREPARED_ONLY`, `launchctl_called=false`.
- Recovery `--plan`: `RECOVERY_PLAN_ONLY`, `network_or_formal_run=false`, bound to the candidate manifest SHA; candidate PID is null while the base release remains active.
- Recovery launch path: the existing recovery core imports the candidate plist environment into the child process and launches the candidate-configured interpreter (`recover_oversold_20261016.py:393-411`), so a shell without `V4_MANAGER_WORKBENCH_CONFIG_PATH` does not by itself break the wrapper.

The recovery wrapper SHA is `558014d5364fb589817958918916b7325338728019439567ff0310a0c95b6128`, its candidate binding SHA is `bee081cef3b5327b90d738d3fca3ca6610cff59fd702afb91c18e57b37422334`, and the pinned recovery core SHA is `b757420def3382d363331d8a6bc46c28eced034bdf220f2d7fa60a639d00da5f`.

The prior independent source-repair review at SHA `fcd4541507fd76baa3b49de27d150f01f902e3eb611a78c6a9504786d617cab8` covers the exact two-file r4 delta, the focused 18-test suite, and the disposable offline cache replay retaining 567 READY rows. Those tests and the offline replay were reused by receipt and SHA; they were not rerun for this wrapper review.

No service control, activation, rollback, recovery run, network request, owner-data write, or formal run occurred. Live candidate recovery, API/UI readback, and natural scheduled behavior remain `CANNOT_CONFIRM`.
