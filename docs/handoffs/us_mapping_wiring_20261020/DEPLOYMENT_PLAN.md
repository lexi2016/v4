# API-only wiring and saved result: prepared, not activated or published

The source PASS and independent API candidate PASS are reused. API r1 is the complete frozen calendar candidate plus exactly the three approved backend source changes. Its manifest is `118d3d465007dd3d9fff05a462b17a4efb950e4cb891f345c59308eb0ea51e59`; proposed API plist is `9e6fa1a90073cbc32b76f86c157ba2c86145b28b08f0927986b5e13ecdbbca1e`. No candidate rebuild, frontend build or source test rerun is needed.

Scheduler preparation remains `PENDING_PARENT_DRIFT`: its existing parent contains an unaccepted change to `ops/macos_research_panel_daily_receipts.py`. The original STOP is retained. No scheduler candidate, pointer, slot or service was changed. Future automatic use of the repaired mapping/master binding is therefore **not deployed** in this stage. Resolving that parent belongs to the controller and its other owner.

## Calendar prerequisite and API lifecycle

The independent calendar executor owns the existing wait and its one permitted switch. Do not cancel or duplicate it. Wiring activation requires its successful completion and a fresh readback of the actual calendar PID, cwd, plist `5515167934594af314f2920e8b35a72d3330540f30129e7264b4e488c03a9ea8` and manifest `d4b39f80c0b34271373617ccbd402a5927193e94e140f20feee4a08511a8189d`. If any other release is active, stop for a new preserved baseline; never overwrite it with r6 or the old worktree.

Only after independent pipeline/publication-plan PASS and controller continuation: back up those exact live calendar plist bytes, recheck the candidate/proposal and all frozen receipts, then require the same current API PID, no direct child, no QUEUED/RUNNING Workbench attempts and no established TCP8873 connection owned by that PID. A healthy task keeps running. No safe gap means no switch. Write exact `local_only/api-candidate.plist`, run one `/bin/launchctl bootout gui/501/com.lexi.v35.api-only`, observe print RC113 absence within16 seconds, then one `/bin/launchctl bootstrap gui/501 /Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist`. Inspect actual lifecycle before any recovery; do not blindly repeat commands. Preserve KeepAlive and RunAtLoad.

Read back new PID/cwd, manifest, healthz/readyz and date-list runtime identity, plus unchanged calendar HTML/asset hashes. No producer/scheduler action or business POST is needed. API rollback restores the freshly backed-up calendar plist under an exact-current-candidate guard; bootout only if loaded, wait for absence, bootstrap that original. The historical r6 backup is evidence and must not erase the accepted calendar release.

## Full saved-result pipeline

`publish_wiring_result.py --prepare` has run the real `ManagerService._work`, actual `engines.run_lanes`, actual merge, `seal_snapshot`, selected-evidence validator and `WorkbenchStore.commit_plan` in `local_only/pipeline-store`. It did not instantiate a JobCoordinator against live state. A frozen-input injection exposes only US_MAPPING to that existing pipeline; every other lane, native input loader, model executor and network connection is blocked. The observed calls were load_inputs1/run_lanes1/merge1/semantic_executor0.

The prepared run is `05d40e7775c44304bbd98016194b0d0e`. It has a complete typed snapshot, terminal PARTIAL job, derivative input and original pipeline LOAD_INPUTS/PUBLISH checkpoints. The old run `52d6d87a1fe547a484b189448d0ddfb7`, its input `3f281b06...` and old checkpoints remain untouched. Only the already-reviewed HK16 master owner/identity/evidence was added to the original business input; quotes and every original owner pin remain frozen. The input records and evidence exactly equal the accepted master replay.

Identity layers are distinct:

- Lane InputBatch: `6b1f625cd98fa024c87a35aede2dbb6442659f3267c38078e6e5546a1bd55943`.
- Complete derivative input snapshot: `2d9ed180c2aad6f94e505dbbff0148244cecc529247d9bb1bfa9a2a2514164f8`.
- Aggregate plan input: `930f15974cf1c11335784dd535494fa98f5d1c31f58fb2ee20ae11b3de46f785`.
- Product digest: `62e4ea7dacd357a77c7d625a4cfdcb00a635cb3cd1797e9fc0c600700d5c2ba0`.
- Saved snapshot file SHA: `cc37d7899d973025cbb0549a731dc37fc41d46328268518a1de49b81c67348d8`.

The new trigger is MANUAL; phase remains NEXT_DAY. US20261019/HK price20261016/target20261020 and source cutoff `2026-10-20T05:44:00.587402+08:00` are retained. The original SCHEDULED trigger is historical source provenance, not a new natural run. Existing batch identity excludes trigger/cutoff/execution IDs; the prepare path explicitly resealed and verified the lane SHA rather than assuming it. Fresh IDs and processing context make the complete input snapshot SHA different. The existing pipeline advances the snapshot cutoff to actual merge time `10:24:44.342517+08:00`, and generated_at is `10:24:44.683578+08:00`; source_cutoff stays05:44. This is PROCESSING_RECOVERY, never natural success.

Daily research counts are BENEFIT5/OBSERVATION303/UNMAPPED379/UNASSESSED11 over698 unique monthly stocks and1003 catalog relations. They are not formal selections. The full merged snapshot contains701 distinct stocks, all701 UNASSESSED, selected0/watch0. Existing membership/paired-review and partial coverage gates remain. Strict V1 is PAUSED_NOT_EXECUTED; formal target eligibility remains CANNOT_CONFIRM. No financial thresholds or safety flags changed.

## Exact publication and idempotence

Publication is NOT_RUN. After approved API activation and controller continuation, use the existing runtime Python from this worktree:

```sh
'/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python' -B docs/handoffs/us_mapping_wiring_20261020/publish_wiring_result.py --check-only --prepared-sha256 8318f44531ed40fa3e1b73da617c7fd7ceee0274348f7546f98b590e3c600be7
'/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python' -B docs/handoffs/us_mapping_wiring_20261020/publish_wiring_result.py --publish --prepared-sha256 8318f44531ed40fa3e1b73da617c7fd7ceee0274348f7546f98b590e3c600be7
```

The helper first binds the raw prepared receipt hash, raw API candidate receipt, manifest, helper and every prepared file SHA. Publication also requires the exact live API proposal and running candidate cwd. It uses `WorkbenchStore.save_input/save_checkpoint/save_job/commit_plan` with no live JobCoordinator, no orphan recovery and no executor. The existing publication kernel lock contains an additional exact old-pointer check before its write. Expected old NEXT_DAY pointer SHA is `81ea8ec394f2e874b381a9a2dba9206e9cd3eb40c98bf2e65c2766c95fdd11e4`, pointing to52d6d87... . Any concurrent pointer drift stops publication. New job/checkpoint collisions also stop.

An exact already-published snapshot/product and pointer are read back without repeating writes. A snapshot without the exact expected pointer, or any partial/unknown result, stops for owner inspection; do not call publish repeatedly. Old snapshots, inputs, jobs, checkpoints, catalog and scheduler cursor are never rewritten. The new catalog entry and NEXT_DAY pointer use the original store contract. Raw files remain local_only.

If specifically authorized to roll back the new result, `--rollback --prepared-sha256 8318f44531ed40fa3e1b73da617c7fd7ceee0274348f7546f98b590e3c600be7` guards the exact recorded newly published pointer inside the same existing store publication lock, then commits the original saved plan. It restores the old pointer bytes while retaining the appended new run/history. It does not delete research or replay the old job. Rollback is prepared, NOT_RUN.

After publication, read-only API URLs are `/api/v4/manager-workbench/runs/05d40e7775c44304bbd98016194b0d0e`, `/api/v4/manager-workbench/days/20261020?run_id=05d40e7775c44304bbd98016194b0d0e`, `/api/v4/manager-workbench/days/20261020/recommendations/US_MAPPING?run_id=05d40e7775c44304bbd98016194b0d0e`, and dated history. Verify all pages/pagination use that same product/input identity and the complete daily/catalog counts. The existing API `_public` path redactor remains the only public projection. The controller owns actual browser reload/date/version/row evidence. No POST, collection, HK history, strict run, new producer, natural rerun or other lane is authorized by these GETs.

Only compact DEPLOYMENT documents/helpers are syncable. Exclude local_only, all raw inputs/snapshots/jobs/checkpoints, plists, logs, release trees, dist and backups. Source and candidate independent PASS are reused; only this new pipeline/helper/publication plan needs incremental review.

Incremental guard repair: expected new pointer is derived from the frozen snapshot run_id/product/generated_at through the existing canonical contract, SHA985b91b19eaaf878f87295f02d8f191d2aaf4bcc2150911522a5e2a68823a248. Exact idempotence checks the entire pointer SHA. Rollback requires both the future publication receipt product/pointer fields and the actual pointer to equal this frozen value; a mutable receipt cannot define its own preimage. Publication also requires launchd state=running, a positive PID, and lsof cwd from that same PID matching the candidate. Ten hermetic local-store guard cases passed; no real publisher, service or pipeline rerun occurred.
