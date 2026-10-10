# Minimal issue: rebound admission remains `CANNOT_CONFIRM`

## Decision

No formal selection or same-run manager consumption was produced. Keep `694_BATCH_HOLD`. The original strict/near two-gate rule and thresholds did not change.

## What code can fix

The date-storage compatibility patch in `source/date-storage-compat.patch` converts only the newly parsed `trade_date` representation to the parent panel's supported integer or string dtype. It validates exact `YYYYMMDD` calendar tokens and checks the encoded result losslessly. It leaves old rows and the parser's raw values unchanged. The change manifest binds the local pre/post source SHA and patch SHA. This is a storage fix, not a market-data scale or unit conversion.

## What current evidence does not prove

For historical target `20261009` / signal `20261008`, the only raw sample is one code. Its exact required cells are 60 prior-session highs, one signal close, and six full-session trade cells (67 total). Of 11 present raw date/field positions, 9 values match the SHA-bound repaired panel; 56 are absent, and 2 present trade values differ: `20260930` raw `76066` versus panel `7606640.0`, and `20261002` raw `85679` versus panel `8567907.0`. No scale conversion or normalization is justified. The signal close and signal-day trade are absent. The sample's repair lineage preserves scale 1 and says `formal_eligibility_verified=false`; it does not prove price basis/currency or volume units.

The historical target-membership candidate has 698 sorted-unique codes and valid producer-defined logical digests. Its capture was at 15:00 HKT, so its scope is `AS_OF_TARGET_CAPTURE_NOT_PREOPEN`; it is not a pre-open frame. Three members (`HK.00853`, `HK.02172`, `HK.02252`) have no row in the 695-row historical panel. No pre-pinned rebound deployment trust policy, owner-cell attestation, or rebound-bound membership attestation was established in the finite inspected evidence roots. This historical frame cannot serve actual target `20261010`.

The previous manager membership receipt reports `MATCHED` for the 698-code set, but explicitly has `rebound_selection_consumed=false`. It is not a selection receipt, same-run shared-ledger readback, or manager consumption proof.

The actual recorded request used target `20261010` / signal `20261009`. Its command exited 0 and its result was `CANNOT_CONFIRM`, with `ValueError:OBSERVATION_PANEL_BINDING`; no admitted selection was published. The separately recorded historical observation run is labelled `SYNTHETIC_TEST`; its arithmetic output (strict 0, near 1, excluded 0, unresolved 694 across 695 panel rows) is not an admitted list.

## Exact proof still needed

1. Deployment-pinned trust policy and approved owner-cell and membership-attestation IDs/SHA. The request may select existing approved IDs; it cannot create or self-sign them.
2. For every actual target member, exact SHA-bound 67-cell source-to-panel proof, with unique date/field cells, raw record locators, decoder and source identity, actual acquisition/availability times, owner-reviewed price basis/currency/scale, owner-reviewed trade unit/scale, and a daily product/finality contract. Unknown, missing, or mismatched cells remain pending.
3. Complete membership for the actual target, with capture/availability no later than the observation cutoff and the pre-approved membership binding. A 15:00 target-date capture is `AS_OF_TARGET_CAPTURE_NOT_PREOPEN`; it must not be represented as pre-open.
4. Valid observation for the same target/signal, selection commit and independent shared-ledger readback, followed by manager input identity and cutoff at or after `evaluated_at`.

No current source quota or current source authorization was checked. The only recorded quota query is historical (see `SOURCE_ROUTES.md`). This package does not request new quota, perform a fetch, or relax the 694 hold.

## Digest correction

An earlier diagnostic incorrectly compared raw JSON file-byte SHA with producer-defined logical self-digests. The corrected verification removes the self-digest field and recomputes with the frozen producer helpers: capture logical digest `34fcb9611e233a8eb612e47a3c419c0659f332beb97a7b718f807abec21a7e59` and publication logical digest `153ab53d3d2f09ac1dfd4931a8144ecacb220caf2e9009be976d3ab513e00c4b` both match. Different raw file-byte SHA values are expected across these hash schemes; digest corruption is withdrawn as a blocker. This does not resolve trust, units, timestamps, missing cells/members, or manager consumption.
