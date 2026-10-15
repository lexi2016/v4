# 2026-10-15 HK pool / A-name bounded repair

Source root: `/Users/lexi/Desktop/学习/v4_app`. Local baseline commit: `55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054`. Delivery base: `c66717a7602367a30dc4d8719c71043915b2071d`, branch `codex/hk-pool-a-names-20261015`.

The previous evening HK Top100 READY input existed, but the legacy deployed preselection materializer aborted before publication when an optional A fupan CSV raised UnicodeDecodeError or csv.Error. The canonical source already had optional-artifact isolation; the active legacy release did not. The 09:00 hourly research job was not an HK producer. Yesterday's available input and manual close recovery do not prove the whole automatic pipeline was healthy.

The existing HK_CONNECT materializer restored today's exact-date 100-code pool from the original READY source once. No new acquisition or parallel producer was introduced. Original source artifact/manifest/receipt and A pool bytes were preserved. Independent input verification passed; this manual input restoration is not natural publication acceptance. Today's pool artifact SHA is `66225363e4dd1b9da4f316d75a8dcc5f249bc0968128c646e9632a1a8b1b1c67`; source run is `20261015-hk-connect-d1-top100-0-2-1d08535262fd`.

The A-name reader now isolates missing/invalid individual pools and uses verified same-date names from the valid pool. Shared-root/manifest/safety errors still fail closed; conflicting names remain unconfirmed. Names are applied to response copies only. Missing/isolated pools and partial authority retain explicit CANNOT_CONFIRM metadata. R1 failed review on missing explicit uncertainty metadata; R2 addressed that finding. No selection code, score, rank, algorithm, market/date contract or BUY gate was changed.

## Active research-service identity

- API: `a-stage-names-api-20261015-r2`, manifest `5395e1bbea0c8f29b7bd5eed580589a9d78f6c9562ba2932320ce4237f8f1989`, activated 10:34:29 +08. It inherits the independently accepted D-1 WECHAT parser fix. Only its runtime consumer delta changed; 1174 other app files were preserved.
- Daily scheduler: `hk-pool-fupan-isolation-20261015-r1`, manifest `bb33fae99d6c111fc72d73540510962b4d5153b187386c44ca39a02efe25648b`, activated 10:21:26 +08. Only the existing materializer's optional A fupan guard was ported; unexpected ValueError still fails closed.
- Independent stage scheduler: unchanged `node-minute-stage-20261014-r1`, manifest `9218888255e513840e25d1e16cebd0da1d5976f39e33a0fa0f5785461dfd8e13`.

## Validation and limits

macOS, project `.venv/bin/python`, exact inactive-release imports with `-B`/PYTHONDONTWRITEBYTECODE. Independent Reviewer reran A-name focused tests against canonical and candidate: 19 passed each. HK regression: `.venv/bin/python -B -m pytest --basetemp=/tmp/v4-hk-fupan-validation-20261015-2 -q tests/test_hk_preselection_optional_fupan_isolation.py`, 4 passed; independent legacy reproduction and candidate checks covered invalid UTF-8, CSV field limit, missing optional file, and unexpected-error fail closed. D-1 parser fix had independent 12/12 tests and refreshed UI verification.

A R2 preactivation reviewer receipt SHA: `637b25d31e7077a2808474bd2c75fa3bdbb8d7fbdf5b802dbf295d9f13e42c54`. HK guard independent receipt SHA: `ea9c81e005cbb8499ad6dfd102874b7162f13f54b85d872830bf6e999479014e`. HK input reviewer receipt SHA: `1a44697555aed878cfaa3f7849686ec42d172de07a2f2daba1dc1d83b99822df`.

At the natural 10:30 slot, HK run `run-e3edc8cdd02d17ebd94311e0` consumed the exact Top100 input, produced 10 observation rows, and displayed them through API and refreshed 8873 UI. Stage receipt SHA: `98c6be6e8da4214cd9fb6b93859293c2785e73488c2021c67672ec32f148e1ce`. Independent operating review SHA: `1c64c3c5a0cab9175cc1b25ef3327d1f55d67fdabe44b29fde8ea92d3589c65b`. The 10:29 full scan covered 100/100. Deterministic replay reproduced all 100 minute rows with 09:46–10:29 bars, excluding post-cutoff bars. Raw capture completed 10:31:03 and contained bars through 10:32; that timing caveat remains. All 10 HK rows remain formal_eligible=false, NO_BUY/WATCH_ONLY. UI execution/natural acceptance remains CANNOT_CONFIRM with NO_INDEPENDENT_RUN_RECEIPT_SHA_BINDING and HK_FORMAL_ELIGIBILITY_FALSE. No blanket NATURAL_VERIFIED or PIT/model acceptance is claimed.

Morning 09:25/09:35/09:40/09:45 A natural stages each produced 10 rows. HK failures at those stages remain historical failures; no manual stage rerun or synthetic backfill was performed. Separate A/PREP partial-source issues remain CANNOT_CONFIRM. Tonight's 17:30 natural next-target-date publication is NOT_RUN at delivery time; the same-thread monitor checks 17:32/17:42/17:52 and pauses after the last check. Stage monitoring continues through afternoon and 16:10 close.

The first D-1 API reload encountered a bootstrap error; the old service was restored and a later unload-settle retry succeeded, with the failure receipt retained. A scheduler preflight initially referenced a validation API absent from the legacy package; it stopped before mutation, then used the actual package inventory/manifest validation. An early baseline import omitted -B, so generated pycache provenance remains CANNOT_CONFIRM; subsequent checks disabled bytecode. These are preserved evidence, not suppressed successes.

A R2 postactivation readback: independent PASS for the frozen API/UI scope. Five A stages each return 10/10 nonempty names (50/50 total), with selection identity/order/rank/score unchanged; refreshed 8873 UI displays ten name/code pairs for 09:45–10:30. Missing-pool uncertainty remains explicit. Receipt SHA: `9cf75363dc2998ed40e98b2e10970418404b9455b00e8354ddb6af3f7ba5b117`, at `V4_A_STAGE_NAMES_20261015/reviewer/a_stage_name_postactivation_review_receipt_r2.json`. No new P0/P1/P2 findings. Full runtime identity remains CANNOT_CONFIRM: release ID DECLARED_ONLY, plist binding CANNOT_CONFIRM, acceptance receipt/runtime inventory/dependency manifest unavailable. App root, selected modules and manifest locator/hash were confirmed. This limited readback PASS does not change stage/natural acceptance.

## Delivery boundaries

This is a PATCH_ONLY delivery because the local A consumer/test baseline contains preexisting unrelated modifications that differ from the remote base. The three patches record only this task's canonical/runtime deltas, each bound to exact before/after SHA in `sha256.json`; they were independently applied to temporary pinned baselines and produced the exact expected after bytes. They are not a claim that the remote base is a runnable copy of the deployed service. The new focused HK test is included in full. No unrelated dirty source, runtime package, raw market data, credentials, account data, or original input is uploaded. The canonical materializer remains byte-identical to its pre-task SHA `046c4f08d08a250d44d9a6af9b9fe5ec615ad05aae268f8c1e451fbd9110a34c`.

Local evidence roots: `/Users/lexi/Desktop/学习/agents调试/V4_D1_POOL_MARKET_20261015`, `/Users/lexi/Desktop/学习/agents调试/V4_HK_D1_RECOVERY_20261015`, `/Users/lexi/Desktop/学习/agents调试/V4_A_STAGE_NAMES_20261015`.

RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false. Vibe 8910 unchanged.
