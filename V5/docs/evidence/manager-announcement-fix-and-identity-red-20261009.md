# Announcement adapter fix + separate plan-identity RED

Base accepted production: bb61f2ec259c0140d0065de14b109a0b41ebf1c3.
The f1d8bae test-only changes are retained on the existing development branch
via cherry-pick bfe7377. No new branch is created for this implementation.

## Actual preceding evidence

Mac ran f1d8bae once: six tests, 2 PASS / 2 FAIL / 2 ERROR / 0 SKIP,
exit 1, 2.534s. Raw failure count five includes four size-path subtests.
Exact corpus size and no target09 fallback passed. Generic file/group limits
failed. Existing-product consumption and plan save raised missing
get_announcement_analysis. All 758 input and 428 source SHA sets were unchanged.

## Implemented announcement changes

- Manager snapshot reuses announcement_bridge._input_limit: only the exact
  body_corpus path receives 32MiB; all other files remain 16MiB, each group 64MiB.
- Bind get_announcement_analysis to original announcement_analysis.read and
  get_announcement_date_catalog to original workspace_announcements.read_date_catalog
  on the existing private service and roots. Original receipt/handoff/judgment/
  cutoff and missing-input decisions execute unchanged; no full service pool.
- Include the reused announcement helper's file in adapter implementation identity.
- No original reader capsule, sealed saved artifact, V4 setting or API limit changed.

Existing Mac verification, with the same expanded input request environment:

```sh
PYTHONPATH=V5/src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s V5/tests -p 'test_manager_announcement_binding.py' -v
```

Goal: all six pass through real package consumption and original saved-plan
readback. This candidate has NOT been tested in the cloud. Errors and behavioral
failures must be reported separately.

## P2: tests only; implementation deliberately still unchanged

Strengthened the actual adapter test to require a five-minute-later read with
unchanged owners to remain CURRENT with the same run/input_identity, original
saved plan_context, actual current runtime/screen cutoff and no file changes.
The old branch accepting STALE_INPUTS_CHANGED is removed.

Added original production projection tests: changing only nested screen
research_cutoff must preserve identity while preserving both payload timestamps
and caller inputs; changing source SHA, daily session, phase or admission gaps
must still change identity. These screen controls are synthetic boundary cases,
not real source-origin evidence. Existing production projection remains unchanged
pending independent behavioral RED.

Run P2 separately from announcement acceptance:

```sh
PYTHONPATH=V5/src PYTHONDONTWRITEBYTECODE=1 python3 V5/tests/test_manager_plan.py ManagerPlanAdapterTests.test_saved_plan_context_is_not_replaced_by_current_runtime_overlay -v
PYTHONDONTWRITEBYTECODE=1 python3 V5/tests/fixtures/manager_owner/check_candidate.py ProductionAdmissionTests.test_screen_cutoff_only_change_preserves_identity_and_payload_timestamps ProductionAdmissionTests.test_screen_source_session_phase_and_admission_still_invalidate_identity -v
```

Expected unverified RED: first command finds STALE instead of CURRENT; second
command's cutoff-only identity assertion fails, while source/session/phase/
admission sensitivity remains a passing control. The production candidate
subprocess now has eight tests; full manager discovery is expected to remain
red until the independently verified P2 fix. Do not report this candidate as a
new full-suite pass or promote it over bb61f2e's fixed preview merely because
announcement checks pass.

## Next sequence retained

After P2 RED, normalize only data_context.research_cutoff in a copy used for
screen hashing, preserving payload and all source/session/phase/admission gates.
Never modify existing sealed products or hard-code CURRENT.

Then fix the ordinary UI's actual query/date binding: date09/viewauto succeeded,
but selection_date09/announcement_date09 is not the same query as the published
payload's announcement date08. Do not fabricate a query alias or mislabel 503 as
verified concurrency exhaustion.

For daily announcement acquisition, follow the existing full owner flow at
0fd5eb374cb155232ed003d5fc4d0d3594252491:
`handoff/manager-daily-chain-20261008/source/api_app/ops/run_manager_daily_announcement.py`
and its `manager_announcement_body_batch.py`. Reuse _capture -> full
EASTMONEY_HK_DATE_CATALOG -> all-row body_batch, resume_evidence_run_id and real
idempotency/stop conditions. WORKERS=3 is concurrency; there is no current
proof that three is an upstream API limit. Do not merely raise BATCH_SIZE while
max_issuers remains three. Current V4 plan-material slots are not collection,
and the old cursor's observed +3 progress is not evidence of starvation.
No live V4 binding, collection, deployment or schedule is changed here.
