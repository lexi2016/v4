# Prepared scheduler overlay; no activation performed by Writer

The controller has user authorization for independent review, bounded deployment, GitHub sync, and subsequent natural checks. This document is a concrete handoff, not an activation receipt or acceptance verdict.

## Candidate and preservation

Final reviewed-target local candidate: `local_only/us-mapping-natural-scheduler-20261021-r4/`. Its `app` is the actual scheduler parent plus exactly five allowed source files. It is not a replacement from historical Git. The source overlay and each before/after SHA are in `OVERLAY_SPEC.json`; `PREPARED.json` binds the final manifest and config. The canonical Git branch already contained yesterday's three-file wiring repair. New Git source changes are native template refresh, resolver fallback, and PREOPEN diagnostics only.

The old parent release manifest lists 871 entries; the actual parent has 872 non-cache entries because of the pre-existing `upstreams/review_core/.DS_Store`, SHA `de3be1dd5f9e047bcbc508cd0570567669de847b5cc82b69cc85c1b03bb2c099`. Controller explicitly accepted preserving this exact file. The guard verifies every old manifest entry and this one extra file, plus the full 941-file actual freeze including bytecode. There is no claim that the old manifest was an exact full inventory. The candidate preserves all other actual parent bytes, including its unrelated native/history/TDX behavior.

The new runtime config is `us-industry-observed-scheduler-20261021-r2.json` inside each candidate release. This config version remains r2 because config bytes did not change when source candidate moved from r2 to r3 and then r4. Only `/source_bindings/hk_industry_classification/observed_policy_template` is added. Existing dated pins, HK holiday contract and every other value are preserved. The complete config, original config and original/proposed plists are local only because operational fields may be sensitive. `CONFIG_DELTA.example.json` contains only the sanitized industry template.

## Activation sequence for controller after independent PASS

1. Verify Reviewer receipt binds the final source, tests, overlay spec and runtime manifest SHA in `PREPARED.json`. Complete controller-owned Git sync with explicit allowlist and remote byte readback. Do not upload `local_only` or the release body.
2. Run the read-only guard immediately before preparing the formal destination:

   ```sh
   PYTHONDONTWRITEBYTECODE=1 python3 docs/handoffs/us_mapping_natural_fix_20261021/preactivation_guard.py
   ```

   It requires exact current parent/config/plist/PID/cwd, zero active scheduler children or established TCP connections, zero queued/running workbench attempts, and terminal receipts for today's dispatcher claims. A busy result means retain the healthy workload and wait for its terminal event; do not stop it. Any source/config/PID drift requires bounded controller review. This guard is point-in-time, not an atomic scheduler lock.
3. Prepare a NEW immutable formal destination, never overwrite r2, r3, r4 or another existing release:

   ```sh
   python3 docs/handoffs/us_mapping_natural_fix_20261021/prepare_candidate.py --output '/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/us-mapping-natural-scheduler-20261021-r4'
   ```

   This command only prepares. It rechecks the full parent before and after. The resulting source hashes must match the independently reviewed local r4 exactly; its manifest/plist identity hashes differ because destination paths differ. Verify that the only app delta is the same five files and that config structural delta remains the single template addition. Retain the new formal `PREPARED.json` locally and record its identity before activation. The original plist/config backups are inside this NEW release, never inside Git.
4. Re-run the read-only guard at the actual switchover. Immediately after it passes, use the existing `com.lexi.v35.scheduler` label lifecycle only: `launchctl bootout gui/<uid>/com.lexi.v35.scheduler`; confirm the old PID exits and the label is absent; copy the reviewed formal release's `scheduler-proposed.plist` bytes to `/Users/lexi/Library/LaunchAgents/com.lexi.v35.scheduler.plist`; `launchctl bootstrap gui/<uid> /Users/lexi/Library/LaunchAgents/com.lexi.v35.scheduler.plist`; `launchctl kickstart gui/<uid>/com.lexi.v35.scheduler`. If any step fails, inspect actual state before another action. Do not kill children, replay a job, alter scheduled tasks, or replace an unrelated service.
5. Read back the new positive PID, cwd, loaded command and launchd environment source/config/manifest identities; verify five source SHAs and full candidate manifest inventory, plus actual loaded config SHA. Verify research flags remain true/false/false/false as specified. An HTTP response from the separate API process does not establish the scheduler's loaded source. No API release change is part of this overlay.

## Conditional rollback

Only if the active scheduler still belongs to this exact new release and no workload is active, boot out this label, confirm absence/PID exit, restore the byte-identical `scheduler-original.plist` (expected original SHA `80125421f00e29cc2dbaa629395ec12c0b87dc4380d2699a8fbeaf3a769e6f1a`), then bootstrap/kickstart the same label. The restored plist points to the retained original config SHA `10cb6ca6446c145b735e7aa51f6928063b96c68a7ee7908b011dbe6f52d57809` and original release; neither requires rewriting. Read back original PID/cwd/source/config identities. Do not overwrite a later release or delete any business history, run, pointer or candidate. Record failed activation separately; do not mark rollback or service start as natural success.

## Natural verification after release

The isolated frozen replay is an offline derivative and never a replacement for today's existing PREOPEN result. Do not backfill or rewrite the 2026-10-21 09:25 snapshot.

Capture the first actual post-activation scheduler run automatically produced by its existing schedule. Bind its job/run, generated/available times, scheduler PID/cwd, five source hashes, config/manifest SHA, target HK date and US session. Check the fixed classification retains observed date 20261014, captured_at `2026-10-14T11:03:29.919614+08:00`, UNKNOWN source_asof, PARTIAL, non-PIT; D-1 master date/manifest/artifact and frozen US quote identity remain independently visible. Daily HK rows must deduplicate and catalog placeholders must not form legacy source paths. Formal eligibility remains CANNOT_CONFIRM; observed rows do not count as recommendations. The eight medical relations retain their existing recovery/applicability states.

Then verify the next natural trading-day 09:25 result (expected 2026-10-22, subject to the unchanged official calendar), including the actual prior source run and cutoff. An existing PARTIAL run whose rows are all filtered must be PARTIAL with retained source run/input/gaps and per-reason counts; absent prior execution stays NOT_RUN. Valid VERIFIED subsets before or exactly at cutoff remain eligible for the original gate. Future/missing evidence stays excluded. Do not change membership periods, relation states or thresholds to obtain rows.

If there is no valid natural slot or complete lineage yet, report `NATURAL_SLOT_UNVERIFIED` / `CANNOT_CONFIRM` and leave the healthy scheduler running. No new heartbeat, collector, model call, schedule change or task duplication is authorized by this plan. Independent review, integration, deployment, Git sync, loaded-runtime verification and natural results remain separate states.

R4 incremental review prerequisite: INDEPENDENT_REVIEW_R3.json retains REVIEWED_FAIL. Both findings are addressed by REVIEW_FIXES_R4.diff and the 24-case affected test command. Only source_bindings.py and service.py differ between r3 and r4; prior ordinary frozen-input checks are reused and do not imply r4 overall acceptance. Activate only after controller verifies the independent r4 verdict binds final PREPARED/overlay/test/runtime hashes.
