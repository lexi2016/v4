# Independent review — V4 manager workbench repair

**Review date:** 2026-10-08  
**Reviewer:** independent read-only reviewer, separate from the implementers  
**Candidate:** `/workspace/scratch/a154a3323e32/candidate`  
**Comparison:** `/workspace/scratch/a154a3323e32/baseline` and local baseline `HEAD`  
**Frozen source provenance:** `0fd5eb374cb155232ed003d5fc4d0d3594252491`; this is not the local baseline commit.

## Verdict

**No consequential candidate-code finding remains open from this review.** Seven Important contract or integration problems were reproduced during review and corrected by the implementers. The final corrections were inspected and their affected regressions independently rerun. No Critical defect was identified within the reviewed scope.

This is **candidate-level review acceptance only**. The repair is **not merge-ready, deployment-verified, or natural-run-verified** on this evidence. Actual Mac process and source identity, loaded scheduler behavior, deployed API/UI readback, complete supplied dependency closure, and natural executions remain external acceptance gates. Tests built from synthetic owner inputs cannot establish those facts.

The reviewer did not edit candidate source, index, or HEAD, and did not synchronize or write to a remote. This report is a scratch review artifact. All source corrections described below were made by the implementation agents.

## Scope and basis

The review used the frozen `README.md`, `evidence.json`, and `source_map.json`, the repository `AGENTS.md`, and `docs/superpowers/plans/2026-10-08-manager-workbench-repair.md`. It considered the working-tree repair against the assembled baseline, including new untracked source and regression files. Source provenance and local Git identity were kept separate.

The principal source scope was the announcement API/shared consumer, manager workspace and history readers, plan owner and bound dispatch, scheduler entry points, target Connect scope, completed-session and volume evidence, daily channel projection, and the frontend API/panel/date-contract integration. The later history and focus-input corrections were also reviewed. Original BUY, Stage, Vibe and owner data/rule implementations were outside the change scope.

The review concentrated on consequential behavior: exact target/publication/source/handoff/owner lineage, source and availability cutoffs, stale source/version/date rejection, sealed same-run execution identity, manual versus scheduled classification, durable completion deadlines, retries and admission, independent US dependencies, target V2 versus D-1 membership, pending volume evidence, and truthful compact display states. It did not use missing dependencies as a reason to invent substitute modules or weaken validation.

## Findings and disposition

The locations below identify the final corrected code or the regression that demonstrates the issue. Each finding describes the failing behavior observed before its correction.

### R1 — Important — Unassessed announcement research became a successful empty selection

**Status: corrected and independently verified.**

The shared consumption result discarded `not_assessed_stock_count`. The daily projection then treated any consumed exact product with no selected or watch rows as `READY_EMPTY`, with `candidate_count=0`. This confused a reviewed product containing an explicit `NOT_ASSESSED` disposition with a completed negative selection.

The reproduction used the real fixture service, registered handoff, original import HTTP route, and original workspace reader. The imported analysis reported a verified selection with one unassessed stock. Its exact product was consumed, but the daily channel reported an empty successful result with no pending count or gap.

**Minimal correction applied:** propagate the original selection disposition counts; distinguish complete assessment from consumed provenance; retain a null candidate count when no positive count is known and assessment is incomplete. The channel now reports `PARTIAL`, the pending count, and `ANNOUNCEMENT_SELECTION_NOT_ASSESSED`. An explicit assessed `NOT_SELECTED` result still yields a legitimate successful empty result.

**Evidence:** `v4/manager_research/workspace_announcements.py:2362`; `v4/manager_research/workspace_daily_channels.py:110`; `tests/test_manager_announcement_parity_20261008.py:308`; the positive empty-control test at line 326.

### R2 — Important — Default evening reads omitted the exact target/publication product

**Status: corrected and independently verified.**

At the evening boundary, the workspace defaulted to the next HK plan session and previous HK publication session, but `_analysis_pairs` derived its search pairs from the older source-date window. The exact default pair could therefore be omitted. A valid current product appeared when the same publication was supplied explicitly and disappeared under the equivalent default request.

The reproduction used a registered and imported product for target `20261009`, publication `2026-10-08`, with the workspace clock at 18:10 HK on October 8. The default bindings displayed that pair, yet the channel was `CANNOT_CONFIRM`; explicitly supplying the same announcement date produced `CONSUMED` and a selected row. This also affected the default input path used by the evening owner.

**Minimal correction applied:** include the exact plan target plus `previous_hk_session(plan_target)` pair before scanning the historical source window, preserving the independently requested publication pair.

**Evidence:** `v4/manager_research/workspace_announcements.py:2223` and line 2238; `tests/test_manager_announcement_parity_20261008.py:337`.

### R3 — Important — Valid morning plans failed next-day historical readback and lost their run binding

**Status: corrected and independently verified.**

The historical reader accepted `MANUAL_REFRESH` and `SCHEDULED_PREOPEN` but rejected the newly activated `SCHEDULED_MORNING` product. A plan generated successfully through the real original owner at 07:00 HK consequently became `SOURCE_FAILED` on next-day/history reads. The historical result also omitted the exact attempt and execution kind needed to preserve the scheduled run identity in the daily projection.

**Minimal correction applied:** accept the original morning execution kind, validate the exact product's sealed same-run journal, and pass its execution kind and exact attempt through historical readback. A bad attempt must still invalidate saved scheduled consumption.

**Evidence:** `v4/manager_research/workspace_history.py:57`, line 258, and line 281; the shared validator in `v4/manager_research/workspace.py:770`; `tests/test_manager_workspace_owner_20261008.py:125`, covering both morning and preopen with real persisted products and journal tampering.

### R4 — Important — A missed completion boundary could reappear as successful on a normal reload

**Status: corrected and independently verified, including the terminal-publication follow-up.**

Initially the owner checked the deadline before product publication, but not after durable terminal publication and readback. An owner starting within its window could persist a successful result after the cutoff. A wrapper might reject the late response while a subsequent ordinary page GET still exposed the saved product as current and scheduled.

Two concrete cases were reproduced with the real store and owner. First, product generation occurred at 09:29:59 and terminal completion at 09:30:01. Second, after the first correction, writing a successful terminal journal was made to advance the clock from 09:29:58 to 09:30:02; the timestamp captured before that write still allowed success to escape. These were real original write/readback paths with a controlled clock and delayed write, not assertions against a replacement owner.

**Minimal correction applied:** check the completion boundary around product readback and again after terminal publication, journal verification, saved-plan readback and daily projection, immediately before a successful return. A violation enters the existing failure path and durably records `FAILED`. Ordinary and historical reads independently validate the exact scheduled attempt and its finish time; an unverified attempt yields `OWNER_ATTEMPT_UNVERIFIED` and `consumed=False` rather than a scheduled success.

**Evidence:** `v4/manager_research/workspace.py:770`, line 809, line 955, line 974, and line 978; `tests/test_manager_workspace_owner_20261008.py:81` and line 102, each parameterized for morning and preopen. The final post-publication guard and both slow-terminal regressions were included in the independently passing runs.

### R5 — Important — Independent US dependencies could consume the plan window or suppress other channels

**Status: corrected and independently verified; the absent independent US dispatch remains an explicit limitation.**

There were two observable failures. The bound plan RPC synchronously prepared mutable US mapping work before calling the original plan owner, allowing slow or failing unrelated work to consume the legal window. Separately, an ordinary workspace read could propagate an unexpected US reader `RuntimeError` or `ImportError`, suppressing all daily channels despite a valid consumed announcement product.

The original dispatch test asserting that slow US work crossed the deadline and prevented any plan call demonstrated the isolation failure; refusing a late backfill did not restore the independent plan opportunity. The ordinary-reader reproduction injected a failing original reader at the documented service dependency boundary and invoked the real workspace reader.

**Minimal correction applied:** the bound plan RPC now calls the original plan owner without synchronous US preparation. Existing US material is consumed through its original reader. Because no independent bounded US owner entry point is available in the supplied closure, the separate status is truthfully `NOT_ATTEMPTED` / `NOT_EVALUATED`, `matches=null`, with `US_MAPPING_REQUIRES_INDEPENDENT_OWNER_DISPATCH`; absent owner/reader bindings remain `CANNOT_CONFIRM`. Ordinary US reader failures are isolated as `SOURCE_FAILED` with a source-specific gap. No substitute producer, thread or retry framework was introduced.

**Evidence:** `v4/manager_research/plan_owner_dispatch.py:185` and line 262; `v4/manager_research/workspace.py:654`; `tests/test_manager_daily_dispatch_20261008.py:344`; `tests/test_manager_announcement_parity_20261008.py:354`.

This closes the cross-channel blocking defect. It does not claim that US mapping was refreshed or completed.

### R6 — Important — The supported publication-date URL alias requested a different announcement day

**Status: corrected and independently verified.**

The new frontend date parser originally considered only `announcement_date`, then the legacy `date`. A URL such as `?date=20261007&publication_date=20261006&plan_date=20261008` therefore requested publication October 7 despite the explicit supported publication alias specifying October 6.

**Minimal correction applied:** use a valid explicit `announcement_date` first, then a valid `publication_date`, then the existing legacy fallback. Explicit conflicts resolve to the canonical announcement parameter without changing the independent selection or plan dates. The agent added real request-query and panel-mount coverage.

**Evidence:** `apps/web/src/manager-selection/dailyChannels.ts:69`; the independently passing `dailyChannels.spec.ts` and `dailyChannels.runtime.spec.ts` suites. The later implementer correction that checks cancellation after each request await, including a late-resolving second binding GET, was inspected and is included in the same final 29-test frontend run.

### R7 — Important — HK Connect reported successful empty selection with a missing original archive/focus input

**Status: corrected and independently verified on the final patch.**

The daily HK channel relied on target membership and selection diagnostics, but those diagnostics covered the announcement lane and scope, not all original focus inputs. Missing archive/discovery/catalyst inputs could therefore be absent from the daily channel while the full workspace already reported their gaps.

The reproduction used the real `_FixtureService` and original workspace calculation, a valid target V2 scope, a verified successful-empty announcement-input fixture, and the original unbound research archive reader. `selection_diagnostics.status` was `READY`, while `RESEARCH_ARCHIVE_READER_NOT_BOUND` was present in the workspace and the material owner was partial. The HK channel nevertheless reported `READY_EMPTY`, zero candidates and no gaps.

**Minimal correction applied:** expose the original focus dependencies in `owner_chain.focus_inputs`, using the existing/archive, original discovery, material-discovery and catalyst-specific evidence. Require that evidence to be complete before reporting a complete HK count. These checks do not inherit unrelated US or market-screen gaps. Positive original focus rows remain visible when inputs are partial; unknown empty results retain `candidate_count=null` and the precise source gap.

**Evidence:** `v4/manager_research/workspace.py:631`; `v4/manager_research/workspace_daily_channels.py:139` and line 158; `tests/test_manager_daily_channels_20261008.py:108`; `tests/test_manager_announcement_parity_20261008.py:368`. The synthetic complete-empty control still reports zero only after complete original focus evidence is supplied. The real missing-archive regression and the affected original-owner suites passed independently after this final correction.

## Verification evidence

All fixtures described here are synthetic. Where stated, they exercise the real router, registered handoff/import path, original workspace owner, original storage transactions and readback validators. They are stronger integration evidence than a fabricated API response, but they are not evidence of authenticated external review or a natural production run.

| Independently executed check | Result | Scope and timing |
| --- | --- | --- |
| Five new Python suites: announcement parity, daily channels, daily dispatch, input contracts, real workspace owner | **116 passed**, one Starlette/httpx deprecation warning | Final source before the last HK focus-input patch; includes terminal publication, historical same-run readback, dispatch isolation and input contracts |
| Announcement parity, daily channels and real workspace owner suites | **67 passed**, same warning | Rerun after the final HK focus-input correction; includes the new original missing-archive regression and successful-empty control |
| Frontend `dailyChannels.spec.ts` and `dailyChannels.runtime.spec.ts` | **29 passed** in two files | Final frontend source; date aliases, API binding, nullable states, schema/run rejection, manual reread and cancellation behavior |
| Actual Python workspace JSON passed through the actual TypeScript workspace validator | **Five payload classes accepted** | Missing announcement, selected announcement, unassessed announcement, preopen volume pending, postclose volume pending; TypeScript emitted only into a temporary review directory |

Python used `/workspace/scratch/a154a3323e32/test_env/bin/python` with `PYTHONPATH=.:upstreams` and the frozen Python 3.14.6 runtime. Frontend tests used the available primary Node runtime and candidate Vitest installation.

The initial combined Python run had two duplicate-owner test failures because their frozen dispatch time preceded the owner's saved generation time. The test clocks were corrected to represent a possible execution ordering; the future-generation rejection was retained. Those failures are not unresolved code defects. The passing counts above overlap and must not be summed as a count of distinct tests. The 116-test run predates only the final HK correction; it is not represented as a run against every final byte.

## Strengths of the final candidate

1. **Announcement consumption follows one exact contract.** Import, analysis GET and workspace share evidence for target, publication, source manifest, owner receipt, registered handoff and judgment. Invalid source/receipt/time evidence prevents consumption, while an invalid legacy neighbor does not suppress a valid exact current pair. Legacy raw products are not silently rewritten.

2. **Scheduled identity is backed by the original durable owner.** The bound worker reaches the original plan owner; the readback binds owner, date, execution kind, run, product and sealed journal. Manual results cannot be promoted by a fast path. Per-trigger admission, durable retry/backoff and reconciliation of unresolved running attempts constrain repeated work.

3. **Source calendars and authority roles remain distinct.** Target-day HK_UNIVERSE_V2 is required for the formal Connect gate; D-1 capture remains diagnostic. The screen resolves a completed full native HK session and checks availability against the read cutoff. These repairs do not turn a prior-session capture into target authority.

4. **Unknown volume provenance remains unknown.** Numeric supplementation does not invent unit/scale attestation. Unproved volume stays `NOT_PROVEN` and pending, including numeric combinations that would otherwise appear to pass both gates. The original inclusive 0.80 price and 1.5 volume arithmetic boundaries remain covered by tests.

5. **The new display is a projection of existing decisions.** It preserves original focus/selection rows and reasons, reports independent dates and run references, keeps unknown counts nullable, and avoids duplicating full article bodies in the compact daily extension. The UI validates schema/date/run references before display. Scheduled kind alone never establishes `natural_run_verified=True`.

## Items declined for certification and remaining delivery gates

| Item | Why this review cannot certify it | Required evidence to close it |
| --- | --- | --- |
| Mac process and deployed source | Review ran in the supplied Linux scratch candidate; no deployed Mac process was inspected | Actual loaded process/module identity and hashes matched to the accepted source pack |
| Scheduler installation and natural execution | Synthetic dispatch and real-store tests do not show loaded jobs firing naturally | Loaded scheduler configuration, actual call target, natural slot execution, durable same-run owner receipt and page readback |
| Complete app import/build and old fixture suite | Supplied closure omits private PDF `DEPENDENCY_MANIFEST.json`, Stage `_namespace` helper closure and `us_mapping_research.py`; older fixture dependencies are absent | Original missing sources and fixtures supplied without invented substitutes, followed by the required original gates |
| Independent US production completion | No independent bounded US owner hook is available in the supplied source closure | Original independent owner dispatch and exact-session output/readback; current `NOT_ATTEMPTED` is not success |
| Real target V2 and canonical D-1 Top100 lineage | Contract tests use synthetic authority inputs; original Stage data/rules were not changed or certified here | Original owner/date/run/manifest/consumer evidence for each distinct authority role |
| Volume unit/scale attestation | Numeric evidence does not supply the missing owner provenance | Original authoritative unit/scale attestation; until then the pending result is required |
| Authenticated reviewer/source and platform identity | Fixture identities and hash validation demonstrate contract behavior, not external authentication or natural source acquisition | Real registered handoff, original acquisition evidence, owner import and exact deployed consumer readback |
| Whole-page production build/UI acceptance | The implementation team reports baseline source-entry and fixture omissions; this independent review ran the new frontend suites, not a successful full production build | Complete original source closure, production build, reload of deployed API/UI and real page acceptance |

The existing `businessStatus.ts` source-map mismatch was not repaired by overwriting it with different remote bytes. This review makes no claim that this separate provenance issue or the omitted original dependency closure is resolved.

**Delivery recommendation:** retain this as a reviewed candidate repair with the above external gates explicitly open. Do not label it fully delivered, merged, deployed, naturally executed or completely sourced solely on these test results.
