# Runtime precheck and proposed integration boundary

This is a read-only PRECHECK handoff. No candidate, service, plist, scheduler, business state, source or old failure was modified or retried. Candidate preparation and activation require a later controller continuation.

The actual API parent is `announcement-daily-workflow-20261020-r8`, app root `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/announcement-daily-workflow-20261020-r8/app`. PID16695 is running and its lsof cwd matches this root. Actual plist SHA is `5d5c01d354c10787b70fb56919fa0652592a49dc9ca003c6ef4e8c1b2ba7b41b`; manifest SHA is `0de62ef4d96018f56cfa2ebbf91470d64b292728c8623cd0a60dd5d9ac11332a`. Full application inventory1274 matches every manifest entry, with aggregate `97b803c3e009e533e77089533171aec693e5f2f8a60a7317262cbdf093623595` and no delta. HTTP health is ok; readyz retains all three safety flags false. Date-list returns the same r8 release/manifest and MANIFEST_EXECUTION_FILES_VERIFIED. Its existing process_status remains CANNOT_CONFIRM; the separate PID/cwd readback is recorded without changing that API field.

At the precheck snapshot there were no QUEUED/RUNNING Workbench attempts, no direct API children and no established TCP8873 connection owned by the API PID. This is not permission to switch and is not a future idle guarantee. Before any actual switch, recheck the then-current loaded identity, full release baseline and live guard.

## Frontend baseline for the sole source Writer

Use the complete actual r8 `apps/web/src`, package/lock and Vite/TypeScript/HTML inputs as the build parent. `RUNTIME_FRONTEND_BASELINE.json` freezes120 source entries,33 dist entries and relevant package/config/HTML hashes. The complete1274-entry inventory is local_only/runtime and is not a syncable runtime tree.

The current `AnnouncementCandidates.vue` is SHA `a6dcf2ea2f543a179743d9ecfdef9b2add6475aaaa02a64038bc4bd641461d20`, newer than the old r6/candidate version. Package SHA is `c19353356c407e397c4eeda0bf052c0229e6fb814c55de43eb60a43263306d2b`; lockfile SHA is `3f0b8425f35a7fdeb13cc0e5422b7814b386a6c7559d0e5c6b2f8340bc01be47`. Current Workbench/useWorkbench/CSS still have the original pre-calendar bytes; previous reviewed calendar candidates were not deployed. Apply only this round's approved frontend patch to r8. Do not copy the whole task worktree or any old release over r8.

The later immutable API candidate should clone this actual complete parent and preserve every non-delta entry. Its frontend static delta should be only manager-selection HTML and the new hashed dependency closure actually needed by that page. Preserve root/daily HTML, all their referenced assets, all old manager assets and all unrelated source/package bytes. The source Writer's final PREPARED/build determines the exact file list; no asset count is assumed before that evidence exists.

## Backend and saved-result reuse require new runtime bindings

All three scoped backend files are still exact accepted r6 preimages:

| File | Current | Accepted repair |
| --- | --- | --- |
| engines/us_mapping.py | 6d98c575e9c03ca58eace87331bb08ec17243738923af9160a8e1eee5eac6ec1 | 32a8e08aa1ab369a95ce36b625fcf9fd843aa4d3d732caa355d5dc78a666bc8a |
| engines/strict_us_selection.py | 7178bb4f0b19ee2c09c1f1a6d32ac1b7e0f1d7afd980512f44afc238d1615c48 | c0051752f3951c956495c18a46981105614cd6caf8cdb254ed54e4fa8e1cd367 |
| inputs/native.py | dd8ab5c5e1c576275075c2eae208039e47effb76e0cf1d38aeab213062e63cc2 | a0735e72297f11a4878520c9e0273f5f7679dda81e9947cc3505dd5ae2f2629b |

Paths are under `v4/manager_workbench/`. The proposed integration is r8 plus exactly these already-reviewed three files and this round's necessary frontend/static delta. Their source PASS can be reused while new candidate preservation and runtime/publisher bindings receive incremental acceptance. Do not enable strict selection or touch the scheduler. Scheduler's earlier parent drift remains outside this task.

The isolated full-pipeline prepared run `05d40e7775c44304bbd98016194b0d0e` is still not published. Its accepted lane batch6b1f625..., full derivative input2d9ed180..., product62e4ea7d... and frozen input/source context can remain unchanged. It is MANUAL processing recovery over US20261019/HK price20261016/target20261020, with source cutoff05:44 and actual earlier processing/generated time10:24. It is not a natural run or a new quote capture.

The old publication helper is bound to the old r6/calendar-derived candidate/manifest/proposal, so it must not be run unchanged against r8. A later explicitly scoped publisher adaptation must rebind only the new reviewed candidate/manifest/proposal and receipt hashes, retain R2's immutable expected-new-pointer and running-PID/cwd guards, and keep every business input/pipeline artifact untouched. No new pipeline run or source test repetition is required solely by a runtime pointer rebind.

The target20 NEXT_DAY pointer remains SHA `81ea8ec394f2e874b381a9a2dba9206e9cd3eb40c98bf2e65c2766c95fdd11e4` and still names52d6d87.... Publication would require this exact expected preimage again, or a new controller adjudication if it changes. The accepted new pointer identity remains985b91b1... derived from the frozen snapshot, not from mutable future receipt fields. Old runs, inputs, checkpoints, catalogs and all other phase pointers must remain intact. Rollback restores only an exact guarded prior pointer and retains appended history.

## Today's newer saved results must remain intact

There are22 target20 catalog entries. The latest is INTRADAY run `e96a793fe0f0464ca354927d301e13d3`, generated15:03:53, product `9969dec205e67169c3d7e7168497f5f40c71839caf68358e6f42a9e78a6811d9`; its pointer SHA is `264aa5930bff737bc8ef23247c03b20df4d651518f1ff60f734caf1b43ccc575`. PREOPEN and MANUAL pointers also remain separately recorded in RUNTIME_PRECHECK.

Do not overwrite these newer results or alter the prepared run's generated time to force default ordering. Any eventual saved-result API/UI acceptance must select the exact new run_id explicitly and separately report current-date default/version behavior. The Top20 research owner determines which actual saved pre-close selection and retrospective derived result are valid comparison objects; this runtime precheck does not relabel either as strict selection, formal eligibility or validated trading effectiveness.

No build, business run, POST, provider fetch, history repair, BUY action, scheduler action or runtime activation was performed during this precheck.
