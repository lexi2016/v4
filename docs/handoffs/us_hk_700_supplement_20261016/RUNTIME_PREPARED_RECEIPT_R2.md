# Runtime candidate R2 preparation receipt

Status: **PREPARED_NOT_ACTIVATED**. The R2 candidate was prepared from the fresh plist-selected ZSXQ release and remains separate from the preserved R1 candidate. The active plist, active config, active release, services, scheduled tasks, and production permissions were not changed. No `launchctl` command ran.

## Fresh active identity and configuration

- Active plist: `/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist`, SHA256 `33df4ecc0cfaa8e574e99a73acdb14dd6c6587fe5deb9f2b15035746517293ce` (7970 bytes, mode 0o644).
- Active release: `zsxq-pdf-ocr-api-20261016-r1` at `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/zsxq-pdf-ocr-api-20261016-r1`, manifest SHA256 `3838f2784ee1b8fa197e8022be505e803f0d322b4788e9c209c1dc30d99f69e3`; full application inventory SHA256 `0f6636b790a92b6c5ceaba2482a60ca00f57700c2da21ca0a76c5dceaab678ee` with 1216 entries.
- Active config: `/Users/lexi/Library/Application Support/com.lexi.v4.local/config/oversold-nextday-recovery-20261015-r1.json`, SHA256 `f4bc5c37fb08d57766bf3cd596f9fe4abdc6c32a327e09bc99c5f555822c7158`. Its existing `relation_root` is `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/us-hk-mapping-finish-20261015-r2/app`; the new config changes only `relation_root` to the R2 app root.
- R2 candidate: `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/us-hk-mapping700-20261016-r2`, manifest SHA256 `f80879b7802ad683a734c64d011896031611bb0a9c249184b6feb54ca8c0ea80`.
- R1 evidence remains at `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/us-hk-mapping700-20261016-r1` with candidate manifest SHA256 `105a17529f35595a34b52a7589df23e6bafb1099de3e6072aeaddab1508094ba`.

## Exact runtime delta

The R2 integration contains six declared paths. Each before/after hash, size, and mode is shown below. The other 1211 active app entries were verified byte-identical; their inventory SHA256 is `051cd4d2111ccc23e223d20ab6c9eafc1e64b47ab18b37944ba063be7c9b7e90`.

| Path | Active SHA256 | R2 SHA256 | Size bytes | Mode |
|---|---|---|---:|---|
| `apps/web/dist/assets/managerSelection-CnQlnjWW.js` | `ADDED` | `002f4dbd045590dd13331a231de453d5d2e39c6f1282a2097af38f7f397fba59` | — → 73979 | — → 1204 |
| `apps/web/dist/manager-selection/index.html` | `a33757eceaef8e354076c5c02bf0dad04c0a6dc7b228b2539002a311c792ad7f` | `8a2d47ea8616e5b7f658bd150947bad7674cf9153ab559e8f33a297ff8d68a9e` | 588 → 588 | 1204 → 1204 |
| `apps/web/src/manager-workbench/Workbench.vue` | `8c66ebe4d63db69495eb2442f65e1236bf62d2e1587083edc4342969b7154794` | `02c22f03ee9d240d22d008d15f16878b986674e7886ab68487cbebe14b826320` | 54869 → 56093 | 1204 → 1204 |
| `apps/web/src/manager-workbench/types.ts` | `9dfde62ac4342cb10d9ff20fe0bd20b0c188c9e5200fd972438d4fa89658fe49` | `543eb656a86519a6bf45849e55fa9251fbd48064d07082cbbe2b31727db13542` | 13887 → 14041 | 1204 → 1204 |
| `v4/manager_workbench/research_data/us_hk_667_review_overlay_20261015.json` | `72a0f074e6412036cd103c7f73ccf15230eb3d1633c09742c88653b863eba384` | `d45d44fb074fc82923a0af5e37a8d645923a84acb48dc2bb1794b1f4ddc98c69` | 19580826 → 66687594 | 1204 → 1204 |
| `v4/manager_workbench/us_mapping_catalog.py` | `8d881796f845787cd0abb4840a4da8f717caf73f12f764e9d5b5fc8fc1894a04` | `b7ec08a65a9bb6e2ee419caf303c5ec60b809a44b7a2bef42883ea0fed4023ad` | 18970 → 23977 | 1204 → 1204 |

## Reused R1 source/build evidence

- R1 delta receipt SHA256: `4ca811585ee43d8d60fe4913b69eae5908fecf4a1706cb1b79a6e2f9737800e8`; R1 candidate manifest SHA256: `105a17529f35595a34b52a7589df23e6bafb1099de3e6072aeaddab1508094ba`; R1 independent review file SHA256: `92b6566bc7cdb888eb7fd54159df7ab4a2711dd1a01842f1cfb621142b8e829c`.
- R2 active module, Workbench, types, overlay, and manager-selection HTML preimages match the R1 base SHA256 values exactly. `git apply --check` passed against the actual R2 base.
- The manager-selection build inputs (`package.json`, lockfile, Vite config, TypeScript config) and baseline manager-selection entry/assets match R1. The only web-tree differences are the seven separately preserved research-lane/main paths recorded in the R2 preparation receipt, so R1's reviewed manager-selection JS/index outputs were reused by exact SHA256. No Vite or Vue typecheck was rerun.
- The 66,687,594-byte overlay's R1 unified-diff proof was reused only after exact before/after content SHA256 checks. The R2 base and candidate inventories, each changed file's before/after SHA256, and all non-delta entries were freshly recomputed. The standard API-release candidate verifier passed with a local fast path that reused this one exact prior proof; the general release helper was not modified.
- Targeted candidate API check: PASS; 667 stocks / 1003 relations; 700 source-reviewed / 303 unprocessed / 0 independently verified; `R001/FULL` and `R700/NOT_PROCESSED/SUMMARY/null`. The test used the R2 app as import root and the R2 config path.

## Staged config and rollback identity

- New config: `/Users/lexi/Library/Application Support/com.lexi.v4.local/config/us-hk-mapping700-20261016-r2.json`, SHA256 `7a6d9689df73f832e15efd53923ab69d03ebc4f0357635bb8d9e67d6342e35b5`, mode `0o644`. All values except `relation_root` match the active config.
- Staged plist: `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/us-hk-mapping700-20261016-r2/config/com.lexi.v35.api-only.plist`, SHA256 `578c5bed8e6465a1f7b2b409c88a8ec2dcf7358efb3ea111cd31e077310aa5d8`. It changes only release/config selectors and working directory; launch label, port, KeepAlive, RunAtLoad, other environment entries, and non-selector arguments remain unchanged. Verified changed selector keys: `V35_APP_ROOT, V35_RELEASE_ID, V35_RELEASE_MANIFEST_PATH, V35_RELEASE_MANIFEST_SHA256, V4_MANAGER_WORKBENCH_CONFIG_PATH`.
- Rollback preimage: `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/us-hk-mapping700-20261016-r2/config/active-api-plist.preimage`, SHA256 `33df4ecc0cfaa8e574e99a73acdb14dd6c6587fe5deb9f2b15035746517293ce`, byte-identical to the current active plist.
- Fresh pointer/config checks passed before candidate integration and after candidate verification. The new candidate is not activated.

## Commands and verification

- Prepare: `PYTHONPATH=. .venv/bin/python docs/handoffs/us_hk_700_supplement_20261016/prepare_runtime_candidate_r2.py`.
- Candidate API checker: `/Users/lexi/Desktop/学习/v4_app/.venv/bin/python /Users/lexi/Desktop/学习/v4_app/docs/handoffs/us_hk_700_supplement_20261016/check_runtime_candidate_api.py`; working directory `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/us-hk-mapping700-20261016-r2/app`.
- Candidate verification: `verify_api_release_candidate` returned `PASS` with exact R2 base identity, six deltas, and full non-delta inventory proof; the large overlay unified-diff calculation was reused only for the matching content SHA pair.
- No activation, API switch, commit, or push was performed.

`CANNOT_CONFIRM`: live API/UI behavior under the R2 candidate, natural-time results, independent semantic facts, prediction, historical PIT, and a future R2 activation/rollback. A fresh independent R2 review is pending.
