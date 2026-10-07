# HK Close Daily API candidate handoff

**State: final candidate handoff; independently reviewed and not deployed.** This is a bounded HK close daily API increment, not a complete independent checkout. The candidate release is `hk-close-daily-r1-20261007-api`, manifest SHA-256 `af281200af029b4e31f4b1fc653050f623aff3850fde10711a279e5fb346cb8a`, marked `NOT_ACTIVATED`. Independent reviewer receipt SHA-256: `50e7925834db9121e1313b64c03774d71c99d2d15d4eaeb9d6df9368114b3689` (`verdict=PASS`, `behavior_verified=PASS`).

## Date-bound evidence

The isolated candidate `create_app` readback reproduced the established 2026-09-11 close chain: `MODEL_REVIEW_READY`, row counts `691/20/100/70`, and model/stage hit counts `15/10`. This was an isolated TestClient result; it does not establish the active API or UI state.

For 2026-09-30, the candidate preserves `MODEL_0_2_SOURCE_MISSING`: row counts `696/20/0/0` and seven missing stages. The pool JSON, its pool receipt, and its manifest currently have mtime `2026-10-02T07:17:41.9Z`, about 47h06m44 after the process-level dispatch receipt finished on 2026-09-30. This timestamp statement applies only to those three pool files; it does not establish when the close-review artifact was created. Within the corresponding V35/V4 data roots checked in this audit, the referenced source run was not found, and the source artifact has no `captured_at` or `published_at`. Whether the pool existed at dispatch time and whether the source was point-in-time available remain **CANNOT_CONFIRM**. Do not recompute shared artifacts or treat a later file as a PIT-safe input.

For 2026-10-02, the HK Connect calendar reports `NON_TRADING_DAY`; the API returns an empty review with no Top20 or row counts. For valid date 2026-09-29, a missing review artifact returns `CANNOT_CONFIRM / CLOSE_REVIEW_ARTIFACT_MISSING`, with no fabricated rows.

## Frozen source delta and validation

The five candidate source/test entries are compared with repository base commit `d6ab71f02f8deb03f45514ce28dc35a983654c47`; exact per-file before/after SHA-256 values and the added-file status are recorded in `HK_CLOSE_DAILY_REVIEW_SUMMARY_SANITIZED.json`. The candidate backend package tests ran with Python 3.14.6 (`-B -m pytest -p no:cacheprovider --basetemp=<EVIDENCE_ROOT>/pytest-candidate-app-01 -q tests/test_hk_close_daily_binding.py`, 6 passed); the frontend test command was `npm test -- src/components/review/HkCloseReviewPanel.spec.ts` (3 passed), and `npm run build` passed with 110 modules transformed. The separate wrapper guard suite ran under Python 3.14.6 and passed 15 isolated tests.

## Root binding and wrapper status

The original API entry point did not pass `V35_REVIEW_CORE_CLOSE_ROOT`; the HK close reader therefore used the V4 default data root and failed to find the established close chain. The candidate binds the configured V35 review-core root and preserves default-root behavior when that setting is absent. Explicit invalid or mismatched artifacts remain fail-closed.

The source package and wrapper were independently reviewed `PASS`; the final wrapper review receipt is recorded above. The wrapper uses a retained same-filesystem claim and kernel no-clobber install. The active plist is atomically moved to a unique claim path, the moved bytes are verified, and the staged bytes are installed with `link(2)`; an `EEXIST` leaves the claim and concurrent target intact and records drift. Before bootstrap the wrapper requires the exact staged plist hash. After API semantic success, it revalidates the candidate package, active plist, and launchd's loaded PID, command arguments, app root, release ID, and manifest hash before writing an `APPLIED` receipt. Runtime identity drift is recorded and stops the wrapper without booting out an unidentified service. The independent reviewer reran the 15 isolated wrapper tests successfully and reported no P0/P1 findings. One non-blocking P2 remains: the successful-fixture test does not assert the receipt's loaded command-arguments and manifest-hash fields, although the reviewer inspected those fields in the isolated receipt and verified that a wrong loaded-arguments probe is rejected. The frozen wrapper SHA is `50235fefacb10e3173f060feff2bad8dad7e339351b31ae5e7600f00914c231d`.

The prior active API PID freeze (`1137`) is expired. The parent reports that the current service is still the old API root at PID `10546`; that is not the intended successor release and is not a readback of this candidate. The announcement task has offered a serial sequence: it will complete its switch/import/API/UI work first, then provide the final runtime root, plist, and source SHA. Its planned `announcement-daily-20261007-r2` release is not yet prepared or activated. The HK close candidate remains unapplied. The next integration stage must rebase the frozen, reviewed close delta onto the actual announcement release after those final bytes are provided. Active API readback for that successor release remains `CANNOT_CONFIRM`; UI and natural-slot checks were `NOT_RUN` in this writer scope. No service action, PID override, or deployment was performed.

## Delivery boundaries

Use the local-only `LOCAL_ONLY_SYNC_MAP.json` to identify the ten exact candidate/app source and dependency bytes and their proposed relative destinations. It is a control file and must not be included in a repository payload. The proposed payload contains only the five candidate source/test files and five required launcher/dependency files. Use the frozen candidate bytes for all mapped paths; the live workspace router, Vue panel, and spec differ from the candidate bytes.

Exclude generated `apps/web/dist` files, the release manifest with its full inventory and local paths, plist/real configuration, raw or derived market data, runtime artifacts, credentials, and this local-only map. The repository destination is `handoff/hk-close-daily-20261007/candidate/`. This is an incremental package, not a full checkout. No remote write or activation has been performed by this writer.

## Acceptance state

| Layer | State |
|---|---|
| Candidate source package | `REVIEWED: PASS` |
| Wrapper | `REVIEWED: PASS`; independent guard tests `PASS` (15); one non-blocking P2 test-assertion gap recorded |
| Isolated candidate API behavior | `TESTED: PASS`; `BEHAVIOR_VERIFIED: PASS` by independent review, based on isolated TestClient/date-bound evidence |
| Active API identity and readback | `CANNOT_CONFIRM`; `NOT_RUN` for the successor release until the announcement task provides final runtime identity for a separately scoped integration stage |
| UI readback | `CANNOT_CONFIRM`; `NOT_RUN` |
| Natural-slot behavior | `CANNOT_CONFIRM`; `NOT_RUN` |
| Deployment / service change | `NOT_DEPLOYED`; not performed |
| Trading safety | `production_allowed=false`, `buy_gate_updated=false`, `orders_sent=false` |

This handoff records candidate source/package review, wrapper review, isolated tests, and isolated behavior verification. The next integration stage must start from the announcement task’s actual finalized release; active API, UI, deployment, and natural-slot evidence for that successor remain unverified.
