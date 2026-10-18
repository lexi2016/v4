# R3 recommendation-count writer receipt

R3 now reports US_MAPPING counts on the full, de-duplicated HK candidate-stock layer. For the saved run `2e2a1dbb1312422c8b1e21a58d2d44d0` (snapshot SHA `388b4db4f4d46d7f926258ea872226243b9f121cd071e7ad6fb56aafb51cccbf`), the in-memory lane route reports 701 candidate stocks: strict selected 0, conditional watch 153, unassessed 437, and not selected 111. The default recommendation page remains 153 stocks with 50 shown per page.

The original 60 US source rows remain separately available with row counts 0 selected, 0 watch, 27 unassessed, and 33 not selected. The 1,003 catalog relations stay outside recommendation candidates. OVERSOLD still uses its existing row-based counts. The UI says “严格精选规则尚未启用” and shows the saved strict count, so zero does not read as a whole-day failure.

The R3 scope file SHA is `f87f41ccce7cd7dac600a74037e9b17bea1169e06f1456d0bb49804139db662e`. The five canonical source/test files and four R3 overlay files, with preimage and final SHA values, are recorded in `WRITER_R3_RECEIPT.json`. The local overlay also contains byte-identical API-R2 support files for direct Vitest module resolution and a `node_modules` symlink to the already-installed workspace packages; the immutable R2 API candidate and active services were not edited.

Validation passed: Python display/independent-recommendation suites (12 tests), Vitest on the API R2 overlay (4 tests), targeted `vue-tsc`, and an in-memory readback through the API R2 router using the exact saved run. The machine canary is `local_only/r3_actual_count_canary.json` (SHA `d1fb540203614d9ad72abfd3c7d6ebdfef83c6724e31fe0b53cdf8ee3fcc4182`). The full web typecheck reports unrelated, out-of-scope diagnostics in `src/api/managerWorkspace.attention.spec.ts` and `src/views/ManagerSelectionView.spec.ts`; no R3 file reports an error.

The saved `/days` response has separate merged-snapshot counts (0/153/548/0) and no `recommendation_counts`; the manager page binds the `/recommendations/{lane}` response. R3 changes that lane response to candidate-stock counts while retaining the old source-row breakdown. The canary is a local in-memory projection, not a live API or rendered-page readback. Root integration/activation and independent review remain pending; `LIVE_API_UI_READBACK=CANNOT_CONFIRM`, `INDEPENDENT_REVIEW=PENDING`.

No engine, qualification/PIT/BUY logic, source data, producer, active service, config, or scheduler was changed. No service action, job, release build/activation, API POST, commit, or push was performed.
