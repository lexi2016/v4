# Perf runtime repair result · 2026-11-01

All four requested software fixes are implemented and deployed locally. Independent review: PASS after two recorded corrections; see review-receipt.json. Cache and deadline regressions passed isolated tests; helper validation covers real pinned files and recovery ownership. Prior matching checks were reused.

Live release: `perf-runtime-repair-20261101-r1`, PID `32999`, manifest SHA `8f93397a31986a1871276ee90b7f4d89e2a31d5691eeb6ea529e0cbea67a481b`. Activation command returned `ACTIVATED_VERIFIED`. Current plist and the original pre-perf backup are retained; the task helper backup restores the exact pre-repair perf release.

The candidate inventory contains 1301 entries: 1299 unchanged and only app.py + preselection.py reviewed overlays. Its provenance identifies baseline bbed661f1441239f7a06f093418efb6ceab0c7cc plus reviewed file SHA; baseline alone is not claimed to contain the repair.

API: health 200, release/app/manifest identity VERIFIED; frontend identity VERIFIED. Date-list 3762 bytes / 0.0165 s; stage batch 8 stages, 10454 bytes / 2.3634 s in this observation. No claim of repeatable latency improvement for batch.

Codex built-in browser: both header identities matched; eight timeline stages rendered; exactly one detail and one batch request; no console errors/warnings; SOP and manager saved plan loaded. Manager remains PARTIAL and the last timeline stage retains CANNOT_CONFIRM. Screenshot is local outside Git: output/playwright/v4-fixed-built-in-home.jpg in this chat visualization root. Audit tab was closed and absence verified.

Detailed runtime identity aggregate remains CANNOT_CONFIRM due to pre-existing missing receipt/runtime inventory/dependency evidence; relevant identity fields have no DRIFT. Natural-session, PIT/model/trading validity: NOT_RUN/CANNOT_CONFIRM, outside this software repair. RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false.

Rollback: use the task-specific `release_repair.py rollback` command in README; it checks ownership, waits job and listener unload, restores the exact backup plist, validates health and known identity. Original pre-repair frontend defect is retained in that rollback target. The external original report rollback instructions were also corrected.
