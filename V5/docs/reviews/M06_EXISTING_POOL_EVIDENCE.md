# M06 existing-pool evidence summary

**Status: REVIEWED / BEHAVIOR_VERIFIED for existing-input replay only.** This is a bounded replay of an existing recorded input. It does not establish full M06 completion.

## Fixed base and minimal change

- Repository branch: `v5/module-isolation-20261008`
- Fixed base commit: `835cd6dab3765ae9b8579560747fa47ad5bce7e7`
- `V5/src/v5_shadow/hk_preselection.py` before the local repair: SHA-256 `afb2782626ae7969680f9a3509a05cd0b0b010d32181427481be8f8098d7c29e`; Git blob `b7610ace643ab8e02da858021939a9c2d98b8601`
- Local repaired file: SHA-256 `00ccdaa1890675335836351d33c4fea5f9458a8dd287e3724efb9f0cb0fb1b21`
- The adapter now supplies `kind='v192'` and `paths={}` to the shared read-only guard. The V192 kind declares no named paths; the guard continues to authorize reads from the unchanged declared file map. No algorithm, data, or trading gate changed.

## Existing input identity

- Dates: target `20261012`; signal `20261009`; eligibility source `20261009`.
- Input inventory: 8 declared files. SHA-256 of the sorted relative-path-to-file-SHA inventory: `767bedb001c64637664182bfecb099930bac87581a042501117dc7d552f543cd`.
- Pool artifact / manifest / receipt SHA-256: `738ffa6533bfc1e041a3cd84841d591f0ee6bda53fe8fe420cf608b9a7f3503d` / `20fb5182d751e75beb80b8c97c42eba4b1d1660084b321d8a69d9ed877f9c571` / `01d4b09fb76b6e2d1135822a088e963d33356a2b0cf432d9af646ac5e2073da9`.
- Security-master artifact / manifest / receipt SHA-256: `2726ae16fc3718a8b5cfb5eda0434f52efc72fd4434d0d244f6244ed1bd65f36` / `22a7c650de263af0e7d860d6dc744065190c307b9aeceede55b0870f4e5b073e` / `0f9ffe3b2a7a58a567af94ed55740552c44357c502e5b7ff37bfb98f4f879596`.

## Verification results

- Before the adapter repair, the pinned source run had 15 tests with 13 errors and exit code `1`; the common cause was `KeyError:'kind'`. The original RED log is retained locally.
- After the repair, the HK preselection test command completed 15 tests with `OK`, exit code `0` (Python `3.14.6`). The recorded command was `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=V5/src python3 -B -m unittest discover -s V5/tests -p test_hk_preselection.py`.
- On the same recorded input, the frozen owner reader returned `READY` with 100 rows and its builder returned `STRICT_0_2_READY` with 100 rows. V5 returned `ASSEMBLED` with 100 rows. Rank order was 1–100 with 100 unique symbols.
- Owner and V5 code-order SHA-256 matched: `8e0bfc5a5c5be1b35372d1434558c5c518ce82e04325ee0ce61077c802b55787`. Probability-text-order SHA-256 matched: `7c13d93dddd017711d83d2d716978be5bc225004eaf9bf8a9aa0f4d5311567ba`. All 100 V5 `pool_score` values numerically matched the source `score_prob_active` values. Neither reader rejected this input.

## Boundaries and remaining work

This replay used an existing pool and master; it did not acquire data or read the source panel or model weights. Formal eligibility and model-weight re-verification remain false. Unsupported `eligibility_universe_root` and `research_name_supplement` arguments remain rejected. Research-only flags remain set; production is disabled; no BUY gate or orders changed. Natural execution and new-pool production were not tested. Independent review passed on the final adapter SHA recorded above.

Independent reviewer reran `python3 -B review/replay_m06_review.py` with Python 3.14.6: exit 0; its fresh test run passed 15/15, exit 0, and same-input owner/builder/V5 comparison passed all 100 rows. Review receipt SHA-256: `b3226a3e48c5d5dec250bdabd9f1d32b972a9cc5b09c1adb9c2898158a593dbc`; test log SHA-256: `21a5ea824b5559e7c87a6ccba0b9906f737381618d4ac99137da34b43b0fdb56`. The initial reviewer harness rejected the declared-patch snapshot status; that failure is retained locally, and the corrected harness verified all 85 source files plus the exact local patch without relaxing SHA checks.
