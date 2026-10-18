# Friday US close actual selection run — 2026-10-18

The actual manual research run was executed and is visible in the existing manager workbench. Complete selection acceptance remains **PARTIAL / CANNOT_CONFIRM**, not a valid all-clear zero-candidate conclusion.

- Target HK date: 20261020; phase MANUAL; run `81f492f043a346828a5b72cc6bc4206b`.
- Cutoff: 2026-10-18 14:54:19 Asia/Shanghai; finished 14:54:50. One POST only, no retry.
- US source session: 20261016. Existing canonical artifact is under capture directory 20261017, not 20261016. The earlier claim that no valid Friday owner archive existed was based on an incomplete two-path lookup and is superseded by this verified manifest lookup.
- All 48 quotes match independently checked daily closes; 96 Decimal comparisons cover previous and current close. Original controlled-late capture timestamp 2026-10-17T15:35:31Z is preserved. This is cross-vendor corroboration, not an exchange attestation or PIT certification; per-symbol corroboration HTTP times remain unknown.
- Source coverage: 48 observed, 9 assessed, 39 unassessed. All nine assessed source groups were not selected because the Friday change was not positive.
- Saved stock counts: selected 0, watch 0, unassessed 649, not_selected 3. The three stock exclusions have membership/relation limitations; they must not be equated with the nine assessed source outcomes.
- Full saved research lane: 1,063 records. The 1,003-row catalog relation projection was consumed; the API page size did not truncate selector inputs. Stock/source/relation record counts are distinct.

## Remaining selection blocker

The factor consumer pins a candidate/review pair dated 20261013; this run targets 20261020. Its hashes, schema and linkage pass, but the date guard correctly returns `US_FACTOR_PAIRED_ARTIFACT_IDENTITY_INVALID`. No supported existing target20 pair builder was found. A new pair requires exposure evidence, date-specific identity/Connect verification and independent review; Friday quotes alone cannot create it. The factor engine also only admits RETROSPECTIVE while this actual run is MANUAL. No pair was relabeled, guard weakened, phase changed, or second producer introduced. Broader relation/PIT and industry-classification gaps remain visible.

## Delivered and verified

The API's one-file manifest-bound archive resolver fix was independently accepted (19 focused tests, real owner canary, 1,238 non-delta files preserved). API release `friday-close-input-api-20261018-r1` is active at port 8873; manifest SHA `0865254e40584da570cfd93aabfdd77c6f9bf8b38a8ca6ba30eb8fcc84d54bba`, source-binding SHA `ae9e3b712d6f899f944816eea25837a7fdc26bddc13b7a347a7e87816f86a0f2`. Manager config is unchanged. The reviewed live plist SHA is `5b31a24029e0d1cf8f6a83e20febf1c0af8675e357d13c8ed68289a7026459b0`.

The API and reloaded UI show the same new run, MANUAL phase, PARTIAL state, source coverage, empty recommendation list and explicit factor gap. `UI_PARTIAL.png` and `UI_FACTOR_GAP.png` are local visual evidence. This verifies actual execution and truthful partial display; it does not satisfy complete selection semantics. See `RUN_INDEPENDENT_REVIEW.json` for the final independent acceptance boundary.

This manual historical run does not prove the natural chain. Issue45 remains open; the first pending fresh natural slot is 2026-10-20 04:15 Asia/Shanghai (US20261019 to HK20261020), with the existing 04:35 monitor. Preserve the above historical correction and inspect actual runtime drift before any follow-up.

Canonical business source was already correct and was not overwritten. Necessary preparation helpers, exact runtime delta and compact evidence are synchronized on `codex/issue45-friday-close-run-20261018`, based on `32d940ea014614fcb77e96f974c2b8941cf18812`; final remote verification is recorded separately. No raw market responses, full overlay, credentials, logs or runtime bundle are uploaded.

Safety: RESEARCH_ONLY=true, production_allowed=false, buy_gate_updated=false, orders_sent=false.
