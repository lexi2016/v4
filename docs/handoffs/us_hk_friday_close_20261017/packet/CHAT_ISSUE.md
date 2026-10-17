# Chat repair issue: Friday US close did not advance V4 selection

**Handoff state: ready for independent review.** This issue package records the observed failure and a research-only Friday snapshot observation. No scheduler, service, production code, or trading behavior was changed here.

## User request

Use the completed Friday 2026-10-16 US session to prepare a US-linked research observation list, identify why the workflow did not automatically advance after the US close, and prepare a self-contained issue for a Chat-led code repair.

## Friday observation result

The compact, self-contained observation result is in [`evidence/research_observation_summary.md`](evidence/research_observation_summary.md) and [`evidence/research_observation_summary.json`](evidence/research_observation_summary.json). Detailed local `REPORT.md` and CSV tables are not required to understand or repair the automation issue; the complete CSVs and raw quote/mapping inputs remain local and are excluded from the GitHub issue package.

The local OpenD/Futu OpenAPI `get_market_snapshot` call queried the frozen 448-code non-OTC universe on 2026-10-17 23:10:34.936–23:10:35.544 HKT (SDK 10.06.6608). It returned 448 rows; 446 have a 2026-10-16 US Eastern `update_time` at or after 16:00 and valid positive `last_price` and `prev_close_price`. `EEX` and `MIMI` have no update timestamp and remain `CANNOT_CONFIRM`. The reported observation metric is `(last_price / prev_close_price - 1) * 100`; pre-market and after-hours fields are retained separately. This is an after-close quote snapshot, **not** a verified official daily-close bar, shared owner artifact, prediction, causal effect, recommendation, or trade signal. Futu documents US `update_time` in US Eastern time and the `last_price`/`prev_close_price` fields in its [official snapshot API reference](https://openapi.futunn.com/futu-api-doc/quote/get-market-snapshot.html).

Using the existing mapping input snapshot (catalog `us_hk_667_20261015_from_20261014_membership`, 667 HK codes / 1,003 unique relations, overlay SHA-256 `3289f0329f0fe2e447a70386341790cb9821df2e76d13a650143fe07f9e9e91c`), the builder produces 270 positive, 430 flat-or-negative, 57 missing, 221 `OPEN`, and 25 excluded rows. These buckets sum to 1,003. Positive rows link to 128 US symbols with a closed research-scope relation and 222 HK codes. `OPEN` and excluded status takes precedence over quote direction. The mapping contains funds and other non-common-stock securities as well as common equities; each row retains the mapped use scope and research status. The top 20 US and HK observations are in `REPORT.md`; no research status is promoted by price movement.

The full snapshot is local at `evidence/futu_snapshot_full_capture.json` (4.45 MB, SHA-256 `8e1548621c5c37e74a084c64e42ff4029b97f7dd852782dea74f493ca693301e`); the 3-symbol canary is `evidence/futu_snapshot_canary.json` (SHA-256 `f997df280b3719e25aad09721c92962e09fe586ad9bf0bc4deb3450ae30092f0`). The mapping input remains at `docs/handoffs/us_hk_mapping_today_20261016/mapping_input_snapshot.json` (SHA-256 `f819ca2f036953d0989a2a28127072d41ac7e051f209087a38953299251a0df3`). These raw inputs remain local; the report and issue use their traceable paths and hashes.

Independent review recorded two non-blocking research-presentation/tooling limits; they do not change frozen rows and do not indicate an `OPEN` candidate leak. `top20_us_observations.csv` builds `linked_hk_codes_json` from all mapped relations, so it may include HK codes linked only through `OPEN` relations; use `candidate_stocks.csv` or `positive_relation_observations.csv` for closed-scope positive-candidate evidence. The frozen builder accepts `--verify` but still rebuilds/overwrites outputs; any necessary replay must use an isolated temporary copy and must not invoke either capture script. Positive oil-linked source price movement can be a cost-pressure direction for airlines and similar users, not an automatic benefit.

The next HK trading date is **20261020**, not 20261019: HKEX's [2026 securities market holiday schedule](https://www.hkex.com.hk/-/media/HKEX-Market/Services/Circulars-and-Notices/Participant-and-Members-Circulars/SEHK/2025/ce_SEHK_CT_075_2025.pdf) lists Monday 2026-10-19 as a no-trading holiday.

## Read-only failure evidence

The controller-owned [read-only audit](../audit/READ_ONLY_AUDIT.md) identifies three breaks in the dispatch/date/handoff path. Source review identified a fourth break in the actual selector consumer:

1. **Dispatch stops before workload.** The loaded `com.lexi.v4.us-market-digest` LaunchAgent has no `EnvironmentVariables` binding. Its pinned dispatcher requires `V35_APP_ROOT`, `V35_RELEASE_ID`, `V35_RELEASE_MANIFEST_PATH`, and `V35_RELEASE_MANIFEST_SHA256`. The first current-log failure is 2026-10-14 21:00 HKT, `RELEASE_IDENTITY`, with zero workloads started. The 2026-10-17 04:15, 05:15, 21:00, and 22:00 slots fail the same way; the 04:15 slot should resolve to US session 20261016, but no Friday-close workload or receipt was produced. The dispatcher records only the typed failure; which hidden identity sub-check would fail next is not logged.
2. **Date fields are conflated.** The 20261017 04:15 HKT slot resolves to US session `20261016`, but `run_us_market_slot` reports `scheduled_date=business_date=target_date=20261017`; the enabled catalog workload passes `BUSINESS_DATE` to `ops.us_market_digest`. The manager consumer separately binds by target date, with a US-session-date fallback and a capture-session validation. The pipeline therefore needs an explicit contract carrying US session `20261016` to HK target `20261020`, while preserving scheduled date, trade date, US session date, source cutoff, manifest, and SHA as distinct values. An 18:00 stage slot targeting the HK holiday `20261019` also failed.
3. **There is no post-close handoff to the existing selector.** The running manager WorkbenchHook generated its target-20261020 draft at 17:39 HKT on Friday, before the US session ended, with `INPUT_MISSING`. Its heartbeat handles HK 09:25, changed stage runs, and a once-per-source-day 16:30 next-day plan; the Saturday HK calendar returns `NOT_APPLICABLE`. The US digest workload invokes only `ops.us_market_digest`; it does not refresh the manager selection or verify Feishu delivery. A later source artifact therefore has no evidenced event path that refreshes the already-created draft.
4. **The displayed 1,003-relation catalog is not the actual selector input.** The catalog loader validates/displays the frozen 667-stock / 1,003-relation overlay, but the loaded API `announcement-continuation-api-20261017-r11c` reaches `NativeAdapters.us_mapping` through dynamic bindings. The read-only reviewer found 37 distinct relations in that projection: 10 evidence-backed relation identities matching 10 reviewed pairs, 5 reviewed seed relations, and 22 `PROPOSED` / `PIT_UNCONFIRMED` registry relations. The count is neither 1,003 nor the older 32. Treat this as an actual-consumer integration defect: make the existing selector consume the frozen projection and prove it by consumer readback, not by catalog display/API response alone. Preserve source, status, use-scope, evidence and PIT fields. Do not promote 757 `CLOSED_RESEARCH_SCOPE` rows to `REVIEWED` or PIT-safe; retain all 221 `OPEN` and 25 `CLOSED_EXCLUDED_SCOPE` rows as non-selectable.

   The package includes [`evidence/real_relation_projection.json`](evidence/real_relation_projection.json), a field-preserving projection of the frozen mapping input: 667 stock identities and all 1,003 relation identities, with original status, use-scope, evidence, gaps and provenance. Machine checks matched every projected relation field-by-field to the frozen input and confirmed the 757/221/25 status split. This is a derived test fixture (`is_owner_artifact=false`, `is_complete_overlay=false`, `no_quote_data=true`), not the 43,652,024-byte owner recovery overlay. It can support a source-level consumer identity/count test; it does not prove that the loaded API read the canonical owner overlay, nor API/UI/natural-run acceptance. Those remain `CANNOT_CONFIRM` until the actual consumer is run against the canonical overlay and its receipts are read back.

The prior shared payload `/Users/lexi/Library/Application Support/com.lexi.v4.local/state/data/research/peripherals/20261016/external_finance.json` (SHA-256 `fedb7f6f3b993d460ae029158bf73748f6205a23802395ccd8b2a642601be7ae`) is labeled `trade_date=20261016` but contains US `session_date=20261015`. No shared owner payload or receipt for session 20261016 or target 20261020 was found. The 20261016 18:27 HKT Futu capture from the prior handoff is also stale for Friday's US session. The ad hoc after-close snapshot above gives a descriptive observation list but does not fill the missing canonical owner receipt or confirm official daily close.

## Runtime source identity

The US digest release is `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/futu-industry-us-20261016-r1/app`. Key source files and hashes from the audit are:

| File | Relevant lines | SHA-256 |
|---|---|---|
| `infrastructure/scheduling/dispatcher.py` | 43–78, 246–260 | `7e61cbb234246bd88c9325fb0641c4bbead10debed09b924298e406b06854668` |
| `ops/run_us_market_slot.py` | 339–396, 443–484 | `0244fd5e717b3977e5d227b6084fd12eb77f2ebef6802be629b2761596e2f79e` |
| `contracts/runtime_workloads.json` | 1732–1765 | `bd9ff31db78fa3eb491799fa389eac2d9871602a191cc4885fd75afb9489e29b` |
| `ops/us_market_digest.py` | 725–727 | `96b15646e35fad6e399edb61eb8c3bd8d20b52141323e0bb1ce477b7313bcaf8` |
| `ops/_us_market_digest_parts/cli_primitives.py` | 65–112 | `252bcc75e3f1ff26ffe58c16c49935d36f5f9ed4811d8bd820f7a454a9d21968` |
| `ops/_us_market_digest_parts/phase_publication.py` | 6–24, 62–94 | `6a0abaef5e2f50297d3021d06e781c1832a690d09269317f84fa407505027379` |
| `ops/_us_market_digest_parts/phase_payload.py` | 120–178 | `fdfeeaf376efb3f2def86abd633d94790e0e9163586d23068eb9bab2c343bd56` |

The loaded `com.lexi.v35.scheduler` plist and running process bind the manager source root to `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/zsxq-long-pdf-scheduler-20261016-r3/app`; the v15 runtime path supplies the interpreter, not the source root. The launcher is `ops/launch_v35_macos_scheduler.sh` (SHA-256 `0c577ae83b1f182dabf3b62e642a5bd5f0f8708b48e1806d8c653b691d2ec952`, relevant lines 5–9, 63–64, 92–94). Active manager files are `ops/run_v35_macos_scheduler_daemon.py` (SHA-256 `1d03d0b21e352a772278e326086ef50a4e43dbfdeacb2dbf56111b496773476a`, hook call at 940–947), `v4/manager_workbench/supervisor.py` (SHA-256 `0d45e31daba2205fb504debcdf4fa1273ac5db9def2ff2f3f2a383f7b1470f97`, WorkbenchHook at 16–55), and `v4/manager_workbench/scheduler.py` (SHA-256 `0672296a340ae84d6bfb48b77b8d23566ea32b4fdb27edc505ea3abb4d785990`, tick at 24–124). The current selector API binding separately lives in `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/announcement-continuation-api-20261017-r11c/app/v4/manager_workbench/inputs/`; audit references are `native.py:25–37,90–100` and `source_bindings.py:499–525`. Work from the repository's owning source after matching it to these deployed identities; do not edit release copies.

## Bounded repair goal

Repair the four evidenced breaks in the existing path:

- Bind the US LaunchAgent to the required release identity at its owning configuration/source boundary, while preserving dispatcher manifest validation.
- Keep scheduled date, US session date, next HK trading date, owner artifact date, source cutoff, run ID, manifest and SHA distinct; resolve 20261016 to 20261020 with the existing calendar.
- After the exact-session owner artifact is committed, idempotently refresh the existing target-20261020 manager draft through the existing selector and record separate capture and consumer receipts. If the source is absent or partial, preserve its exact status, date and coverage; never silently backfill 20261015 or claim a close bar from the ad hoc snapshot.
- Integrate the frozen 667-stock / 1,003-relation overlay into the existing selector consumer and prove the consumer's actual readback. Preserve relation identity and original source/status/use-scope/evidence/PIT fields; do not promote `CLOSED_RESEARCH_SCOPE` to `REVIEWED` or PIT-safe, and keep `OPEN` / excluded relations non-selectable. A catalog endpoint or UI projection alone does not pass this case.
- Carry forward the two reviewed research-result limitations: Top 20 linked HK codes aggregate all relation statuses, while candidate evidence comes from positive closed-scope rows; and the frozen builder's `--verify` rebuilds outputs, so do not run it against frozen files. Keep oil-linked source movement distinct from beneficiary direction because it can be a cost pressure.

Do not add a producer or data panel; change ranking or mapping semantics; promote open/excluded relations; expand provider permissions; bypass release checks; change trading gates; or conflate page/API, notification, and natural-run acceptance. Keep `RESEARCH_ONLY=true`, `production_allowed=false`, `buy_gate_updated=false`, `orders_sent=false`.

## Acceptance matrix for Chat

| Case | Required result |
|---|---|
| Launch dispatch | Required release identity reaches the dispatcher and existing manifest checks pass; failed identity still produces an actionable typed receipt and starts zero workloads |
| Exact session and date mapping | The 20261017 04:15 HKT slot binds US session 20261016 and maps it to HK date 20261020, skipping 20261019 |
| Source identity | Consumer binds the exact owner artifact/receipt, session field, manifest, SHA, cutoff, and run ID; no stale 20261015 fallback |
| Partial source | Missing or invalid rows remain explicit and traceable; observed subset is not relabeled complete and absent values are not imputed |
| Mapping | Preserve the pinned 667-stock / 1,003-relation input and 757/221/25 status split; relation counts conserve and open/excluded never enter candidates |
| Actual selector mapping input | Prove the selector consumer reads all 1,003 frozen relation identities, not only the catalog; source/status/use fields remain unchanged, `OPEN` and excluded remain non-selectable, and `CLOSED_RESEARCH_SCOPE` is not promoted to review/PIT eligibility |
| Post-close consumer | A committed exact-session artifact refreshes the existing target draft; repeated delivery of the same identity creates one canonical result |
| Provider failure | Original error, attempted session, coverage, and retryable state survive to the downstream result; no fabricated result or stale fallback |
| API/page/notification | Report API readback, reloaded page, and notification receipt separately; no one surface implies another |
| Natural run | Verify the next eligible natural slot against its source, run ID, output, API/page and delivery receipts; until then `NATURAL_SLOT_UNVERIFIED` |
| Safety | All four frozen research-only/trading safety flags remain unchanged |

## Chat prompt

The complete Chinese prompt for direct copy/paste is [CHAT_PROMPT.md](CHAT_PROMPT.md). It starts from repository-relative links to this issue, `source_context/README.md`, `SOURCE_MANIFEST.json`, and the evidence directory; it does not require any local absolute path. The prompt includes all four gaps, frozen scope, required acceptance, and diff/test/rollback deliverables.

## Local replay and remaining gaps

- An independent reviewer reran the frozen builder in an isolated temporary copy and reported `PASS`; 448 quote rows returned, 446 valid after-close snapshots, 2 `CANNOT_CONFIRM`, and all 1,003 relations were conserved. The builder's `--verify` argument still rebuilds/overwrites outputs; never run it against the frozen handoff path and do not invoke capture scripts.
- `CANNOT_CONFIRM`: the GitHub issue ZIP deliberately omits raw quote and mapping inputs, so regenerating the full research tables from that package alone is not possible. The packaged compact summary, audit, source excerpts, hashes, and result semantics are sufficient for the code-repair task.
- `CANNOT_CONFIRM`: the ZIP includes the derived 667/1,003 relation projection as a test fixture but omits the full 43,652,024-byte recovery overlay and raw mapping input. The fixture does not establish full owner overlay identity at runtime or selector/API/UI/natural consumption; verify those on the actual target runtime after repair.
- `CANNOT_CONFIRM`: an exact official 20261016 US close bar and canonical shared owner artifact/receipt were not found; the LaunchAgent diagnostic does not expose the hidden identity sub-check; no post-close API/page refresh, notification receipt, or natural-slot result is verified.
- Code repair, GitHub submission, deploy, service restart, and natural-run verification are outside this writer handoff.
