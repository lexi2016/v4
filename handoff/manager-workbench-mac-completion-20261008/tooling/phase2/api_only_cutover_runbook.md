# Manager Workbench R1 API-only cutover runbook

This phase stages the independently accepted API candidate and prepares a guarded API-only LaunchAgent switch. The switch is **not deployed**. No live plist, LaunchAgent, scheduler, binding, automation, or formal manager state was changed.

## Frozen staged release

The accepted API candidate was copied into the previously absent release root using exclusive creation:

```text
release root: /Users/lexi/Library/Application Support/com.lexi.v4.local/releases/manager-workbench-r1-mac-20261008-api
app root: /Users/lexi/Library/Application Support/com.lexi.v4.local/releases/manager-workbench-r1-mac-20261008-api/app
release ID: manager-workbench-r1-mac-20261008-api
application inventory: 1,016 entries; SHA-256 0f2e6752b55430dd556d212739a9de4b2176acc92f95fc15b45ec342cb2b3771
release manifest: /Users/lexi/Library/Application Support/com.lexi.v4.local/releases/manager-workbench-r1-mac-20261008-api/release-manifest.json
release manifest SHA-256: d125d33b8c8a5cae6edead79cb756b671baf07a79ddc0653c2884800a7eafb49
stage receipt: phase2/receipts/api_release_stage_receipt.json
stage receipt file SHA-256: 7744cded27787e630e1d486f9b5dd55cb0a5fce8fca7f4ceb4a9f51c060b1ba2
frontend dist: 11 files; frozen tree SHA-256 38f0d0195385ed9cf5ce8943e15a81a9b1ef4813c7a1cd5e4359386e76917234
```

The release inventory was checked against the accepted candidate and the package manifest. The staged API plist and reviewable diff are under `phase2/drafts/`:

```text
plist: phase2/drafts/com.lexi.v35.api-only.plist
plist SHA-256: d3552150122b8f9c89d538e5ce4553ac49a73dd4a4342e2d4786d88ee373a357
diff: phase2/drafts/staged_api_plist_diff.json
diff SHA-256: ea7abba2c33cac0b7914a7f4dc5dff3df401908c4d6cf60bace06de4bb1374cc
```

The diff changes exactly five release identity environment keys (`PYTHONPATH`, `V35_APP_ROOT`, `V35_RELEASE_ID`, `V35_RELEASE_MANIFEST_PATH`, and `V35_RELEASE_MANIFEST_SHA256`) plus `WorkingDirectory`. It preserves the original disabled plan binding path and SHA `f3b7cbfa1709b2b27816d294e599cb1ae82ff918ba41ec148644f1a1751f5fd6`, the `V4_MANAGER_SCREEN_AUTHORITY_ROOT` at `/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data`, the manager research-state root, command shape, and safety values. `RESEARCH_ONLY=true`; `production_allowed=false`, `buy_gate_updated=false`, and `orders_sent=false`.

## Read-only preflight

The last read-only preflight was observed at `2026-10-08T09:29:43Z` and returned `READY_API_ONLY_R1_CUTOVER`. It saw the existing R3 API loaded at PID `1297`, active API plist SHA `72050bf4c7f00c8271cf9226ea866683a8e9e459d2875547b08f69fad30bfdf5`, scheduler plist SHA `c478c87e7866fa50154df674ea7cb570197251aaa5da3014b3666e7f22914da2`, and Stage Center plist SHA `9c7199ca1fcfedc09397255c932d25c6edc15779952bbd5b5bec2671e883d3f5`. These are observations; rerun preflight immediately before any separately authorized switch and use the fresh output values.

Run the read-only plan and preflight with the pinned interpreter:

```sh
"/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python" \
  "/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_R1_MAC_20261008/phase2/tools/api_only_cutover.py" plan

"/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python" \
  "/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_R1_MAC_20261008/phase2/tools/api_only_cutover.py" preflight
```

The preflight verifies the current API process and plist identity, immutable release inventory and manifest, exact staged plist and diff, disabled binding, both read-only scheduler guards, and the two dated analysis responses. It writes no live file and calls no LaunchAgent action. The OpenAPI route, manager-selection index, and referenced asset bytes are checked only by the post-bootstrap runtime readback. If an identity or pinned SHA differs, stop and prepare a fresh reviewed plan.

The historical product baseline is `control/pre_switch_product_baseline.json`, SHA `c511e4c0241e7f98820aeba0e763a967223da1af454d14c6bac89c6fe8d49c31`. At the last preflight, the 2026-10-08 analysis for publication date 2026-10-07 matched product SHA `8b1e906db2cdcb8784d9658085aa4f1aa0711a8711b83a38c9ee8d7567151157`, with 529 stocks and 613 article decisions; its owner import receipt matched the pinned response and was `VERIFIED`. The 2026-10-07 analysis for publication date 2026-10-06 matched product SHA `7b27fe7d40e9c12db3d56751cc789c6eb84515bb2392fc1b00a3bc4a5fd38278`, with 524 stocks and 580 article decisions; its absent receipt remains compatible with the prior R3 response. Both analysis response hashes matched the pinned baseline.

The additive consumption_validation projection uses the original readback probe's compact JSON serializer, preserving the API response object's key order (ensure_ascii=False, separators=(",", ":")). Its frozen current/legacy SHA pins are 796e437a76c1a40acf7ade7c1bac64be53c7aaa4cd21e387d3ca7e3e2c72aee9 and 25ed3622660ce7602bb782257cf3b85d7346c1c7838e8fc1488b9dbf245ab726. The generic _canonical_sha remains sorted for plans and operation receipts. The two failed switch attempts used that sorted serializer on these response projections: the same staged responses produce f5c96caab104572949931351501fcb103743df16e1a97ed6650253905ac0f2a6 and be89ecb3f0029d3142ad8b70e24d30ec2e5ac71d7eb08183f0953d4b9d9525f3 when sorted. Both full responses still match their pinned R3 bytes after removing only the additive top-level projection. The staged TestClient probe and metadata-only fixture are recorded under completion_20261008/; this is a read-only helper verification and does not switch the service.

Workspace readback remains CANNOT_CONFIRM. The baseline workspace response SHA is `c7423ab38a87b3392652956fcb6fc408ef20d917257366d87a0fb80f56aadc9b`; the last sampled response SHA was `e400e9852a29c2261c74475cc90d0c4ef1f32aa9006aa3612d9d6196d8861dca`, and this endpoint's envelope hash varied across read-only samples. Its `announcement_reviewed_analysis` is `CANNOT_CONFIRM` with gap `ANNOUNCEMENT_ANALYSIS_NOT_CONSUMED:ANNOUNCEMENT_AGENT_JUDGMENT_RECEIPT_INVALID`; `announcement_review` is `NOT_RUN`, `plan_product` is `NOT_MATERIALIZED`, and `read_context` is `VERIFIED_WITH_GAPS`. The helper reports `data_loss_conclusion=CANNOT_CONFIRM`; it does not claim that workspace product is verified or infer data loss. Strict-oversold shared-panel evidence is also `CANNOT_CONFIRM`: the required 2026-10-07 and 2026-10-08 manifests/date pointers are absent and the 2026-10-05 through 2026-10-07 dates are outside that panel's scope. No re-import or second producer is part of this phase.

## Separately authorized API-only switch

Only a separate authorized operator may execute after an independent review of this final diff and a fresh `READY_API_ONLY_R1_CUTOVER` preflight. The currently staged plist SHA is `d3552150122b8f9c89d538e5ce4553ac49a73dd4a4342e2d4786d88ee373a357`; the observed current plist SHA is `72050bf4c7f00c8271cf9226ea866683a8e9e459d2875547b08f69fad30bfdf5`. Reuse those values only if the immediately preceding preflight returns the same values and identities.

```sh
"/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python" \
  "/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_R1_MAC_20261008/phase2/tools/api_only_cutover.py" \
  execute \
  --confirm SWITCH_API_ONLY_TO_MANAGER_WORKBENCH_R1_20261008 \
  --expected-current-plist-sha256 72050bf4c7f00c8271cf9226ea866683a8e9e459d2875547b08f69fad30bfdf5 \
  --expected-staged-plist-sha256 d3552150122b8f9c89d538e5ce4553ac49a73dd4a4342e2d4786d88ee373a357
```

The helper takes an exact preimage and writes its operation receipt under `phase2/receipts/api_only_switch_runs/` before it calls `bootout`. Its only live-file target is `/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist`; it calls `bootout` and `bootstrap` only for label `com.lexi.v35.api-only`. It rechecks the active plist SHA, loaded PID and release identity, candidate package, disabled binding, scheduler plist, and Stage Center plist immediately before the action. It restores the original API plist on post-bootout replacement/bootstrap/readback failure, preserving file metadata. Any unknown loaded identity or compare-and-swap mismatch fails closed.

After a successful switch, check the operation receipt, launchd identity and manifest, OpenAPI manager-workspace GET route, manager-selection index and referenced asset bytes, and the current/legacy analysis product hashes and counts. The workspace and strict-oversold evidence remain `CANNOT_CONFIRM` as described above. Browser reload and natural-slot behavior remain `CANNOT_CONFIRM` until directly checked. The process's in-memory Python source fingerprint is unavailable and remains `CANNOT_CONFIRM`; do not add tracing endpoints or inject into the process.

## Rollback

Rollback requires the successful operation receipt and the exact current API plist SHA recorded by that receipt. The expected current SHA will be the staged plist SHA below only if no later API-only file change occurred. Replace the receipt placeholder with the receipt path created by the successful switch:

```sh
"/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python" \
  "/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_R1_MAC_20261008/phase2/tools/api_only_cutover.py" \
  rollback \
  --receipt "/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_R1_MAC_20261008/phase2/receipts/api_only_switch_runs/<operation-id>/operation_receipt.json" \
  --confirm ROLLBACK_API_ONLY_TO_RECORDED_PREIMAGE \
  --expected-current-plist-sha256 d3552150122b8f9c89d538e5ce4553ac49a73dd4a4342e2d4786d88ee373a357
```

Rollback restores only the recorded API plist preimage and restarts only that API LaunchAgent. It must finish `ROLLED_BACK_TO_PREIMAGE` with the old runtime identity and HTTP readback, or `ROLLBACK_INCOMPLETE` with unresolved state and the backup path. Do not continue if state is unresolved. Scheduler and binding bytes are read-only guards throughout.

## Protected paths and later scheduler stage

This API-only scope does not change `/Users/lexi/Library/LaunchAgents/com.lexi.v35.scheduler.plist`, `/Users/lexi/Library/LaunchAgents/com.lexi.stage-center.scheduler.plist`, the disabled plan binding, `/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_auto_research`, the screen-authority root, or `/Users/lexi/.codex/automations/automation-3/automation.toml`. It does not refresh manager data, run an owner import, activate announcement collection, alter trading rules, change a BUY gate, or send orders.

Historical HK canary planning, exact-root scheduler adaptation, disabled binding preparation for the R1 root, and any future scheduler activation remain a later separately reviewed phase. No canary is rendered or executed here. `DEPLOYED`, `API_VERIFIED`, `UI_VERIFIED`, `BEHAVIOR_VERIFIED`, and `NATURAL_VERIFIED` are not claimed by this staging handoff.
