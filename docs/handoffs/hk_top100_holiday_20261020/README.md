# HK Top100 holiday runtime repair · 20261020

State: IMPLEMENTED_SECOND_INCREMENTAL_REPAIR / READY_FOR_THIRD_REVIEW. Review 2 confirmed P1 resolved, but found P2: unused HK file checks could block A on an unsupported split-date branch. See both `review_round1_fail.json` and `review_round2_fail.json`. Current delta only guards those HK-specific checks on that branch; A checks and normal HK checks remain strict. Third independent review, integration, sync, deployment and natural-slot acceptance remain pending.

GOAL: target HK 20261020 uses prior HK securities/Connect date 20261016 across normal production, HK-only retry, consumer reader and preparation gates. Preserve A dates/model/safety and today's recovered pools.
WRITER: hk_top100_runtime_writer; generic Sol High task entry, no specialist-role load claimed.
REVIEWER: parent to assign independently, read-only.
ALLOWED_PATHS: task worktree's runtime single-file handler, candidate split preselection file, targeted test file and this handoff directory. Parent approved the extra runtime ops consumer overlay.
FORBIDDEN_PATHS: canonical dirty checkout, retained release/plist, business state, providers, commit/push/restart.
PASS_SIGNAL: independent targeted regression on actual retained importer, normal/retry/consumer/gates; independent HK sessions, unknown calendar closed, A dates unchanged.
STOP_RULE: new dependencies/paths, unsafe flags, provider/business mutation or unrelated behavior require parent decision.

## Actual runtime and delta

Retained app: `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/us-mapping-close-scheduler-20261020-r1/app`.

Its facade imports `executor_registry_preselection.py` and rebinds handlers with `FunctionType`; it has no candidate split dependency. The copied single file is a precise backport; `runtime.patch` is its minimal diff plus the consumer diff. Do not deploy the split architecture or the whole cd27 candidate.

- Runtime handler derives HK target, price close and last Connect eligibility date from its existing frozen calendar. The retained calendar lacks candidate `next_session`, so a bounded local adapter reuses `resolve_market_states`; calendar/model files are unchanged.
- Update, security master, scorer, normal consumer and HK-only retry receive those dates. Preparation failures still prohibit scoring and remain retryable.
- Local helper imports survive facade globals rebinding. The retained HK-only retry otherwise raises `NameError: _retry_missing_hk_only` before work; baseline harness reproduces this.
- Runtime scheduled consumer accepts separate HK target/signal/eligibility args and verifies them against the same calendar helper. The actual retained shared CLI/reader supports a single source date. Equal price/eligibility dates use only its real CLI flags and reader keywords. Split dates produce explicit HK `CANNOT_CONFIRM / HK_SPLIT_DATE_CONTRACT_UNSUPPORTED` before HK preparation/production/reader, while A continues. No eligibility date is substituted and no shared-library/root upgrade is included.
- Candidate split changes only three lines: target HK session state controls preparation on an A-open HK holiday. Existing correct date helper/arguments are reused.

The real `PRODUCER_RECEIPT_MISSING:HK:20261019` failure is preserved. It belongs to independent `research_panel_runtime_evidence`; dispatcher loops after exceptions (291-350), while 1730/1800 do not take stage-input preflight (`run_v35_macos_scheduler.py` 463-580). A regression injects the evidence failure and verifies preselection is still called; overall dispatch remains FAILED for the publisher. Publisher and receipt data were not modified.

## Verification

`writer_receipt.json` records baseline/after SHA, source root/branch, Python, test command and scope. Tests run from `/tmp` against retained runtime imports with only two in-memory source overlays, no provider or business-state writes.

Baseline: 2 passed, reproducing holiday 19 sent to HK and missing retry facade helper. First Writer run was 15 passed but did not cover the actual shared contract; independent Reviewer correctly rejected it. Incremental repair: 17 passed, 2 baseline cases skipped. Scope includes holiday19→target20/source16, ordinary day, A/HK target divergence, actual facade imports, real retry through all preparation steps to scorer argv, real retained CLI parser accepting that argv, actual imported reader signature compatibility, real domain mapper/formal gate on synthetic READY100, unknown calendar, prerequisite failure, independent publisher failure, candidate split holiday preparation and early fail-closed split-date paths preserving A.

Second incremental reproduction: 2 failed and 2 passed before the fix; the four branch checks pass after the fix. They prove missing unused HK scorer/security entries permit A on split dates, while normal HK scorer and A selector remain mandatory. Prior 17-case evidence and Reviewer P1 resolution are reused; date helpers, consumer ops, shared library and candidate split are unchanged. Third review is limited to `review_round2_delta.patch` and these direct effects.

Earlier overlays are superseded and must not be integrated. Current overlay is `/private/tmp/hk-top100-reviewed-overlay-20261020-contract-r2`; the receipt records build result and updated after SHAs. See receipt for exact incremental regression command. Parser verification executes only retained argparse declarations; scorer/read/materialization bodies never execute.

## Integration and rollback

Run `build_runtime_overlay.py --base-app <retained-app> --output <new-dir-outside-release-tree>`. It verifies both retained baseline SHAs and reviewed source SHAs, compiles and emits only the two source files. It refuses an existing output or one inside the retained release tree. This is an overlay builder; full release/inventory binding remains the integrator's responsibility.

After independent Reviewer PASS, parent may integrate these two files into a new release based on the actual retained scheduler app, using its existing release/inventory mechanism. Preserve all other bytes/dependencies, including the dedicated HK interpreter and shared package/date-aware reader. Rebind/restart only within separately authorized deployment scope. Do not substitute cd27's whole tree.

Rollback restores previous scheduler release/binding and matching inventory, without business-data rollback. No provider requests, pool regeneration, Stage run, release/plist mutation or restart were performed. Today's recovered HK100 and A298 receipts are separate; this offline result does not establish natural-slot acceptance.
