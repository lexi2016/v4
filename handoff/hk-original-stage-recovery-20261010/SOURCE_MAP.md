# Earliest-known HK Stage source map

Evidence assembled 2026-10-10 for the bounded 20261009 original-path canary. This is provenance for reuse, not a claim of publication, live acceptance, or an absolute earliest run across unsearched history.

## Earliest known outputs

- Earliest successful Stage output record located: 2026-09-15 `STAGE_1545_1555`, run `run-399c46b9fb5bc9ee937fe234`; 16 source rows produced 10 selected. Receipt records `algorithm_sha256=fa010779e194b06ee9a77799d6b41a8d76a641a047b05b96c4594766e4497506`, route `hk_connect_stage8_natural_rtd_data`, source `FUTU_RTDATA_NATURAL`, and the natural 15:45–15:55 window. Exact activation/source-file binding for this 2026-09-15 run: **CANNOT_CONFIRM**.
- Earliest full-day output set located with a loaded Stage release binding: 2026-09-21. The set includes recovery and natural outputs; it is not an all-natural claim. At 09:30 recovery, 100/100 source rows produced 10 selected, but the Futu active snapshot arrived at 11:27 after the 09:35 cutoff, so it is not cutoff-safe natural evidence. At 15:45, the natural Stage 8 path recorded 23 requested/completed and 10 selected.

## Loaded Stage release and selection path

- Loaded Stage app root: `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/20260921-pools-acquisition-stage/app`.
- Release manifest SHA-256: `38a499562df4f6477d6fb5d530f26d5b485fc4990f68eb64eb77f6b8bd178826`. The deploy reviewer receipt binds launchd's loaded app root, release ID, and manifest SHA.
- Loaded runner: `ops/run_stage_center_nodes.py`; config: `stage_center_tick_config.json`; working directory: app root. Runtime: `/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python`, Python 3.14.6. Loaded config SHA-256: `5a90b819e8c7342430e18a58d6472d7b96fe829078b98df26cec6eb778aa7c37`.
- Selection source: `stage_center/selection.py`, SHA-256 `31e80e068890be03957920870719030463262c78911953541be3074f8650d4c9`. Its computed algorithm SHA matches the receipts above. Contract is exact-date D-1 `prob_active` Top100, four-lane scoring, stable Top10 truncation, research-only / NO_BUY.
- The 2026-09-21 fixed D-1 input is `/Users/lexi/Library/Application Support/com.lexi.v4.local/state/data/preselection_pools/20260921/hkconnect_d1_top100.json`, SHA-256 `3a909c06b9df0dd10dc1f54fa023237d61a39a5c16730558a4e4d6c38a39aa6c`; 100 rows, producer `v3_shared_hk_0_2_consumer_v1`, source run `20260921-hk-connect-d1-top100-0-2-b04132054578`, source SHA `acfa5dda39cdaa9500ae809e2fc36ed2e1eb62ce719c59ebf014be3663a5a872`. The source artifact's recorded relative path is `runs/20260921/HK_CONNECT_D1_TOP100_0_2/<run_id>/artifact.csv`; its exact local resolved path: **CANNOT_CONFIRM**.

## Daytime collector and runtime inputs

- Stage collector: `stage_center/live_collectors.py`, SHA-256 `6c2c623f1d86d24a2c62652c11e4d8fc9248920728b5c7e93a2ee848a735fd1c`. `collect_hk_minute` dispatches the requested explicit D-1 code list to `scripts.live_acquisition.pytdx_exhq` and refreshes the Futu active-lane observer for the same codes/cutoff. Receipt route: `shared_pytdx_exhq_hk_exact_d1_top100`.
- Loaded config fixes the HK universe to `FIXED_D1_TOP100_ONLY`; shared data root is `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/20260920-manager-r2-stage-research-consumption-candidate/app/upstreams/v3_shared_data`. Raw, selection, and receipt roots are under `/Users/lexi/Library/Application Support/com.lexi.v4.local/state/stage/{raw,selection,receipts}`.
- PyTDX wrapper SHA-256 `19946fd9c09033a77b460fe5a68f70969623d3b1c26f058091349e702d482fdd`; probe SHA-256 `9ce612fb06f022601841828bb25d11d1850cd4e3ab09de775babd56f7b8d0399`. The wrapper starts `scripts.live_acquisition.pytdx_exhq_probe`, batches up to 64 codes, timeout at most 180 seconds. Probe uses TDX ExHQ market 71/category 7, 400 bars, in-window aggregation, and no cache.
- Futu observer source `shared_data/hk_auction_0920.py`, SHA-256 `c1d2df6e1712b4ce16c673ef4313b23936925f50a1ea2aa9932f6b01bd08685e`; it requests explicit D-1 codes (not a plate). A late Futu snapshot degrades to PyTDX observation and is recorded as degraded.
- **Import-byte caveat:** the configured shared-data release manifest is `PREPARED_NOT_ACTIVATED`. Its PyTDX/Futu files match copies in the loaded Stage release inventory, and the Stage config points to it; however, the run receipt does not record imported module hashes. Exact per-run imported module bytes remain **CANNOT_CONFIRM**. The main loaded Stage release and selection implementation are bound by manifest/deploy evidence.

## Cleanup receipt

Root reports the writer's isolated cleanup receipt SHA-256 `5ed92add2c3f2514b4891b8dddb03de6a2da7031fb63e2a39d21ab19666af040` as verified. This reviewer did not independently recompute that receipt hash.