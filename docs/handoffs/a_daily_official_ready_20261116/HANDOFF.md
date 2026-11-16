# A-share official daily source timing

The R2 Main runtime scheduled A at 15:40, 16:10, and 16:40. One natural run and its retry started before the same-day TDX file was ready on 2026-11-16. The 16:10 attempt obtained the official dated ZIP by 16:10:21 Shanghai time. The 11 official dated ZIPs observed for trading sessions on November 2–16 each carried an HTTP Last-Modified header of 16:10:06 Shanghai time. The observations describe those objects. The official documentation gives no fixed minute for the dated incremental file.

This overlay removes only the A workload's 15:40 slot. The 16:10 dispatch may start with a missing exact dated A receipt or the existing verified prior failure. 16:40 continues to require the existing verified prior failure. A corrupt, wrong-date, symlink, or nonfile receipt cannot authorize the first attempt. The existing exact completed-receipt reuse path is retained. The direct wrapper starts A at 16:10 and treats both its new waiting status and the historical waiting status as a successful no-op.

The existing source owner allows same-day acquisition from 16:10. Its first uncached GET waits for 16:10:15 when necessary. Verified cache reuse, two attempts with the original two-second retry pause, and the dated ZIP validation are retained. The cutoff includes a buffer after the observed headers. The A source policy file stays byte-for-byte identical because authenticated lifecycle receipts for 301139.SZ compare its complete hash. The catalog and actual owner enforce today's timing.

The patch restores over exact `v4-single-panel-daily-20261116-r2-main` application bytes. Check the role manifest, exact policy SHA and each of the four file identities in `OVERLAY_INVENTORY.json` before applying it to an isolated future release. Restore the four preimages from that manifest to reverse the source candidate. HK and close workloads match the R2 catalog byte-for-byte after excluding the one A slots field.

The focused replay tests restore the exact patch over frozen R2 bytes. They exercise the catalog, the bound policy SHA, the actual source owner with an injected clock and existing valid ZIP fixture, the existing executor gate with exact receipt cases, and the wrapper. Fifteen cases passed. Use the absolute project `PANEL_PYTHON` and an isolated test directory.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  "$PANEL_PYTHON" -m pytest -q -p no:cacheprovider \
  tests/test_a_daily_official_ready.py --basetemp /path/to/isolated-pytest
```

Source candidate only. Independent acceptance, installation, and natural operation of this candidate are separate.
