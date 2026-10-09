# Automatic post-owner assembly and fixed e06d execution candidate

Base 4dc2a816fa4ebde2ea85352b49b4d4e8ec9f1279: parent reports Mac35 unique PASS, no installation, business owners mocked. This candidate is NOT_RUN on Mac. It supersedes the manual post-owner request gap and missing e06d identity described in DAILY_OWNER_INSTALL_CONTRACT_20261009.md; it does not claim working source/model execution channels.

## Scheduling evidence and explicit new default

Pinned V4 workspace_plan_autorun DEFAULT_CONFIG is PROPOSAL_ONLY, lead_seconds=180 before the frozen 09:30 Stage boundary. It is an owner helper, not proof of a loaded Mac scheduler. No usable installed three-lane schedule was found in available source evidence. Adopt the authorized NEW V5 default: HK applicable trading days 08:00 start, 08:45 assemble/save research plan. Owner execution window ends08:45; plan grace ends09:00. Those two window deadlines are new candidate admission policy, not old V4 acceptance or user-specified minutes. The original HK full/half-day calendar is retained; default pre-open half-day slot is explicitly bound. Missing inputs produce BLOCKED; no prior-day fallback or late backfill. launchd remains disabled until existing Mac acceptance and V4 conflict checks.

## Actual pipeline now wired

One tick uses the same daily_dispatch and run_ledger. Jobs may omit slot fields and use the defaults above. Each still carries original exact source requests. Source request changes create a new computation identity; unchanged requests reuse the existing attempt. At08:45 the owner execution window is closed, so tick reads the exact existing ledger identity without claiming/executing it again. This retains valid readback references instead of losing them behind MISSED_WINDOW.

Supply `manager_template` in the exact-date bundle instead of a fully assembled manager_request. The template is an existing manager request with bound materials/US/archive/membership/source roots and separate marked output root. Its stale `now`, US mapping product references, rebound observation and announcement offline binding are not trusted as today's outputs. After the original owners return:

- US: read the exact run and current pointer from that owner output root, check run ID/logical artifact SHA, hash actual file bytes and copy only those verified files into immutable private manager input snapshots. A changed pointer rejects assembly rather than silently mixing versions.
- Rebound: bind the independently verified original observation root and four-part reference, even when business selection remains BLOCKED.
- Announcement: bind the actual returned immutable revision root, manager_binding file SHA and revision manifest SHA. Legacy consumed inputs remain explicitly blocked for missing decisions.
- Preserve other explicitly bound original manager files; never substitute US for HK Connect.

The template plus actual references/file bytes determines a durable sealed request. Its `now` is actual post-owner wall time on first assembly. Subsequent identical ticks reuse that sealed cutoff and request; changed inputs create a different immutable version. Original run_manager_plan refresh saves; independent original same-run/attempt/SHA readback verifies; a second ordinary `view=auto` workspace read must return the same plan. Its payload SHA is retained. This is the original ordinary workspace read path, not an HTTP/browser deployment claim. No module generation activation, gateway change or dabcfbee replacement occurs. Partial plans remain ledger BLOCKED with saved/readback evidence, and an uncertain save remains RUNNING.

## e06d pin and original decision execution

Source commit: e06d143e881c66c22053a5c594b9c0be21d5be34. Static-only assembly follows its original SOURCE_MANIFEST + OWNER_DEPENDENCIES + CANDIDATE_MANIFEST and assemble_owner_app namespace bytes. All29 app files match those manifests; app manifest SHA is da392a57bf93dd9a5b4355d934e267a7c5c4fe495e90779364627e8a8f118d8a. Stored separately at vendor/announcement_revision_baseline; legacy vendor unchanged. No announcement branch writes or unverified Library403 patch.

Announcement owner_request can now be:

- target_date: current HK date;
- revision_create: exact original create_revision keyword arguments (parent_root, recovery_sha256, revision_id, parent_product_sha256, parent_receipt_sha256, semantic_catalog, semantic_sha256, reviewer_output, reviewer_sha256, decisions, decisions_sha256);
- review_identities: parent_task_id, reader_identity, reviewer_identity (different actual reader/reviewer).

Absent real files/identities blocks before a ledger claim, so waiting does not exhaust attempts. When actual inputs arrive, the adapter invokes the pinned original CLI: create → prepare → register-handoff → verify → import → readback, then two independent manager consumer reads at an actual current cutoff. It never produces decisions/reviewer PASS. Existing body failures, 91 original NOT_ASSESSED gates, original decision digest and reviewer checks remain entirely in e06d. A crash leaves the common claim unknown; do not rerun create or reuse a failed revision ID blindly.

The read-only manager transport now admits an optional revision_manifest_sha256 binding. It selects the separately pinned revision capsule, validates parent/recovery/decision inputs, existing owner identity and registered handoff, and reads both the revision root and its exact parent. Original read-only audit denies writes/network/subprocess; constructor write-once is replaced only with equality validation of the already-existing identity. Legacy readers retain their original capsule/contract.

## Remaining execution dependencies: explicitly not automatic success

The readable V4/e06d interfaces supply capture/prepare/import/readback and consume externally supplied semantic_catalog, article_decisions and reviewer_output. They contain no authenticated model invocation or task-queue submission/return contract for an independent Reader/Reviewer. Current available channel is the existing external Mac research/independent-review workflow producing those files; a callable queue/worker entrypoint and receipt contract were requested from the coordinator. No credential/access change or new model service was introduced. The unverified Library403 content patch is excluded.

Likewise, daily bundle source requests require the existing source owners to resolve fresh exact-session payload/receipt and rebound panel evidence. No source-refresh scheduler binding was supplied in the readable inputs. Missing today's bundle reports BLOCKED_CURRENT_BUNDLE_MISSING; missing real announcement analysis/review reports BLOCKED_WAITING_REAL_ANALYSIS_REVIEW_DECISIONS. These are remaining front-half integration dependencies, not justification to run yesterday's products as automatic stock selection. This candidate closes reviewed-input → immutable revision → automatic post-owner plan assembly/save/readback, not fresh source/model acquisition end-to-end.

US actual five candidate archives have matching receipts but, per Mac report, still lack acquisition clocks, issuer identity and trusted proposition spans. Follow US_RELATION_LIMITED_RECOVERY_REQUEST_20261009.md. If historical acquisition evidence does not exist, only original-owner current-time acquisition can supply new evidence; never backfill10/9 history. natural_verified remains false throughout manual/candidate work.

## Existing Mac verification (cloud does not run it)

Synthetic unit candidates, one invocation, expected43 unique (previous35 + assembly8):

```bash
PYTHONPATH=V5/src:V5/tests python3 -B -m unittest test_us_mapping_scope test_run_ledger test_daily_dispatch test_daily_us_owner test_daily_owner_adapters test_daily_manager_assembly -v
```

Separate original-owner integration, TWO tests, using the existing complete fixed e06d fixture bundle already accepted by Mac (not just assembled app). This exercises actual original create/register/import, new read-only revision transport and original manager refresh/auto-read; no real capture/model. Missing bundle is ERROR, not SKIP:

```bash
V5_ANNOUNCEMENT_REVISION_TEST_BUNDLE=/ABS/E06D_BUNDLE PYTHONPATH=V5/src:V5/tests python3 -B -m unittest test_daily_revision_chain -v
```

Keep original failed and successful evidence separate. Before any enabling: verify private roots, fresh-source/analysis channels, approved default timing/calendar, no V4 label/process conflict, independent stop/rollback and original gates. The existing render/disable/bootout commands remain valid; no installation performed here.
