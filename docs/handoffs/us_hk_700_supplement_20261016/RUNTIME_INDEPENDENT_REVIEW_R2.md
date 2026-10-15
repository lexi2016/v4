# Runtime independent review

Reviewer: `mapping700_review` (independent from `mapping700_writer`)
Candidate manifest SHA256: `f80879b7802ad683a734c64d011896031611bb0a9c249184b6feb54ca8c0ea80`

REVIEWED=PASS — the R2 base, delta/preserved inventory, activation-path binding, and focused regression evidence match the frozen candidate.
BEHAVIOR_VERIFIED=PASS — R2 candidate-only API behavior passed the exact in-process readback; live API/UI and natural-time behavior remain unverified.

## R2 base and artifact identity

- Active plist remains SHA256 `33df4ecc0cfaa8e574e99a73acdb14dd6c6587fe5deb9f2b15035746517293ce`, bound to release `zsxq-pdf-ocr-api-20261016-r1`, manifest SHA256 `3838f2784ee1b8fa197e8022be505e803f0d322b4788e9c209c1dc30d99f69e3`. The prepared rollback preimage has the same SHA and is byte-identical to the active plist.
- R2 candidate manifest SHA256 is `f80879b7802ad683a734c64d011896031611bb0a9c249184b6feb54ca8c0ea80`; R2 config SHA256 is `7a6d9689df73f832e15efd53923ab69d03ebc4f0357635bb8d9e67d6342e35b5`. The only active-to-candidate config value change is `relation_root`.
- The R2 staged plist SHA256 is `578c5bed8e6465a1f7b2b409c88a8ec2dcf7358efb3ea111cd31e077310aa5d8`. R2 prep and cutover-plan identities bind the active plist/config, ZSXQ base manifest/inventory, R2 manifest/config, delta receipt, staged plist, and rollback preimage.
- Independently recomputed base and candidate inventories match their release manifests: 1,216 base entries and 1,217 candidate entries. All six declared delta entries match their before/after hashes. The remaining 1,211 entries match by path, file hash, mode, and size, and their inventory digest matches the preparation receipt. No overlay diff or full mapping-data audit was repeated; source/build review evidence is reused from the unchanged R1-reviewed inputs and exact recorded SHA pairs.

## Candidate behavior and R2 entry

- Re-ran `check_runtime_candidate_api.py` with the R2 app/config paths. It passed with 667 stocks, 1,003 relations, 700 source-reviewed, 303 unprocessed, and 0 independently verified. Exact `R001` is `SOURCE_REVIEWED` / `FULL` with both new evidence keys in the evidence row; exact `R700` is `NOT_PROCESSED` / `SUMMARY` / `null`. The research-only safety flags passed. This is an in-process candidate check, not a live-service readback.
- R2 entry wrapper SHA256: `4f0665f1c0595bc671a45d2294cb85638cbd71cc901d53f0f59d4340841ccae3`; shared activation core SHA256: `25e72ccf9034663dcc9e1d8a14c54ccda9a4b74009dd3152a3f4537eef1d078a`; R2 binding test SHA256: `fd69dd0b2eb76026fbcd333f54fd50890c4a8d1988ea7d54998e82d1d22eb6e2`.
- The wrapper binds the shared core to the R2 candidate, config, plan, staged plist, R2 rollback preimage, and distinct `runtime-activation-receipt-r2.json` path. The core's receipt writer uses `ACTIVATION_RECEIPT_PATH`; a mocked cutover test verified it writes only to a pytest temporary path and leaves the R1 receipt and active plist unchanged. `activation-entry-receipt-r2.json` (SHA256 `bd1e6956ee4e38289d9f92544dc4a2798388ce78bb5fb8fb706eced2cbdcc8cd`) records the binding test result and dry-gate result.
- Re-ran both focused activation suites: `PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH=. .venv/bin/python -m pytest -q --basetemp=/tmp/v4_mapping700_r2_runtime_review_20261016 docs/handoffs/us_hk_700_supplement_20261016/test_activate_runtime_candidate.py docs/handoffs/us_hk_700_supplement_20261016/test_activate_runtime_candidate_r2.py` — **14 passed**. Re-ran the R2 entry without activation flags; it returned `PREPARED_ONLY` and `launchctl_called=false`.
- After these checks, the actual active plist still hashes to `33df4ecc…`, equals the R2 rollback preimage, and neither the R1 nor R2 activation receipt exists. This review did not activate or call `launchctl`.

No P0/P1/P2 findings in the frozen R2 runtime scope. `CANNOT_CONFIRM`: live API/UI behavior under R2, natural-time results, independent semantic fact acceptance, prediction, historical PIT, and real activation/rollback behavior.
