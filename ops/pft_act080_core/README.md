# ACT-080 Phase 1B · V1.1

Run from the isolated V4 worktree with the configured panel Python.

```sh
"$PANEL_PYTHON" -m pytest -v -s ops/pft_act080_core/tests
"$PANEL_PYTHON" -m ops.pft_act080_core.run --archive "$VOL2" --output "$NEW_DIRECTORY" --workers 18
```

`ReplayState.consume` is the shared per-stock entry for a single bar, an ordered chunk, or an entire chain. Preserve the in-memory state across chunks. The archive loader binds the ZIP, chain bytes, ordered observed sessions, and stock roster. The zero-based observed-bar index advances on coherent finite OHLC with nonnegative volume. Coherent historical negative and zero QFQ prices remain in the index and absolute W/Y/ATR calculations. A bar with any nonpositive OHLC cannot qualify or create a Key K. Missing or nonpositive ratio denominators yield NA. QFQ adjustment PIT stays CANNOT_CONFIRM.

## Key K and episode lifecycle

`config.json` binds the reviewed anchor sources and the pre-replay lock. BREAKOUT applies the canonical PFT-F-F05 price, prior high, prior volume and return predicate. Today's predicate must be true and the seven preceding flags must all be evaluable and false. REVERSAL is the ACT074A1 mechanical upward reversal proxy using a full MA24 cross and previous-five volume expansion. VIOLENT and FUNDING_ACTIVITY use the two source rules from `score_zge_clean_scheme_v1_9.py`. Their BBI and five-volume averages use the available bars through D, with at least one observation.

A distinct Key K date opens one causal episode even when several types qualify. All types are retained and the primary type follows BREAKOUT, REVERSAL, VIOLENT, FUNDING_ACTIVITY priority. The key-day low and anchor session are fixed. A later close strictly below the anchor low retires the current episode before today's Key K and maintenance checks. The episode also retires when the gap from its last valid maintenance session exceeds 60 observed bars. At equality the episode can still be maintained. A retired episode requires a fresh Key K to restart. A fresh Key K replaces any still-active episode on its own date. Every stock has one separate cooldown clock that advances its last accepted session only on release.

Candidate gating requires a positive bar with C at or above the active Key K low, anchor age 0–29 observed sessions and the locked geometry. Geometry is positive W and Y, and either W>=Y with C>=Y or absolute W/Y gap at most 1.5 ATR with C>=W. Geometry can maintain an episode beyond the candidate age window. The three original ACT-074 arms run only after these gates with their existing parameters. The earliest A/B/C arm represents a qualified day. Later arms keep their raw rows and get DUPLICATE_SAME_DAY.

The first raw representative emitted by an episode is FIRST, including when its date is later than the anchor. The next B-eligible candidate date is CONFIRM once, and remaining rows are REPEAT. Accepted role uses the same rules on the accepted stream. `episode_opened_D` indicates the anchor day and can be false for FIRST. Stock/date/arm candidate IDs match Phase 1; use `config_sha256` alongside those IDs to identify the run rule. The structural episode IDs use the distinct Phase 1B namespace.

## Outputs

The feature table covers all raw candidate IDs. The released subset is identified by `accepted_flag`. W and Y, ATR14, and all Phase 1 feature calculations are retained. The separate time-split sidecar carries calendar folds and 10-observed-bar purge/embargo windows. Split rows are outside the prefix proof because their left-side masks use finalized boundary calendars. CSV files preserve sorted rows, repeat fixed headers, and use an empty cell for NA.

The combined JSON reports per-stock conservation, distinct raw stock-days, gaps, wave roles, maximum first-to-last raw emission span, feature NA, exact serial/parallel and prefix equality, input/code/config hashes and execution timings. The code digest concatenates top-level implementation Python files in lexicographic basename order with a `name:byte_length\n` prefix per file. Use a new output directory for every run. The final `CONSERVATION_AND_FEATURE_AUDIT.json` marks a completed run.
