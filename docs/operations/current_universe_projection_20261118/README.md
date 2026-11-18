# V4 current-universe projection patch

This patch applies to the combined Main source after the reviewed retention delta is applied. It filters only exact current snapshot entries whose `original_quarantine_eligible` record has `classification == QUARANTINED`, `quarantine is True`, `target_date_ready is False`, and `reason_code` equal to `VERIFIED_BSE_OLD_CODE_REPLACED` or `VERIFIED_DELISTED_NO_CURRENT_BARS`.

The product-only export patch SHA-256 is `ac634f800504cf85d5917e05b74ca51d8294c3a4e62f0ea826984b452179fb5b`. It applies to the exact combined Main daily-product preimage `e23fd1ecb7e1d7964f3f24526413398266085a2b779d20a42da02a0079405aa0` and produces `31befa8372d2b54dde4249b8ff5e08b455e049d4346295dfdb35a3f34869e5cc`. Apply this zero-context export only after verifying that preimage, with `git apply --unidiff-zero daily_active_universe.patch`.

The D18 bound snapshot witness is generation `54f9474006c480a47303c18e4b2fd9a22132609cf44f229de63c68cb7d8a37a0`, snapshot SHA-256 `d98b51c1ef798ad662f775e86c5db2d5428af8088c31f0e70c2cc30748031fed`: 5,842 original target codes, 5,580 active, and 262 excluded (232 old BSE codes, 30 delisted). Eight other eligible records remain in active scope.

Run the focused regression against an installed candidate source with the Main Python runtime:

```sh
V4_DAILY_SCOPE_TEST_APP_ROOT='/path/to/candidate/main/app' /path/to/v4-mac/bin/python -B tests/test_v4_current_universe_scope.py
```

This overlay changes only the numeric daily product projection and its product/manifest exclusion summary. It does not edit the source snapshot, selector/backtest kernel, historical product versions, or sealed D18 artifacts.

The prepared r2 bundle in the local candidate directory still contains an earlier Workbench host passthrough delta and is marked not deployable by the controller. This product-only patch is the corrected source overlay; no replacement full release was built in this change.
