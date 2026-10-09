# Small owner-adapter and Mac installation contract candidate

Base 0477911e4548682c70d974dad708249438346d8c. Its Mac P0 evidence is 26 unique PASS, including 20 fresh-root rounds / 80 claims / 20 attempts. Old RED is syscall fault injection, not proof of the Darwin kernel cause. This increment has NOT_RUN Mac acceptance and no installation/deployment.

## Exact existing owners and behavior

- US remains the existing isolated us_mapping_daily owner. It retains MANUAL_RECOVERY and fixed registry scope; ledger SUCCEEDED is only original COMPLETED/VALID_EMPTY execution, never broad selection or natural verification.
- Rebound calls run_rebound_daily and read_rebound_observation from a separate clean checkout pinned to 2d8e38ec61792b3e75581f96318e9c284f72b7ba. No business source is copied. The child uses the same Python environment but an isolated namespace. Exact HEAD and clean source/vendor/contracts are checked before/after. The original owner retains input deduplication and interrupted-run reconciliation. NATIVE_VALUES_OBSERVED is recorded as BLOCKED selection, with the independently read original reference preserved. Its original lock implementation is unchanged; all scheduled users must enter via the common ledger, not concurrently invoke an uncoordinated direct owner process.
- Announcement calls the existing verified offline owner twice, without capture/import. Even CONSUMED is BLOCKED until the separate decision revision and independent reviewer contract are bound. The supplied short revision e06d was not resolvable in available remote branches; full commit/path requested. No legacy analysis is relabelled as a reviewed decision.
- run_manager_daily uses the existing run_manager_plan refresh, original saved product, independent reader and same attempt verification. The common ledger admits one exact request. Partial plan save/readback is retained as BLOCKED business acceptance; an uncertain save leaves RUNNING and is not retried. No ordinary API generation is activated here.

## One dispatcher, explicit daily input bundle

`daily_tick.tick` calls existing daily_dispatch; launchd is only a wake-up. No new collector or market scheduler is created. Missing or invalid lane does not stop other lanes. Actual HK target/calendar, supplied schedule/deadline and US source rules still apply; no default trading slots are guessed. Rebound selects prior completed full HK session inside its original owner. Half-day slots require explicit binding. HK Connect is never replaced.

Private config fields: `enabled` (start false), absolute `ledger_root` and `bundle_root`. Use separate V5-marked directories; ledger marker is `.v5-daily-run-ledger` = `v5.daily-run-ledger.v1\n`; bundle marker `.v5-daily-bundles` = `v5.daily-bundles.v1\n`.

Bundle filename is actual HK YYYYMMDD.json. Fields: target_date; jobs; optional manager_request. Each job: lane; research_cutoff; owner_request; scheduled_at; deadline; half_day_bound; max_attempts. No identity hashes need guessing: tick derives code/config/dependency and exact request hashes from registered adapters. Preserve the bundle/cutoff for retry; changing inputs intentionally creates another identity.

owner_request contracts:
- us_mapping: unchanged existing US request.
- announcement: binding (existing exact offline root/SHA/target/publication), cutoff equal to research_cutoff.
- rebound: owner_checkout (clean separate pinned checkout), request (original rebound observation request), output_root (original marked observation root).

manager_request is the unchanged original refresh request, prepared AFTER products with actual cutoff and exact root/file/reference SHA. Without this prepared request, tick reports BLOCKED_POST_OWNER_REQUEST_MISSING; it does not guess file paths, use old references, or backdate a clock. Automatically assembling this post-owner request remains an integration gap; this candidate supplies the real save/readback adapter, not a claim of fully automatic three-lane closure. The ordinary manager API remains on its current generation.

## Mac render / acceptance / explicit installation / stop contract

No command below was executed in cloud. Use existing independent Mac task, a private candidate checkout/environment, private config and separate V5 roots. First run synthetic acceptance once:

```bash
PYTHONPATH=V5/src:V5/tests python3 -B -m unittest test_us_mapping_scope test_run_ledger test_daily_dispatch test_daily_us_owner test_daily_owner_adapters -v
```

Expected 35 unique tests: previous26 + adapters9. Includes announcement CONSUMED still blocked, changed readback rejected, numeric rebound blocked, same-input blocked dedup, original manager saved/readback once, wrong attempt rejected, disabled no-op, disabled launchd contract, one bad lane allowing other lanes. These mocks are not real owner acceptance.

Render only, with absolute paths:

```bash
/ABS/V5_PYTHON -B /ABS/CANDIDATE/V5/src/v5_shadow/daily_tick.py --config /ABS/PRIVATE/config.json --render-launchd --python /ABS/V5_PYTHON > /ABS/PRIVATE/com.lexi.v5.daily.candidate.plist
plutil -lint /ABS/PRIVATE/com.lexi.v5.daily.candidate.plist
```

Rendered plist has Disabled=true, RunAtLoad=false, label com.lexi.v5.daily.candidate and 300-second wake-up; business execution remains gated by explicit job windows. Default disabled config is a no-op. After Mac acceptance and explicit installation coordination only: preserve the old candidate config/plist, set config.enabled=true and plist Disabled=false, then use the existing user's launchd domain:

```bash
launchctl bootstrap gui/$(id -u) /ABS/PRIVATE/com.lexi.v5.daily.candidate.plist
launchctl enable gui/$(id -u)/com.lexi.v5.daily.candidate
```

Stop the V5 candidate only:

```bash
launchctl disable gui/$(id -u)/com.lexi.v5.daily.candidate
launchctl bootout gui/$(id -u)/com.lexi.v5.daily.candidate
```

Then set config.enabled=false. Preserve ledgers/products; restore any previous candidate config/plist only after bootout. Do not touch V4 launchd labels, services, data roots, permissions or dabcfbee preview. Unknown attempts require original owner readback reconciliation, not deletion/reset. Actual automatic installation, approved slot resolution, decision/reviewer binding and natural/cross-day verification remain NOT_RUN/BLOCKED.
