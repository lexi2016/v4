# M18 Mac acceptance supplement — 2026-10-10 r1

This supplements, and does not replace, the previous local FINAL_REPORT.md / RESULT.json. No code/config changes, refresh, capture, repeated engineering tests, permission changes, Chrome, or native-app retry. Existing logs and failed directories remain local. Uploaded material contains identities, hashes, counts and request/status metadata only, not raw announcement text or full business products.

## Outcome to return to original Chat

Fixed code `6daed6271313b5ae5324c8948f163258ab8d1fa3`, delivery `19e37dcec266fd25c49e06e3bfad979e4fb55d55`. M18 workspace and announcement analysis read paths deployed and API-verified; **full manager-page business acceptance is NOT complete**. The static HTML HTTP200 is not used as page-business proof.

Live URL (user Mac only): http://127.0.0.1:61796/manager-selection/?date=20261009&plan_date=20261009&view=auto
Switch: 2026-10-10T15:04:47.543981Z; old gateway PID94191 → PID83255. Same61796 URL retained. Manager PID83037/60036, announcement PID83038/60037; all three process identities read successfully. Runtime source is isolated fixed Git-blob materialization `m18-6daed627-source/V5`, not a claimed Git checkout. Static source `m18-web-fixed/dist`; old static source `display-cleanup-e9c94a13/dist` preserved. Full args/config/manifest/resource SHA and CAS generation IDs are in RESULT.json. Old V4/8873 PID81797 and8910 PID1311 were unchanged in post-deployment receipt. Candidate gateway83039/60038 remains temporary.

## Actual product and classification

Run `5b4feaf7ef7d4d13bec639e90b6d3db0`; plan SHA `56556a67ddc1a562e82b38e750be92fcfda070945397cc4eacffd1c79f42bcf0`; consumed=true CURRENT_RECOVERY, historical_eligible=false. Same-run terminal PARTIAL, SHA `1fa22b5d8616edba05082191eb2a7c1dfce83a4d0d23b13c2d689a8ac4336e77`.
Announcement product SHA `56acef75f660cc76c6f0482b200dd604a282f95d4520de2f2d7eb56d6c47185a`. Actual readback392article decisions: event2 / earnings0 / watch26 / not-selected270 / unassessed94. Original91 insufficient-text gate count retained. Issuer projection is a different denominator:281 issuers, selected2/watch26/not-selected182/unassessed71; manager announcement channel28rows. No reimport or recapture.

## Requests: source-inferred initiation plus actual HTTP observations

`catalystObservationPanel.ts:821–823` initiates workspace auto, announcement list and analysis separately. `dailyChannels.ts:75` makes plan_date alone unbound; `catalystObservationPanel.ts:734–744` updates announcement date to server binding20261008 and rereads its list. The deployed source, not a browser network trace, establishes this request sequence.

- workspace date20261009&view=auto:200, full original frontend validator passed; expected run/product/terminal.
- analysis date20261009 (default previous session), and explicit publication_date20261008:200. Analysis embeds stock selection; it does not call independent /selection.
- independent announcement list date20261009:503; final server-bound date20261008:503 MODULE_RESULT_NOT_AVAILABLE. Source handles it separately as announcement read failure / unknown coverage.
- independent announcement /selection date20261009:503 MODULE_RESULT_NOT_AVAILABLE. This route is not called by the inspected M18 panel.
- ManagerSelectionView.vue loadDate:2648–2654 separately starts seven legacy host requests. All seven source-derived exact20261009 requests actually returned404 ROUTE_NOT_CONFIGURED: selection, preselection-pools, stage-selection, manager/research, research/lane, workbench-research, manager-decision. Exact URLs/status/body hashes are in RESULT.json. No new module implementations were added.
- Historical09 is HTTP200 with refusal/nonconsumption, not a qualifying historical PASS. 10/08 dynamic and10/12 US dynamic preserved byte-identically.

The original21post-switch checks (9API,11assets,1HTML) with exact paths/status/SHA are in RESULT.json. The new8request checks add the final08list plus7host paths; they are not silently added to the original21. GETs do not invoke business execution. No full DOM/page business claim.

## Engineering evidence, not rerun

135Python tests exit0 after using real-path TMPDIR; original84/126 not rerun. Four targeted frontend specs51tests exit0; real currentRecovery3tests exit0; typecheck/build exit0.119package file hashes and6reverse/forward/preimage commands exit0. Full actual HTTP frontend validator PASS for09auto/history,08dynamic,12US. All exact saved command argv/time/exitcodes included in RESULT.json. Initial failures preserved: private clone128; old overlay file mismatch1; Mac symlink TMPDIR run1; npm network lookup1. Source materialization checked771/772 V5 blobs, excluding only unrelated cloud preview.tar.gz. This is not full-suite or independent new-reviewer certification.

## Browser/tool and remaining issues

Direct mcp__cua_repl.js tool is present this turn, correcting the earlier overly broad phrase “no CUA tool.” Read-only `await cua.getState();` timed out after31.6448s and reset kernel. No usable Mac IAB session confirmed. Earlier IAB explicitly unavailable and native app denied; no native retry, noChrome, no cloud localhost substitute. UI visual NOT_VERIFIED; natural daily execution NOT_VERIFIED.

Return issues to original Chat: (1) list08/09 and independent selection09 published result missing503; (2) seven host routes absent404; (3) IAB usable-session gap; (4) delivery documentation conflates timestamps: actual manager generated_at02:24:48.215061Z, announcement available_at02:23:24.502381Z. Correct documentation, never rewrite product timestamps. Business remains PARTIAL with original gaps/PIT restrictions.

## Rollback entry

Local `m18-evidence/rollback-record.json` contains exact old_args and old_cwd, also embedded in RESULT.json. Restore only gateway61796 using that old command/cwd after verifying live ownership; old frontend/config/active hashes are recorded and unchanged. Rollback was not executed by this supplement. Upstream services needed by live gateway were left running. No automatic natural-schedule claim.
