# Day25 STAGE_0930_0935 missing-field evidence

Prepared 2026-10-05T10:13:35+08:00. Target 20260925; D-1 20260924; cutoff 09:35:05 Asia/Hong_Kong.

`fields_by_code.json` SHA-256 `11e256bec4ee181f956bb2792260290b1e2b5784a9838ebef91b3074eebbcc3e`; CSV SHA-256 `d02371d0d8fdb28fad944bc0881943ba1deb4899bf57b11f9a4f3d1adb6a7546`; receipt SHA-256 `1d1d6cbd74aff12d48cfa250551430ec8e7a046075a8769438c93e974375996a`.

Prev-close coverage is 19/19. Numeric last-price label coverage is 15/19; 12/19 have positive-volume evidence in the window, 3 EastMoney values are reference-only because all five window rows report zero volume, and 4 Yahoo codes have no valid complete positive-volume OHLCV row. `last_price`, `prev_close_price`, and `pct_chg` are derived research-projection keys only; `pct_chg` uses `(last_price / prev_close_price - 1) * 100`. The D1 pool prior-day `pct_chg` is not used.

Yahoo turnover is unavailable and not inferred. `volume_ratio`, `turnover_rate`, and free-float shares remain CANNOT_CONFIRM. The master policy is OUTSTANDING_SHARES_X_CUTOFF_LAST_PRICE; cap arithmetic remains a research scenario because the field mapping and cutoff-safe last price are not confirmed.

Minute capture occurred after target cutoff, so data is NOT_FORMAL_PIT. That alone does not decide use in the existing historical observation lane; source/owner contract review is required. No publication, stage rerun, active-store write, source/config change, or Futu request occurred.
