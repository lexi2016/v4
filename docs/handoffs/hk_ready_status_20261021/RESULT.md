# HK READY status repair — 2026-10-21

The canonical HK D-1 source changed to eligible `READY`; the active Stage consumer accepted `STRICT_0_2_READY` and `PARTIAL_WITH_ROWS`, so it rejected today's valid 100-code pool. The repair accepts `READY` only through the verified canonical resolver, exact schema/date and explicit eligibility. Existing provenance, trio SHA, Top100 membership, model and research safety checks remain enforced. Selection/ranking and A-share logic are unchanged.

## Delivered and independently accepted

- Source and regression tests: REVIEWED/PASS, 29 tests passed in 0.42 seconds using Python 3.14. The original rejection was reproduced. Existing STRICT/PARTIAL behavior is retained.
- Canonical source integrated; Stage release `hk-ready-status-20261021-r1` activated while idle at 09:38:20. Independent inventory verified 1,087 entries against the previous release, with only the target validator and release-local config changed. Schedule retained; API and deadline services unchanged by this task.
- Natural `STAGE_0935_0940`: frozen pool = snapshot = raw unique codes = actual selector input = 100, missing/extra = 0. There are 500 minute rows covering 09:36–09:40, and 10 selected rows. Independent physical artifact/manifest/receipt verification and API readback passed. This proves full100 consumption; provider completion at 09:41:22 and owner receipt at 09:41:57 do not establish the five-second timeliness target or overall NATURAL_VERIFIED.
- `STAGE_0925` recovered once through a separately reviewed, hash-pinned operator capsule. Capsule R2 independent checks: 11 passed in 0.03 seconds; R1 failure retained. The recovery used exactly the 20 preserved second-filter rows, retained the original 09:19:48 timestamps, and selected 10. Independent actual readback passed; all A lane objects, pointers and six immutable file hashes were unchanged. Attempt 2 is consumed and settled; automatic retry is disabled for this operator attempt.
- API and refreshed V4 page show HK10 for recovered stage1 and stage3. Stage2 remains missing its original-window HK input. UI observation/NO_BUY labeling remains.

## Evidence limits

Historical 09:20 all100 actual observation/reranking remains CANNOT_CONFIRM: the retained 50-reference/20-filter artifacts cannot prove the missing original full100 observations. `STAGE_0930_0935` has no verified original-window snapshot and was not fabricated or recollected. Later full100 acceptance does not certify those earlier windows.

A-share read-only audit: frozen/requested 327, returned 313, exactly 14 missing, 327 pages read / 14 EMPTY_PAGE / zero read errors. All missing codes are 920xxx BSE symbols. The installed TdxMinuteReplayProvider routes every six-digit 9-prefix code to SH market1; the adjacent HQ path defines BJ=2. This mapping defect is the strongly evidenced likely cause. Per-symbol request/response records are absent, and corrected BJ2 queries were NOT_RUN, so provider-level causality remains unconfirmed. No A code was changed. The A capture at 09:26:35 is not an exact natural 09:25 verification.

## Reproduction and identity

Writer baseline: `55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054`.
Sync branch: `codex/hk-ready-status-20261021-sync-r1`, based on existing remote `f9154a3b4db1d7657ae6549f2efe41d6979b6caf`.
Canonical root: `/Users/lexi/Desktop/学习/v4_app`.
Active Stage root: `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/hk-ready-status-20261021-r1/app`.

| File | Before SHA256 | Accepted SHA256 |
|---|---|---|
| stage_center/_runner_parts/hk_input_validation.py | canonical: 92e8fb2be06e6530c33f3cf2f5b44f29b0bcf7875e6a5902260f8be4c814f735; previous runtime: 594a430e91a4a158ea9f72bae7a00aa19481b01b913d7e18c0f5e075954e9f1e | 22c7a1ae4cae7f4b828d157b3fd98ded3781883b628d5c475cba9f8cac9ca4a2 |
| tests/test_hk_ready_status_20261021.py | absent | c14442115198cf9b1f06c96a283600b4874394754af6d0dc9f81cde1e05e315c |

The baseline source tree lacks deployed helper dependencies. Regression uses the retained previous release read-only, with frozen source copies kept locally. This commit is not a standalone runtime bundle. With `E` set to the local evidence directory and `HK_READY_RUNTIME_ROOT` set to the retained `hk-stage8-network-20261020-r1/app`, the executed regression form is:

```sh
HK_READY_FROZEN_SOURCE_ROOT="$E/frozen_source" \
HK_READY_FROZEN_BASELINE="/Users/lexi/Desktop/学习/agents调试/V4_OPENING_POOL_CONSUMPTION_20261021/frozen_input_baseline.json" \
PYTHONDONTWRITEBYTECODE=1 /Users/lexi/Desktop/学习/v4_app/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_hk_ready_status_20261021.py --basetemp="$E/pytest-independent"
```

Independent acceptance is recorded in `code_independent_review.json`, `deployment_independent_review.json`, `natural_hk100_independent_review.json`, `capsule_independent_review_r2.json`, and `recovery_independent_review.json` under local evidence directory `V4_HK_READY_STATUS_REPAIR_20261021_R1`. The operator script, pins, raw market data, runtime bundles, screenshots and logs are intentionally local and are not in source sync. Do not re-execute the consumed recovery.

RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false. No A repair, new provider query for A14, original-window recollection, model change or trading action was executed.
