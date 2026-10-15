# Daily OVERSOLD root cause and scope

Read-only Luna Max audit observed scheduler PID 90252 at 2026-10-16 00:37 Asia/Shanghai, label com.lexi.v35.scheduler, persistent-minute mode. It loads release hk-tdx-conflict-repair-main-20261015-r2/app and manager-workbench-v7.json. The API uses a separate release and the single-day 10/15 recovery config. Scheduler pins only cover 10/12 and 10/13.

NEXT_DAY submits after 16:30 and persists a source-date cursor. The 10/15 attempt was earlier than exact-date panel publication 17:20 and master capture 17:30, correctly returned PARTIAL, retryable=false, but the cursor suppresses later attempts. TDX61 has an existing cache-aware owner but no daily readiness/capture orchestration. Retrying the old cutoff is invalid.

Relevant paths: v4/manager_workbench/scheduler.py, binding.py, supervisor.py, inputs/source_bindings.py, inputs/native.py; upstreams/v3_shared_data/shared_data/hk_daily_supplement.py capture_tdxpy_window_supplement; LaunchAgents com.lexi.v35.scheduler.plist and com.lexi.v35.api-only.plist. Old cursor nextday_20261015_e20bef1a44833b22.json and attempt18425e50e6294f15a6bc02ac881c5af2 remain evidence. Manual run5cb9b603e183428cab8de8990abcb7e3 is not natural acceptance.

Frozen behavior: preserve other lanes and phase visibility, exact source date and parent SHA, actual cutoff, existing producer and cache. Add readiness/capture/submit state and bounded transient retries, idempotency across repeated ticks/restarts/concurrent claims. Never declare empty/failed source successful. Terminal source quarantines may remain PARTIAL. No threshold, pool or trading changes. Candidate review, deployment and later natural result are separate.
