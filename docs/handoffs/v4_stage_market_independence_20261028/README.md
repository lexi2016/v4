# V4 A/HK stage recovery — 2026-10-28

Main R7 activated at19:21:01 and Stage R7 at19:27:14 Shanghai time. The20:00 original hourly scheduler completed with `SUCCEEDED` and business state `PARTIAL_WITH_ROWS`. The installed Stage reader independently consumed that publication and returned420 A-share research contexts. These are research contexts, not newly selected stocks. Today's historical A-share stages remain0/`CANNOT_CONFIRM`.

The API business name correction is active, but its effective release identity is still `CANNOT_CONFIRM`. A metadata-only successor passed independent review but was not activated: its fresh authentication request expired before any service action. That correction is handed to the human-authorized V4 naming task for one coordinated API cutover. This task has released API lifecycle ownership. See `API_OWNER_HANDOFF_R7.json`; never execute an old helper or replay a completed control plan.

## Why yesterday differed

- On2026-10-28 the morning source was genuinely PARTIAL after bounded pagination. The old research reader rejected it, and shared Stage exception handling blocked the independent HK market as well.
- On2026-10-27 the unfinished morning fetch had instead been marked READY, and its early timestamp became the next window start. That day's09:35 stage produced10 A and10 HK rows, both PARTIAL. This is not proof of complete source coverage or historical PIT validity.
- The original2026-10-28 morning tasks failed before publishing input/archive/completion evidence. A later release cannot create evidence that those inputs were available at the old market cutoffs. Native09:25 A capture separately rejected future-dated quotes; the older09:26:37 transaction recovery is not a native09:25 baseline.

## Implemented and actually observed

The Stage market isolation is the reviewed two-file overlay in `stage_source/`. Six previously failed HK slots were manually replayed from preserved raw inputs; API readback showed10 HK rows in each of8 slots. These are late recoveries, not natural-session/PIT certification. A remained unconfirmed. The original receipts and raw inputs were retained.

`hourly_candidate/` contains the reviewed existing-producer changes for actual source completion, byte binding, publication and the installed Stage consumer. Main884/API1329/Stage983 source files were installed using scoped immutable releases. Main and Stage now use the R7 hourly fixes. The name fix is present in Main/API; a live600048 sample displayed保利发展. Full name/BJ coverage is not certified.

At20:00 the original Main owner fetched a PARTIAL source, published input and hourly archive, then finished at20:00:11.627230. Source completion, both publication records and the original dispatcher receipt bind the same bytes. The installed Stage reader selected slot2000 and retained `ZSXQ_SOURCE_PARTIAL_INCOMPLETE`. See `NATURAL_2000_ACCEPTANCE_R7.json` and its once-only independent runtime review. Actual local execution is observed; the original `natural_execution_verified=false` and `UNVERIFIED_LOCAL_CLOCK` fields were not rewritten. The completion chain is local consistency evidence, not an external timestamp signature or independent historical PIT certification. The supplemental PDF continuation still reports `PDF_POST_SUCCESS_FAILED:ValueError` separately.

## API identity correction and ownership

The active API inherited an old inline `V35_RELEASE_ID` that overrides the plist environment. Its adjacent manifest also uses a schema incompatible with the installed frontend verifier. Health200 did not establish release identity.

`control/api_identity_r3/` preserves the exact independently reviewed metadata/control source and focused checks. An immutable successor keeps all1329 application files unchanged, corrects canonical identity metadata, and produces `VERIFIED` through the actual installed frontend function under its final environment. It remains unactivated. The20:01:54 authentication expiry left originalAPI67002 running, with no root acknowledgement, TERM or active coordinator. The user later observed `EXPIRED` in Terminal. The approved V4 naming task owns the next coordinated API switch and must verify the actual effective PID/cwd/ID plus frontend-build after activation.

Host-bound plists, raw input, runtime directories and executable authentication helpers are intentionally excluded from this export. The frozen control tests were executed in the original scoped CASE; this is audit source, not portable CI or a reusable live plan. Earlier failed reviews and diagnostics remain retained.

## Data protection and remaining boundary

The pre-existing daily data task and its scheduler retry finished naturally before Main cutover. The original owner published generation31d40c5900ced1b2 with a PARTIAL daily receipt; this task did not publish or roll back market data. Five small-file pins and two current Parquet stat identities remained unchanged across cutover/runtime review; the two previous-generation Parquet stat identities also match. Large payloads were not rehashed. This task made no raw5073-stock or frozen-backup rewrite, and did not signal the other data job.

Tomorrow's actual intraday Stage and native09:25 execution are still unobserved. Today's missing A outputs cannot be replaced with the20:00 archive or existing preselection candidates. `RESEARCH_ONLY=true`, `production_allowed=false`, `buy_gate_updated=false`, and `orders_sent=false` remain the boundary throughout.
