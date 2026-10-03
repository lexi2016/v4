# Issue23 R2 Stage B independent review

Verdict: REVIEWED=FAIL; BEHAVIOR_VERIFIED=FAIL for the complete candidate Stage runner path. The isolated HK prior-Connect binding behavior passes, but the single-runner-overlay candidate cannot enter its preserved R1 stage helper implementations.

## P1 — candidate runner and preserved helper signatures do not match

The candidate overlay app/stage_center/runner.py forwards historical_markets unconditionally from _run_one (line 964) and tick (line 979). The R1 files intentionally preserved in the candidate do not accept it: app/stage_center/_runner_parts/slot_execution.py:6 and app/stage_center/_runner_parts/tick_planning.py:20. The actual preserved dispatcher calls runner._run_one(decision) at app/ops/_run_stage_center_nodes_parts/stage_dispatch.py:367, which uses the wrapper's default None and still forwards the unsupported keyword. A candidate-only cold-process reproduction captured both exact errors:

1. _StageCenterRunner_tick_body() got an unexpected keyword argument 'historical_markets'. Did you mean 'historical_backfill'?
2. _StageCenterRunner__run_one_body() got an unexpected keyword argument 'historical_markets'. Did you mean 'historical_backfill'?

This stops regular Stage work before the old helper body runs; the dispatcher can only re-raise or record CANNOT_CONFIRM. Do not enable this candidate. The targeted Stage A tests cover builder CLI behavior against a synthetic active fixture (tests/test_stage_service_overlay_closure.py:803-845); they do not exercise the built candidate with its actual R1 helpers.

The full reproduction command was:

    cd /tmp
    env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH='/Users/lexi/Desktop/学习/agents调试/V4_HK_STAGE_RECOVERY_20261003/issue23_runner_only_r2/stage_r1_binding_candidate/app/upstreams:/Users/lexi/Desktop/学习/agents调试/V4_HK_STAGE_RECOVERY_20261003/issue23_runner_only_r2/stage_r1_binding_candidate/app' '/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python' -B /tmp/issue23_r2_stage_b_compat_repro.py

The script calls only the two candidate wrappers with object() as the receiver; it does not invoke the service, provider, collector, selection, or an external action. Full tracebacks and command output are in issue23_r2_stage_b_compat_repro.stdout.log; the exact script is /tmp/issue23_r2_stage_b_compat_repro.py.

## Verified acceptance evidence

- Active R1 remains release 20261002-hk-open-stage-r1, 914 files, inventory SHA dbe82acd4e3bbbee02d36a647d57ea19d54f557a3ac3c82d70b639aa8897e0a3. The active manifest and LaunchAgent plist hashes still match the Stage A readback.
- Independently recomputed candidate inventory is 914 files, SHA 6f18dda4f714ec85cfa8400162f29af2bd7bf427c8afcedb7491f5060555dbfc. Exactly stage_center/runner.py and the rebound stage_center_tick_config.json differ; all other 912 app paths match active R1. Overlay allowlist/entry is the single runner path.
- Config changes are exactly release_id and candidate-local shared_data_root; service python_path is unchanged. production_allowed, buy_gate_updated, and orders_sent remain false.
- Candidate cold import used the service Python from /tmp; reviewed modules resolve under the candidate root.
- Candidate _build_hk_stage_binding returned READY for target 20261002 with 100 unique HK_CONNECT members from source trade date 20260930, source signal date 20260929, and price signal date 20260930. Source artifact/manifest/receipt SHAs matched the existing dual-root input. The source date tree and shared read-lock file hashes/mtimes were unchanged; collection and selection were not called.
- Stage A's independent 5/5 focused CLI result is accepted from its receipt and was not rerun in Stage B, as frozen scope requires. The known full-closure failures were also not rerun.

The builder candidate remains offline and NOT_ACTIVATED; API/UI/deployment integration and natural scheduled behavior remain unverified. Under the frozen stop rule, stop here and keep the candidate unactivated. The owner/writer should resolve the interface mismatch within an explicitly refreshed scope, then repeat only the wrapper compatibility reproduction plus candidate import and binding checks; this review does not authorize extra overlays or another build.

Receipt: issue23_r2_stage_b_reviewer_receipt.json.
