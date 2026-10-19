# Pending activation and rollback

No activation is authorized by this document. Gate: independent source/candidate preservation PASS plus controller continuation, with the exact final PREPARED.json and source/config hashes. Source changes after that review need a scoped incremental receipt.

The fixed target is US20261019 -> HK20261020. NYSE official calendar resolves the US close to 2026-10-19 16:00 EDT / 2026-10-20 04:00 HKT, and the existing producer slot to 04:15 HKT. Future runs use the existing official calendar/session functions, not a hardcoded target day. Natural evidence is NOT_RUN before that slot.

Before switching:

1. Recheck all three active plist raw SHAs and their exact active release/manifest identities against PREPARED.json. Any new parallel change stops the switch; do not overwrite it.
2. Recheck each candidate's complete manifest inventory and source SHA; verify the scope config SHA. Preserve original plist raw backups in local_only.
3. Inspect current API/scheduler job lifecycle. Do not terminate healthy in-flight work merely to hurry this release; wait for its bounded completion or report the ownership condition.

Switch order: API, then persistent scheduler, then the dedicated short-lived producer. For each role, write only its prepared candidate plist, run `/bin/launchctl bootout gui/501/<exact label>`, wait at most 16 seconds for the SIGTERMed job to disappear (print returns 113), and then `/bin/launchctl bootstrap gui/501 <exact plist path>`. A job already absent skips bootout. On unexpected lifecycle state, inspect and stop instead of repeating bootout/bootstrap blindly.

The API and persistent scheduler retain their existing KeepAlive behavior. Read back running state/PID/cwd after bootstrap; if a loaded API/scheduler job needs its existing explicit start, only that exact job may be kickstarted. The short-lived `com.lexi.v4.us-market-digest` **must never be kickstarted** during activation. Its original RunAtLoad=false and absent/false KeepAlive are retained; no StartInterval, QueueDirectories, WatchPaths, Sockets or MachServices start trigger is added. All four existing StartCalendarInterval entries remain 04:15, 05:15, 21:00 and 22:00 HKT. Loading that job prepares the next existing calendar event; it is not an instruction to fetch now.

Role labels:

- API: com.lexi.v35.api-only
- Scheduler: com.lexi.v35.scheduler
- Producer: com.lexi.v4.us-market-digest

After each switch, read the corresponding launchd identity. API checks are GET /healthz, GET /readyz and GET /api/v1/runs/date-list?date=20261020; check manifest identity and RESEARCH_ONLY/false trading flags. Scheduler identity includes its in-process WorkbenchHook and original scheduled-lane config. Producer should remain loaded and idle until its original slot. No manual run POST, provider call, historical backfill or extra scheduler is part of this activation.

Rollback restores only the prepared original raw plist for each changed role, then uses the same inspected bootout/wait/bootstrap lifecycle. Use the actual loaded state: if bootstrap previously failed and a job is absent, restore original plist and bootstrap it directly. Never call kickstart on the dedicated producer. Retain every old release and every historical plan/receipt; rollback does not delete or rewrite business data. Verify old identity/health after restoration. Do not claim rollback was exercised unless actually performed.

Natural acceptance after 04:15 uses the existing producer receipt and existing scheduler cursor/job/plan store: ORIGINAL_TIME_CAPTURE, POST_CLOSE US20261019, exact payload/receipt/manifest SHA, supplementary frozen547 scope from the same provider response, and SCHEDULED/NEXT_DAY US_MAPPING for HK20261020. Read that exact new run through API and rendered manager-selection page. Existing US20261016 MANUAL/NEXT_DAY plans are retained and cannot substitute for this event. Record invalid/missing quotes as gaps; a failed or legally controlled late event must retain its actual timing classification and cannot be promoted to a natural-slot PASS.

No new background monitor, cron, LaunchAgent, port or producer is created. Monitoring/wakeup ownership belongs to the controller's separately supported continuation mechanism. A prepared release or current manual/API PASS does not prove the future event.
