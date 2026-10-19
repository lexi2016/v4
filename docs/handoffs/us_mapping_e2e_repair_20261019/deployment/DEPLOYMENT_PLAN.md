# Frozen bounded deployment plan

GOAL: Preserve the active announcement-fixed-membership release and overlay only the accepted US_MAPPING repair on API 8873, then generate exactly one authorized MANUAL US_MAPPING run for independent API/UI review.

WRITER: /root/mapping_deployer via supported default entry, requested GPT-6.1 Sol High; named sol_high registration not claimed verified.

REVIEWER: Controller-assigned independent read-only API/UI reviewer. Prior source review remains effective.

ALLOWED_PATHS:
- This deployment directory: plan, bounded scripts, compact receipts; raw responses, build and plist backup only in local_only/.
- New release /Users/lexi/Library/Application Support/com.lexi.v4.local/releases/us-mapping-e2e-repair-20261019-r1: clone active app, replace exactly SCOPE.json source_delta paths; replace apps/web/dist/manager-selection/index.html; add only recursively referenced new /assets/ files. Preserve existing asset bytes.
- /Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist: change active release root/id/manifest hash bindings only; preserve all unrelated values. Original raw bytes retained.
- Reload only gui/<uid>/com.lexi.v35.api-only with launchctl bootout/bootstrap; no other service action.
- Exactly one POST /api/v4/manager-workbench/runs with {"target_date":"20261020","phase":"MANUAL","lanes":["US_MAPPING"]}, after source date/cutoff and saved owner input verification.

FORBIDDEN_PATHS: old releases, business source outside six frozen paths, scheduler/stage-center/Vibe 8910, shared producers, business data overwrite, permissions/global config/BUY, commits/pushes. Candidate metadata records overlay lineage; it does not claim complete worktree Git equivalence.

Preparation: python3 docs/handoffs/us_mapping_e2e_repair_20261019/deployment/bounded_release.py prepare

Activation (controller integration gate required first): python3 docs/handoffs/us_mapping_e2e_repair_20261019/deployment/bounded_release.py activate

Rollback: python3 docs/handoffs/us_mapping_e2e_repair_20261019/deployment/bounded_release.py rollback

Activation and rollback restore/replace the same plist, inspect /bin/launchctl print gui/<uid>/com.lexi.v35.api-only, and run /bin/launchctl bootout on that exact loaded API job. They wait at most 16 seconds for the SIGTERMed job to disappear, then run /bin/launchctl bootstrap gui/<uid> <exact plist path> and /bin/launchctl kickstart gui/<uid>/com.lexi.v35.api-only. An already missing job skips bootout. Original release is retained unchanged. Activation rechecks original manifest/plist/config and six preimages against SCOPE, and the complete app inventory against preparation. Rollback accepts only the exact prepared candidate plist and restores original bytes before reloading only API.

PASS_SIGNAL: Candidate complete diff constrained to six source paths, manager HTML and required new assets; all other bytes preserved; rollback artifacts executable; after controller continuation, runtime identity/safety health and single dated run handed to independent API/UI review. Writer preparation is not acceptance.

STOP_RULE: Drift, unexpected existing candidate, changed source date/input, out-of-scope file need, unknown POST outcome, permission/ownership ambiguity. Unknown POST is checked through GET history without another POST. No repeated source acceptance tests.
