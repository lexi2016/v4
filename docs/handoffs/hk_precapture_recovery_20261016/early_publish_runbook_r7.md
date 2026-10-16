# R7 early-HK projection: guarded publication runbook

**Preparation only.** This document does not authorize publication. Run only after an independent R7 reviewer reports PASS and the parent explicitly authorizes execution. Do not alter source, frozen receipts, A-share, `STAGE_0925`, `STAGE_1300_1315`, or Stage R1. The older `early_publish_runbook.md` describes R6 and is not an R7 activation instruction.

The successful R6 retry receipt records the drain sequence and its observed exit conditions, but contains no reusable activation-helper path. Use the existing release-lock/CAS utilities and this R7-specific sequence; do not create or invoke a second recovery producer.

## Frozen candidate and preparation pins

Refresh all active values at execution time. If the active API is no longer the recorded base, stop and preserve the new active release; do not activate R7 against a different base.

| Binding | Prepared value |
|---|---|
| Active base | `announcement-connect-api-20261016-r2` |
| Base manifest SHA256 | `63d1244ec11aa81d74ade566c42da41947ed0a580b2f27ea74b2f286e77dd089` |
| Base inventory SHA256 / entries | `eaafe64cd512e79b83dd48a6920efb267e868dff8f44e38ed8c270778523c1de` / 1230 |
| Base `app.py` SHA256 (same reviewed R6 early fallback) | `76ea0556478c301d7758451e7c5dda02e4480991fa433244ba59e0eac0d5d21c` |
| Prepared active plist SHA256 | `04ecb0906ca5b46f296c9ece249a8c2c3a99134719176824fa33847ecdba24dd` |
| R7 candidate | `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/hk-morning-selection-recovery-20261016-r7` |
| R7 manifest / inventory SHA256 | `bfde3721184d186e2b92f1747eb9d16219face2dc353e4e0be7de8a31e67ad47` / `572ccb3a44ce195bb54ef3ee67ae03c40ce93cc1c0a81931a54f64fb8aa95a58` |
| R7 `app.py` SHA256 | `34a3fbccbe25bd901256f423fe77714c4701f4e838fe442731376793f9810149` |
| Staged plist SHA256 | `2b902b87f17575258c5b483fe38f8cb1c02ab036bc14013adf2a14206cb37924` |
| Independent R6 activation retry reference | `EARLY_ONLINE_ACTIVATION_RETRY_R2_RECEIPT.json`, SHA256 `97c7ddab1045f8b4a8e2db9a1499e45a3e72ed3722f68b5e9f1ba18054341805` |

R7 differs from its fresh base only at `apps/api/v35_api/app.py`: the exact HK response gains `selection_markets.HK_CONNECT.trade_date` and `stage_id`. Candidate verification recorded one delta path and 1,229 byte-identical non-delta inventory entries.

## Preflight under the gateway lock

Acquire `/Users/lexi/Library/LaunchAgents/.com.lexi.v35.api-only.release.lock` using `shared_api_release_lock`. Hold it through CAS, readbacks, and any rollback. Fresh-read the active gateway plist and release. Require the base release ID, root, manifest SHA, inventory SHA/count, and plist SHA to match the values recorded in the newly consumed R7 review/build receipt. Require exactly one expected loopback API listener on `127.0.0.1:8873` and record its PID. Then run `verify_api_release_candidate` for the R7 root with `expected_manifest_sha256=bfde3721184d186e2b92f1747eb9d16219face2dc353e4e0be7de8a31e67ad47`, `active_pointer="base"`, the held `lock_lease`, `require_shared_lock=True`, `role="gateway"`, and `base_role="gateway"`. Any mismatch stops before plist or service changes.

The four R6 backfill stores and matching runner receipts are already installed. Reuse them **read-only**; do not rerun the recovery helper, regenerate artifacts, copy, or reinstall anything. Verify each exact store tree and runner receipt against `EARLY_ONLINE_ACTIVATION_RETRY_R2_RECEIPT.json`; stop if a path is absent or a hash differs.

| Stage | Backfill run | Store-tree SHA256 | Runner receipt SHA256 |
|---|---|---|---|
| `STAGE_0930_0935` | `hk-morning-20261016-stage-0930-v1` | `329084062bb443913fd96e50bd55764be2b27ded3f5b12f30a1be8a33604194d` | `7705fd6b8393e2cbe2dfebdd12bead7d370511ce24c01440ca161ab1edb659af` |
| `STAGE_0935_0940` | `hk-morning-20261016-stage-0935-v1` | `eb161ff7f500247b38ad02c56e7ddb3e06bac6f03b483cfe7fab1997b672bd72` | `e6c3ea14d193a3cdc6f4a622b0c55d7176087316da1d4d3217dbe175f5eb0b60` |
| `STAGE_0940_0945` | `hk-morning-20261016-stage-0940-v1` | `eb74318c92ae4b48b33cb68718597814c2a1dcf9787bd3812925b4c6998d20f8` | `64573855d3ed3a4e7454dd27cbd207fa4d1bf95e238f4e7510404bcf662d749d` |
| `STAGE_0945_1030` | `hk-morning-20261016-stage-0945-v1` | `ef8e53fdb80cc198ec8f4bae48fbde0ea4e9059d733d5ed05bcf5544a2455552` | `b286e07ed50e8b8c806661939cb4c2b441d28f0fd1bf627925a908f8145e7ec0` |

Capture the immediate pre-cutover A-share, `STAGE_0925`, `STAGE_1300_1315`, and Stage R1 identities and protected receipt hashes using the same API/state evidence standard as the R6 retry receipt and its independent protection review. Compare post-cutover evidence to this immediate snapshot. Read only; any changed protected identity stops the cutover and is reported. Recompute the D-1 pool file SHA256 at `/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data/preselection_pools/20261016/hkconnect_d1_top100.json`; require `78646320d1140bb574b6aee66c9bd6b51f57ca0797fd96e4f2775e245a57efd8`.

## Cutover and drain gate

Create a unique, non-overwriting rollback directory outside the release package. Copy the exact current R2 plist bytes and mode; verify its SHA256 equals the fresh CAS plist pin. Stage the R7 plist from the candidate beside the active plist under a unique sibling name and verify its SHA256 equals `2b902b87f17575258c5b483fe38f8cb1c02ab036bc14013adf2a14206cb37924`. Do not replace the active plist before the service has fully exited.

Run `launchctl bootout gui/501/com.lexi.v35.api-only` once. A successful return is not proof of exit. Poll until all three conditions hold together: launchd reports the service absent, the recorded old PID is dead, and there are zero listeners on port 8873. Use the R6 retry's explicit `service_absent`, `old_pid_alive=false`, and empty `listener_pids` gate; its observed drain took 341 ms. Allow at most 15 seconds, checking every 100 ms. If the full gate is not reached, do not bootstrap; stop and report the observed state.

Only after the drain gate passes, atomically replace the active plist with the verified staged R7 plist. Read it back and require `read_active_release` to report the R7 ID, manifest, app root, and inventory pins before bootstrapping. Run `launchctl bootstrap gui/501 /Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist` once. Wait for launchd running, one API PID, exactly one `127.0.0.1:8873` listener owned by that PID, and a successful local HTTP check. Do not retry bootstrap blindly.

## API and UI readback

For each of the four stages, issue the same default workbench request used by the UI, with its default limit made explicit:

```text
GET /api/v3/workbench/stage?date=20261016&stage=<STAGE_ID>&limit=50
```

Require HTTP 200 and `selection_markets.HK_CONNECT.trade_date == "20261016"` plus `stage_id == <STAGE_ID>`. This is the R7 schema-identity check that the previous UI path rejected. Also require ten HK rows, `PARTIAL_WITH_ROWS`, `OBSERVATION_UNVERIFIED`, source `CANNOT_CONFIRM`, original `HK_ACTIVE_SNAPSHOT_UNAVAILABLE`, after-cutoff/PIT evidence, and formal/natural/production flags false. All rows remain `NO_BUY`. For each response, require `market_readback_bindings.markets.HK_CONNECT.target_pool_sha256` to equal the just-read D-1 pool file SHA.

Open the existing stage workbench and verify its actual request uses `limit=50`, the frontend validator accepts each response, and all ten rows render without a read error. Compare A-share and the protected stage identities/receipt hashes to the immediate preflight snapshot. Do not use a successful API response as proof of UI acceptance or natural-time validity.

## Rollback and stop conditions

If R7 startup, schema validation, API readback, or UI rendering fails, do not alter the four backfill stores. Under the same lock, boot out R7 and wait for the R7 job absent, its recorded PID dead, and port 8873 listener set empty. Only then atomically restore the exact backed-up R2 plist bytes and mode; verify the backup hash and `read_active_release` identity before bootstrapping R2 once. Wait for R2 launchd state, PID, sole listener, and HTTP health using the same full-exit/startup gates. If rollback bootstrap fails, stop and report exact state; do not repeat blindly.

Stop before any change if CAS/base pins differ, a protected identity changes, a backfill hash differs, the drain gate times out, the listener is unexpected, or R7 review/parent authorization is absent. Keep A, `STAGE_0925`, natural `STAGE_1300_1315`, Stage R1, and scheduler state untouched.
