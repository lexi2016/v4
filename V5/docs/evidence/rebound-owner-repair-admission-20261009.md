# Original-owner repair and admission candidate evidence — 2026-10-09

- Repository/source root: `lexi2016/v4`, `/workspace/v4`.
- Branch: `v5/rebound-owner-20261009` only; no merge, deployment or main/master writes.
- Original development baseline: `2719328494a9ec3177a7be56e7348f86dd0137f5`.
- This increment baseline: `2d8e38ec61792b3e75581f96318e9c284f72b7ba`.
- Code/doc/test commit: `0afaed3697eb38aa351f99ed5a9036587bb108e1`.
- Cloud static interpreter: `3.12.14`; no product imports or tests executed.

## Actual validation status

PASS: AST parse and compile without execution for the changed Python files, frozen decoder and two embedded Mac scripts; JSON parsing; exact canonical decoder bytes against read-only fetched commit `74478a0e62be215c8527ccc9a14b89b51042d014`; original updater, original numeric owner and lockfile SHA pins; staged `git diff --check`; allowed path/branch review.

New Mac candidate test methods: panel repair 26 (24 synthetic + 2 opt-in real owner), raw decoder 22, admission 20; 68 total. All new product tests **NOT_RUN** in cloud. Existing observation regression remains required. Parent-reported prior 2d8 recovery25 + daily11 = 36/36 single Mac PASS, 550 source files unchanged, applies only to the prior increment. It is not selection success or a test result for this commit.

## Delivered behavior and boundaries

- Original HK02 updater wrapper shares the original asset root and writer lock; normal append delegates the original function. Internal native or explicitly mapped stored PyTDX raw gaps use the original parser/decoder and enrichment, strict historical prefixes, immutable revision/receipt, parent CAS, readback, exact old-value/key checks and idempotent recovery. No cloud publication occurred.
- Original frozen 60-session price / five-full-session mean comparisons are unchanged. The new financial admission path checks 67 exact cells, whole six-day volume unit/scale, raw/source/document/decoder identities, real acquisition/availability, calendar completion, price basis and target-date membership. Only a proved code receives scoped `OWNER_VERIFIED`. Unknown unit, incomplete proof and missing members stay refused/pending. No amount, capital, market-cap, listing-date or lot-size gate was added.
- Manager validates the ledger-readback payload, target coverage, grouping, integrity and evaluation time before its cutoff. No new scheduler/ledger, manager/worker/UI/archive changes, collectors, trading or credentials were added. Main branch integration consumes the existing shared ledger.
- Trusted deployment pins are independent of request/evidence writers. A request cannot authorize itself by supplying its own digest. These are not cryptographic signatures against a compromised owner process.
- The original full-master owner is not marked complete; natural verification, production and BUY/order changes remain false. Old observation artifacts remain readable; new admission requires the current implementation.

## Real evidence still missing / current Mac facts

- All 2671 planned missing rows in the 695 native files were NOT_PRESENT. Cache 10/5 and 10/6 each covers 692 targets; 10/7 known post-close sample only HK00001. The raw adapter is bounded to explicit available keys and does not fill absent history.
- Mac sample raw SHA `0f45a1f19a0882e2c96ff0c2c0d94d8cabcd26f7305dc0c1e292130c35de5ddf`, HK00001 trade 45276/38090/47348 on 10/5–7, actual 2026-10-07T22:07:41.136988–22:07:41.160969Z. Cloud did not receive this file. Its exact record pointer and original request/response fields still need Mac readback; no guessed envelope is accepted.
- Current native manifest SHA `a9c75b248d264e2ed78532cbfc1004f8de97b8e8f91c587a66b50f5afa020bee`, panel SHA `785212e96f9f088075800f55dfaf09ef83fccdde7c220e24f9f14d8808db5f90`: `NEW_INCREMENT_ONLY`, trade_v uint32_le offset24 scale1, unit null/NOT_PROVEN. Its read_started/read_completed times are file reads, not provider capture. No all-six-session proof follows from them.
- Mac quota receipt `74f9a1e38a01691a0f9942df2fc35b490b3c86fb180cd7506ea45767b5e806fc`: one query at 2026-10-09T16:33:41.158289–16:33:41.165456Z, ret0 used99 remaining1; 96 details, 93 target codes. Keep this discrepancy. OpenD was healthy; first asynchronous script cancelled connection. Historical requests0; 694 bulk HOLD.
- Actual clock observed 2026-10-09T16:46:03Z = HK10/10. Existing CURRENT contract cannot newly claim target10/9. Isolated historical repair is available; historical selection consumption needs an explicit replay contract, no clock rollback.
- Parent must install the new reader before activating writer, ensure every original writer uses its lock, and retain repair evidence through later normal-append parent chains. These integration/deployment steps are not done by this branch.

## Mac handoff

From repository root, using its existing locked Python >=3.14 environment:

```sh
PYTHONPATH="$PWD/V5/src:$PWD/V5/tests" "$PY314" -B -m unittest \
  test_rebound_panel_repair test_rebound_raw_repair \
  test_rebound_admission test_rebound_observation -v
```

Opt-in original-owner validation: `V5_REBOUND_REPAIR_ORIGINAL_TESTS=1`; native real asset-copy case additionally `V5_REBOUND_REPAIR_REAL_INPUT=/absolute/path/binding.json`. Complete native/raw request, authority and manager/shared-ledger interfaces are in `V5/docs/REBOUND_OWNER_REPAIR_ADMISSION_20261009.md`. Real raw repair must first use a complete owner asset copy with actual SHA-bound inputs; it cannot inherit synthetic fixtures as proof.

## Before/after raw SHA256

| Path | Before | After |
|---|---|---|
| `V5/src/v5_shadow/rebound_observation.py` | `ecf2473791bddea11ac307472a0564193518fb121e15eaf17d7e6a2ff4e8041b` | `15845f00a98e60e2b028e20749b8c6fe2822a0b235061da00e85763a9552668b` |
| `V5/src/v5_shadow/rebound_panel_repair.py` | `ABSENT` | `1fa7d530b7b1fe7190a0e33990c82e0d26292a6c98f02d72dc942b455bd6ac94` |
| `V5/src/v5_shadow/rebound_raw_repair.py` | `ABSENT` | `0c6236be65fb52c78b04c124dad90b0d5413c41d78e00bc00d73f1706e1985cc` |
| `V5/src/v5_shadow/rebound_admission.py` | `ABSENT` | `483ff3d575d6bc6751547225c87e523ae20de91453afb921aaa6ea6755549805` |
| `V5/tests/test_rebound_panel_repair.py` | `ABSENT` | `a62bdb06d40532d14ad4634eb92bc71480772170bde427af56bf9ce52dc9379e` |
| `V5/tests/test_rebound_raw_repair.py` | `ABSENT` | `3bec218c947716f099ce85b7a71303e1b051d8f0e09b2b0d9f88384c50c792a3` |
| `V5/tests/test_rebound_admission.py` | `ABSENT` | `ecf4f5bc75fb1c01b547d39e551cf672304a7470a9210c0317a946f137c1c61e` |
| `V5/contracts/rebound_repair_source_manifest.json` | `ABSENT` | `057a2c453ae562bc94564829dd8f78aba2b303bb7182a0b493fde9d4bedbafcd` |
| `V5/vendor/rebound_repair_baseline/hk_daily_supplement.py` | `ABSENT` | `fa7dcbce4ee026b0a02c47220820d0407af183553d3304afcc5db425dce33cbd` |
| `V5/docs/REBOUND_OWNER_REPAIR_ADMISSION_20261009.md` | `ABSENT` | `e5371b668f2d6568c62ed953b5eefc4fc7fa298927cf6c893559123500cf4c90` |
| `V5/docs/evidence/rebound-admission-candidate-20261009.md` | `ABSENT` | `e08cf97e9d6212844b354e576ec6288cea2f163392f06fe2d48a57191e1bcb04` |

Frozen sources remain unchanged: original updater `27da90f0e623e45fa1a27af7dcc3b6e5e1ff2320bae1c61bd903ed82050beb89`, numeric owner `be0d5e69ff72efd07d2caca4e68948245db4900a8c41f467e9c30f6899c044b1`, lockfile `7cb690f890cc28b6a79311f07e724f61c3dc4411494d480c0041f075f0825bfd`.

This evidence is committed separately after the code commit. The final handoff reports the resulting branch commit and remote per-file readback; this file does not claim a push before it has occurred.
