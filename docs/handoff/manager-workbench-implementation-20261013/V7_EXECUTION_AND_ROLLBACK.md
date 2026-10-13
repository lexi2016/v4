V7 is prepared from the active R10 gateway and R8 scheduler. It is not deployed. V5/V6 remain unchanged. The manager frontend's four already accepted assets are reused. API non-manager files (1072) and scheduler non-manager files must pass `verify_v7_candidate.py` immediately before any cutover; drift requires manager-only delta replay on the new active base.

Use the existing runtime Python and the helpers in this directory. The parent operator performs the following stages; the Writer does not start a service, call a model, or change a formal pointer.

1. `verify_v7_candidate.py` validates the candidate manifests, active base, manager/source closure, retained module bytes and API/scheduler imports. It holds the existing shared API release kernel lock. The installed generic lock yields no lease object; the receipt explicitly distinguishes this from lease-object attestation. Generic publication logic is unchanged.
2. `prepare_v7_canary.py --capture-receipt <accepted R5 receipt>` prepares isolated material/config. Reuse the existing complete capture cache; do not recapture R4. R4's different calendar identity remains a preserved failed reference. The R5 receipt must use the actual candidate calendar. Completion cutoff must follow capture completion. Inspect `v7-material-preparation.json`, then call the same helper with `--execute-model --article-id <one eligible article>` for exactly one new Reader and independent Reviewer. Full-day counts and single-article research scope remain separate. Capture is disabled and no lease is granted. Subsequent calls reuse the exact prepared product pin.
3. `serve_isolated_candidate_v7.py --proof <isolated-root>/v7-single-canary.json --port 18873` opens temporary GET-only saved readback. The URL is `http://127.0.0.1:18873/manager-selection/?date=20261013&phase=RETROSPECTIVE&run_id=<actual run>`. Confirm actual API/body/source/execution identities and five page views. Stop only this temporary process after inspection. No model rerun on GET.
4. After real chain/API/UI acceptance and explicit activation, prepare the approved formal manager config with separate state/capture/shared-source lease roots and capture disabled/no token. Run `stage_v7_cutover.py --manager-config <approved config> --output <this handoff>/.tmp/v7-cutover`. This writes only staged plists and original byte-for-byte rollback copies; it does not install or activate. Config roots and saved date/input pin must be the reviewed formal choices, not the temporary canary identities.

For the same-window switch, the operator must use the existing shared release lock for the whole operation (including last active-base validation and pointer writes). Preserve both original plist SHA values and the original old manager binding/config bytes. Stop the two existing labels together, drain them, install the two staged plist bytes with exact preimage checks, bootstrap the same two labels, and verify 8873, new manager route, retained Stage route and the scheduler's WorkbenchHook. API old collector write routes are removed by the accepted manager-only patch; scheduler old AnnouncementCycleHook is excluded when the new config is present. Other producer environment variables remain the original values. Do not grant new capture ownership while either old writer may still be running.

The concrete same-window service commands (operator only, under the shared-lock orchestration) are:

```sh
launchctl bootout "gui/$(id -u)/com.lexi.v35.scheduler"
launchctl bootout "gui/$(id -u)/com.lexi.v35.api-only"
# Validate both formal plist bytes still equal the receipt's original SHA;
# replace only those two exact paths with their staged plist bytes.
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.lexi.v35.api-only.plist"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.lexi.v35.scheduler.plist"
```

Only after verifying the old API write routes and old scheduler owner are absent may the operator explicitly grant the existing source-wide new owner lease, inject its token into the approved config, enable capture and reload the same two services together. The lease/config activation remains an explicit operation, never an automatic startup or HTTP action. First observe a bounded capture/background-research cycle, verify actual saved input/date/SHA and 8873 readback, then verify the natural slot when it occurs. PREOPEN remains fixed at09:25 and does not await capture/model. Source gaps remain visible and do not erase valid partial materials.

Whole rollback: disable capture submission, stop/drain both new services, revoke the new source lease using the current token (no fallback grant), restore BOTH original plist bytes after checking the staged/current identity, restore the original config/binding bytes if the operator changed them, then bootstrap the same two original labels. Preserve new immutable products/checkpoints as evidence; never overwrite old success or history. Verify original API/Stage and scheduler identities before re-enabling any old collector. Canonical synchronization is separate and uses only `canonical_sync` exact paths/preimage SHA in the V7 build receipt; never replace an active app with the canonical whole file.

Writer status: PREPARED. Real network/model/API/browser/formal switch/natural slot are NOT_RUN by Writer; parent receipts establish those stages separately.

The operator-only exact-plan entries are now executable. `manager-workbench-v7-formal.prepared.json` uses the approved three distinct formal roots and keeps capture disabled/no token. After the single-article saved canary succeeds, run:

```text
<runtime-python> -B H/prepare_v7_operator.py --canary-proof <isolated-root>/v7-single-canary.json --output H/.tmp/v7-operator
<runtime-python> -B H/operate_v7_cutover.py --plan H/.tmp/v7-operator/operator-plan.json --plan-sha256 <printed exact SHA>
<runtime-python> -B H/operate_v7_cutover.py --plan H/.tmp/v7-operator/operator-plan.json --plan-sha256 <same SHA> --execute
```

Preparation writes only H and fails if any listed canonical preimage or immutable formal destination differs. Default operation is dry-run. Explicit execution holds the existing shared lock across last verification, both service stops, guarded exact-path writes and both starts. It copies saved capture and manager products/checkpoints as exact bytes with their existing relative refs; RETROSPECTIVE stays RETROSPECTIVE. It never writes or grants a lease, enables capture, modifies a shared producer, or labels a saved plan natural. It preserves unrelated launch environment variables and modules. The three approved roots are `state/manager_workbench`, `state/manager_workbench_capture`, `state/manager_workbench_source_leases` under the existing `com.lexi.v4.local` support root. The formal new config path is `config/manager-workbench-v7.json`.

Whole rollback entry:

```text
<runtime-python> -B H/operate_v7_cutover.py --plan H/.tmp/v7-operator/operator-plan.json --plan-sha256 <same SHA> --mode rollback
<runtime-python> -B H/operate_v7_cutover.py --plan H/.tmp/v7-operator/operator-plan.json --plan-sha256 <same SHA> --mode rollback --execute
```

Rollback checks postimage SHA before touching each source/config/plist, stops both new services, restores the exact prior source/config/plist bytes (removing only batch-added source/config files), then restarts both prior labels. Copied immutable material and research evidence remain in the new separate roots and do not affect old manager state. Any changed formal config or active lease requires resolving that specific state before rollback; the entry does not erase concurrent modifications. Apply startup failure invokes this batch's bounded source/plist/config restoration and preserves a journal. These entries were tested with temporary roots and fake service control only; real activation/readback remains the parent operator's next stage. The earlier manual commands explain the same sequence but this entry provides exact-path/preimage guards.
