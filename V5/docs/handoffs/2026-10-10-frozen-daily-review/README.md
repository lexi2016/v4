# Frozen daily/manager issues for E and external Chat

Freeze basis: 3d9541aca3e5d28e94109609940503cca239b9fe. Original announcement revision: e06d143e881c66c22053a5c594b9c0be21d5be34. Do not substitute current branch HEAD when reproducing these two issues. SOURCE_INDEX.json indexes318 source/contract/fixture files by fixed commit, repository path, byte length and SHA256. It includes a conservative shared Python support set and the full original e06d handoff fixture bundle; it is not a claim of runtime/data evidence.

E's latest reported evidence:43 unit tests PASS; original chain1 PASS /1 FAIL. Actual test logs, invocation times, interpreter/dependencies and private input/reference receipts are held by E and must be added to the final problem package. Cloud did not run or verify Mac tests. No real reviewer/body/market data is uploaded by this handoff.

## Frozen issue1: cross-day automatic read assertion

Call path:
- V5/tests/test_daily_revision_chain.py::DailyRevisionOriginalChainTests.test_original_manager_save_then_auto_read_consumes_revision fixes target=20261009 and uses datetime.now for refresh/auto read.
- V5/src/v5_shadow/manager_plan.py::run_manager_plan → _assemble → original workspace.refresh_workspace_plan; independent original saved-plan/attempt reader returns matching run/SHA.
- Subsequent action=read, view=auto calls original workspace.get_workspace.
- V5/vendor/manager_plan_baseline/v4/manager_research/workspace.py::get_workspace routes target<actual HK today into workspace_history.read_history.
- workspace_history.select_plan admits generated_at and saved research_cutoff only within the original historical boundary. If no eligible saved plan exists, read_history returns HISTORY_QUALIFIED_SAVED_PLAN_MISSING; plan run_id is null.

Reported scenario: on10/10 create a10/9 manual recovery plan, refresh response says CURRENT; auto then correctly takes the historical route, which does not qualify the late-created recovery as an on-time10/9 plan. Test compares saved run_id to null. Source supports a clock/view/qualification mismatch; a CURRENT refresh label is not proof of historical eligibility. Whether the solution belongs in fixture date selection, recovery-view presentation, or a separately explicit recovery read contract is the external review question. Do not backdate generated_at/cutoff or relax original PIT/history gates to make the assertion pass.

Relevant unchanged functions: workspace_history.boundary_context, select_plan, read_history; workspace.refresh_workspace_plan/get_workspace; daily_owner_adapters.run_manager_daily (today-only guard, same-attempt save/readback and ordinary auto read); daily_manager_assembly.assemble_manager_request (real cutoff sealed once); daily_tick.tick (08:45 plan admission). Exact source bytes are indexed at the failing baseline, not at the separate US increment.

## Frozen issue2: actual reviewer missing revision binding

Original e06d ops/run_v5_decision_revision.py::create_revision requires reviewer_output.decision_revision == _review_binding(...), before creating immutable revision. Required fields: revision_id, parent_product_sha256, parent_owner_receipt_file_sha256, source_recovery_receipt_sha256, source_run_id. It separately requires decision_status=EXPLICIT_DISPOSITIONS and original logical digest of article_decisions. Original register-handoff still checks actual distinct reader/reviewer identities, dates, catalog/body/semantic hashes and PASS.

Reported actual reviewer lacks decision_revision. This is revision provenance binding failure, not evidence that semantic judgments failed. E should include the sanitized exact reviewer key structure, original hashes, create argv and error traceback. External Chat must distinguish code issue from a new actual reviewer acknowledgment of the pinned parent/revision; do not fabricate PASS or mutate a previously frozen reviewer file behind its SHA. The independent semantic review, missing provenance and unchanged91 content/PIT gates are separate concerns.

Source paths: V5/src/v5_shadow/daily_announcement_revision.py::run_revision; announcement_offline_reader.py (revision read transport); V5/vendor/announcement_revision_baseline/ops/run_v5_decision_revision.py, run_v5_offline_analysis.py, run_manager_daily_announcement.py; original fixed e06d tests/test_decision_revision.py and tests/test_offline_analysis_chain.py. All are indexed.

## Frozen scope / independent ongoing work

No patch to either issue was made after freeze instruction. Independent US repair is commit7a3d3bc1e7a51899a60b455fcc6502c9e66eab60: optional original native reference-identity input reconnects material discovery, and complete original reviewed seed is exposed without changing matches. This US-only increment changes manager_plan input binding, not its historical auto route or reviewer contract. Keep its acceptance separate; do not use it as the reproduced failing baseline.

Daily source/Reader/Reviewer execution gap remains separate: known original supervisor invokes run_manager_announcement_cycle through a validated runtime binding; semantic/reviewer outputs remain external heartbeat human/agent inputs. No available task-submit/return runtime binding was invented. E alone owns preview publication; no cloud installation/deployment was performed.
