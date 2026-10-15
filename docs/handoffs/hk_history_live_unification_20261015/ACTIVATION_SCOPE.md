# HK history API-only activation

```text
GOAL: Make the independently reviewed hk-history-unified-api-20261015-r1 release the live 8873 API, with unchanged manager roots, A control, scheduler, C panel/model and history identities.
WRITER: /root/hk_live_writer_61, gpt-6.1-sol / high, sole writer.
REVIEWER: /root/hk_live_review_61, gpt-6.1-sol / high, independent read-only reviewer.
ALLOWED_PATHS: Existing handoff scope plus this ACTIVATION_SCOPE.md, PREACTIVATION_REVIEW.json, ACTIVATION_RECEIPT.json, ONLINE_CANARY_RECEIPT.json, FINAL_RECEIPT.json, API_DELTA.patch, SYNC_SUMMARY.json, publishscript/activate_api.py; /Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist; /Users/lexi/Library/LaunchAgents/.com.lexi.v35.api-only.release.lock; graceful stop/start of com.lexi.v35.api-only only. No frozen candidate code, descriptor, app or source-data changes.
FORBIDDEN_PATHS: Scheduler and all other services/config; A state/data; panel/model/scorer/BUY/orders; old app; unrelated workspace changes. No data copy, manager migration, parallel producer or coordinator.
PASS_SIGNAL: Shared lock, old-plist CAS and base verification pass; actual healthy queues drain before graceful stop; candidate verification and new PID/cwd/manifest binding pass; online five fixed HK keys and invalid 422 pass; A compact hash/nested identities/status unchanged; scheduler PID/plist and protected source identities unchanged. Independent online review follows writer receipt.
STOP_RULE: Healthy pending jobs are awaited, never killed; changed CAS or review pins stop before service action. Activation/online failure restores only original API plist and old API release under the same lock, preserves failure evidence and leaves data/scheduler untouched.
```

The parent explicitly advanced this stage after independent candidate PASS with no P0/P1/P2 findings. Old manager RUNNING records require owner-PID evidence; stale records are not rewritten. Current manager jobs use lifecycle service.stop → JobCoordinator.stop → pool.shutdown(wait=True).
