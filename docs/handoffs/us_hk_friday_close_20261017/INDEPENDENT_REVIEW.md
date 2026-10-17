# Independent review: Friday US close handoff

## Verdict

- `REVIEWED: PASS` for the frozen research output and Chat repair packet.
- `TESTED: PASS` for the isolated offline replay and final package integrity checks. Focused runtime regression suites were inspected but not run because this batch changes no production code.
- `BEHAVIOR_VERIFIED: LIMITED` for the deterministic descriptive snapshot builder only. Automatic selection and full runtime overlay consumption remain `CANNOT_CONFIRM`.
- No P0 or P1 finding blocks this handoff. Three known research/tooling limits are recorded below as non-blocking P2 constraints.

## Evidence checked

The frozen builder replayed successfully in an isolated temporary copy. `REPORT.md` and all five result CSVs were byte-identical to the frozen outputs; `results.json` was semantically identical after normalizing temporary paths. The replay counted 448 returned quote rows, 446 exact-session after-close rows with valid prices, and two `CANNOT_CONFIRM` rows. The 1,003 relation buckets conserved: 270 positive, 430 flat-or-negative, 57 missing, 221 open, and 25 excluded. Candidate construction uses only positive `CLOSED_RESEARCH_SCOPE` rows; no `OPEN` row entered `candidate_stocks.csv`.

The `real_relation_projection.json` fixture was compared with its pinned source snapshot. Its 667 stock rows and 1,003 relation rows, including every projected relation field and source order, match the frozen `mapping_input_snapshot.json`; the snapshot and recovery-overlay SHA values match the fixture metadata. Status counts remain 757/221/25, safety flags and `research_only` match the source, and the fixture contains no quote rows or price fields. It is explicitly marked derived, non-owner, and non-complete.

All 24 runtime/test source entries, 6 evidence entries, 33 packet artifact entries, and 34 writer-receipt file hashes verified. The final ZIP has 37 entries, passes CRC validation, includes the prompt and relation projection, and excludes CSVs, capture scripts, raw captures, the original mapping snapshot, and the full recovery overlay. ZIP SHA-256: `50ac78d8eba8448217a903d8330720a648b6f0472e390abd3d63f22e3e1173bd`.

## Findings and boundaries

- **P2, documented:** `top20_us_observations.csv` builds `linked_hk_codes_json` across all mapping statuses, so a displayed US row can list `OPEN`-only HK links. This does not leak `OPEN` rows into the candidate table. Use `candidate_stocks.csv` or `positive_relation_observations.csv` for closed-scope candidate evidence. Evidence: `packet/CHAT_ISSUE.md:19`, `packet/evidence/research_observation_summary.md:8`.
- **P2, mitigated in the handoff:** the builder accepts `--verify` but rebuilds and overwrites outputs. The dangerous direct command was removed from the issue; the packet now says replay happened only in a temporary copy and warns against running it on the frozen path or invoking capture scripts. Evidence: `packet/CHAT_ISSUE.md:19,86`, `packet/source_context/README.md:15`.
- **P2, interpretation guard:** positive oil-linked source movement can be cost pressure for airlines and similar users, not an automatic benefit. Evidence: `packet/CHAT_ISSUE.md:19`, `packet/evidence/research_observation_summary.md:10`.

The issue describes the four evidenced breaks: missing US dispatcher release identity, conflated scheduled/session/target dates, no post-close event refresh of the existing selector draft, and a displayed 1,003-relation catalog that differs from the active 37-relation selector projection. It includes repository-relative implementation prompt, source excerpts/tests with SHA-256 manifest, runtime/API count evidence, synthetic contract fixture, and the field-preserving relation projection. It warns Chat to match the target base before editing where worktree source differs.

The full 43,652,024-byte recovery overlay and raw mapping/quote inputs remain outside the ZIP. Therefore the fixture does not prove that the canonical full overlay has been consumed by the live selector. The exact official US daily close, canonical shared owner receipt, post-close API/page refresh, notification receipt, and natural slot are also not established. The dispatcher log does not identify the hidden `RELEASE_IDENTITY` sub-check. These remain `CANNOT_CONFIRM`; no `API_VERIFIED`, `UI_VERIFIED`, notification, or natural-run status is claimed.

Focused tests reviewed in the package include dispatcher, US session calendar, owner handoff, manager scheduler, and selector binding/engine tests. The manager 16:30 test excerpt is explicitly marked worktree-only, not present in the loaded scheduler release. No production code, configuration, service, or trading gate was changed by this handoff.
