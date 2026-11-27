# ACT-080 Phase 1

Run from the isolated V4 worktree with the configured panel Python.

```sh
"$PANEL_PYTHON" -m pytest -v -s ops/pft_act080_core/tests
"$PANEL_PYTHON" -m ops.pft_act080_core.run --archive "$VOL2" --output "$NEW_DIRECTORY" --workers 18
```

`ReplayState.consume` is the shared per-stock entry for a single bar, an ordered chunk, or an entire chain. Preserve the in-memory state across chunks. The archive loader binds the raw ZIP, chain bytes, ordered observed sessions, and stock roster. The zero-based observed-bar index advances on coherent finite OHLC with nonnegative volume. Coherent historical negative and zero QFQ prices remain in the index and absolute W/Y/ATR calculations. A bar with any nonpositive OHLC cannot qualify. Price ratios require positive prices and bases. Missing or zero denominators return NA. QFQ adjustment PIT stays CANNOT_CONFIRM.

The three ACT-074 arms use returns relative to previous observed close, prior five-day return `C[D-1]/C[D-6]-1`, trailing three-bar high/low range, and D volume divided by the mean of the prior five observed volumes. EMA uses a first-close seed, Y requires 114 bars, ATR14 uses a first-14-TR average and Wilder updates, and KDJ uses a nine-bar RSV and K/D seeds of 50. ATR distance measures `(close-anchor_low)/ATR14`, W/Y opening measures `(W-Y)/Y`, W/Y slopes are one-bar relative changes, opening slope is a one-bar arithmetic difference, and upper wick disagreement measures `(high-max(open,close))/(high-low)`. A distinct arm yields one raw row. The earliest arm in A/B/C order represents the date. Later rows retain their qualification and receive DUPLICATE_SAME_DAY.

An episode opens at the first eligible day with no current wave. Its fixed Key K anchor is that day's low. A later close strictly below that low ends the episode before new qualifications are processed. The first raw representative is FIRST, the first qualifying B date thereafter is CONFIRM, and the remaining raw rows are REPEAT. The first released row of an episode has accepted role FIRST. A subsequent first released B-eligible date is CONFIRM. These roles leave the structural episode and same-stock cooldown independent. A duplicate never becomes a released row.

The feature table contains all candidate IDs and the released subset is identified by `accepted_flag`. CSV members partition the sorted rows in order and repeat a fixed header. An empty cell represents NA for the feature file. The split sidecar alone carries calendar folds and the 10-observed-bar boundary windows. An episode can have an assigned fold only in its origin period, and purge/embargo rows have an empty assigned fold. Split rows are outside the prefix proof because their left-side masks are defined using the finalized boundary calendars.

The combined JSON records conservation, per-stock and gap counts, feature NA, exact serial/parallel and prefix equality, file hashes, source validity and stage timings. The code digest concatenates top-level implementation Python files in lexicographic basename order with a `name:byte_length\n` prefix per file. The configuration has its own digest. An existing output directory is rejected. If a run fails after output creation, retain it for diagnostics and give the retry a new directory. A completed run has a final `CONSERVATION_AND_FEATURE_AUDIT.json`.
