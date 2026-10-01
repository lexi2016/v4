# Stage A0925 cross-day candidate composition review

Date: 2026-10-01. Scope: composed release `20261001-stage-pr16-a1445-a0925-crossday-r1` against frozen base `20261001-stage-pr16-a1445-r1`; review only the A0925 collector/test/config delta. No activation, historical runner, API, UI, or natural-run check was performed here.

## Identity and composition

- Candidate readiness JSON SHA-256: `99ca56fcec864f92a067bef2e99ca24492aec04b351f93a51db1dc4f677c9cb8`.
- Candidate release manifest SHA-256: `5dc3be0b27fb46c9b2cb9b30d0d50ae0424395d69dc0ae3d143af88251fff204`.
- Candidate inventory declares 884 entries, aggregate SHA-256 `2c1fc4fbacb1d2e9a77e95564c6ed326648f77f94d81ceb9c6bb365cfcba1fc0`; verified all 882 regular-file hashes/sizes and both declared symlink targets against disk. Candidate and base path sets match, and the exact inventory delta is only:
  - `stage_center/_live_collectors_parts/a_auction.py`
  - `tests/test_tdx_minute_replay_provider.py`
  - `stage_center_tick_config.json`
- Candidate collector SHA-256: `2b39ede48161e6be59efc769849a8da2319521faeac3f2985b82de508e7c6aef`; test SHA-256: `90d87c551c0b2eabd7a4820520a2d3dd8c37355a31fced42cfce296e0a57078e`. Config JSON differs from base only in `release_id`, set to `20261001-stage-pr16-a1445-a0925-crossday-r1`.
- The collector delta changes only capture-time policy relative to the reviewed A1445 base: market cutoff must equal the exact target cutoff; `NATURAL` capture must be on the target date and at/before cutoff; `RECOVERY` capture must be strictly after cutoff. The reviewed exact 09:25 market-tick and approved-method guards remain in place. The behavior matches the independently reviewed source delta recorded at `a0925_crossday_capture_delta_review_20261001.md` (SHA-256 `7fd68be036a82cca4ca94936eedb1ef1154d3fff8520d443f2378e000fe109eb`).

## Focused verification

Using configured Python 3.14.6 from the candidate app root:

`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH='<candidate>/upstreams:<candidate>/app' '<configured-python>' -B -m pytest -q -p no:cacheprovider --basetemp='<review>/tmp_a0925_candidate_test' tests/test_tdx_minute_replay_provider.py -k '0925_auction_collector'`

Result: `4 passed, 11 deselected in 0.04s`.

No P0/P1 defect was found in this frozen delta. Carry-forward P2 coverage note: the committed tests do not persist exact-cutoff `NATURAL` and exact-cutoff `RECOVERY` boundary cases; the earlier source review records those as passing isolated probes. This does not block the bounded composition review.

## Verdict and limits

`REVIEWED: PASS` for the composed three-path candidate delta. `BEHAVIOR_VERIFIED` is limited to the targeted fixture tests in the candidate package. Candidate manifest/readiness say `NOT_ACTIVATED` / service false; the historical 2026-09-29 and 2026-09-30 binds/canaries, active service behavior for this new release, API/UI readback, and natural execution remain `CANNOT_CONFIRM` pending separate evidence.
