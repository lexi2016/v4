# Recovery and daily invocation candidate evidence

- Repository: `lexi2016/v4`; branch: `v5/rebound-owner-20261009`.
- Original V5 baseline: `2719328494a9ec3177a7be56e7348f86dd0137f5`.
- This increment baseline: `2edcc42204f6e319da9df8cad7578d9f6eaf13b3`.
- Code/document commit: `c1099fbeb1b149f803d5e1c97c940e60ed02f926`.
- Source root: `/workspace/v4`; cloud Python `3.12.14` used only to parse/compile bytes without importing or executing product modules.
- Read-only V4 comparison: `74478a0e62be215c8527ccc9a14b89b51042d014`, `handoff/manager-four-functional-gaps-20261009/package/`.

| Added path | Before | After SHA256 |
|---|---|---|
| `V5/src/v5_shadow/rebound_recovery.py` | ABSENT | `adfea1ac357fa6366fa13fcc7de79ee4ad016f77e6b6388818cd0b7b28143aaf` |
| `V5/src/v5_shadow/rebound_daily.py` | ABSENT | `e20279ee4399707f431f24bd8d85504bb693f5e61768a3a40c43ccdea3d6245c` |
| `V5/tests/test_rebound_recovery.py` | ABSENT | `37deed81e14fb10a152565126631200a26ff6f1a6f2851de877cdd059060aabb` |
| `V5/tests/test_rebound_daily.py` | ABSENT | `477672f373f3cf7eebda73ae4b70a9cba2263d25911c7f57c40117ce02265bbf` |
| `V5/docs/REBOUND_RECOVERY_DAILY_20261009.md` | ABSENT | `0507b46931d3f11a1e9205fc4108c49d9572dfc71c796233242a721280660dce` |

Existing owner, observation, manager_plan, legacy_adapter and worker were compared byte-for-byte with increment baseline and are unchanged. No V4/vendor/UI/source-owner files changed. No market payload, credentials or execution-environment files added.

Static validation: four Python files `ast.parse` and `compile(tree, ..., 'exec')` succeeded without executing the compiled objects. 25 recovery + 11 daily test methods identified. Staged whitespace check passed. The independent source reviewer confirmed the append/internal-gap and hard-NOT_PROVEN findings. Review found and fixed writes-before-root-overlap-check, cross-day readback reconciliation, failed-attempt reconciliation and repeated failed-reconciliation behavior. These are static findings; no product behavior pass is claimed.

Mac commands (locked Python >=3.14 and V5 uv.lock environment):

```bash
PYTHONPATH="$PWD/V5/src:$PWD/V5/tests" "$PY314" -B -m unittest \
  test_rebound_recovery test_rebound_daily -v
PYTHONPATH="$PWD/V5/src:$PWD/V5/tests" V5_REBOUND_OBSERVATION_ORIGINAL_TESTS=1 \
  "$PY314" -B -m unittest test_rebound_observation -v
```

All product tests above: **NOT_RUN in cloud**. Recovery tests use synthetic planner fixtures and actual synthetic packed native bytes. Daily tests stub the owner to isolate orchestration; existing observation differential tests remain necessary. Actual 695-row recovery, proof of units/scale/session completion/PIT/target membership, original-owner repaired panel publication, manager integration, API/UI readback and scheduled natural execution remain **NOT_VERIFIED**.

Concrete blockers: original append updater cannot fill internal 10/5–7 gaps; no usable recovery writer found in this checkout or new V4 comparison package; new manager source still has no successful volume-evidence decoder branch; exact 10/8 full-master receipt/capture absent per Mac report. Amount/unused full-master fields/natural acceptance are not silently added to the numeric two-gate predicate. Documented daily semantics plus real capture evidence may establish completed-session use without a provider final flag; this candidate does not invent that evidence.

See `../REBOUND_RECOVERY_DAILY_20261009.md` for request schemas, zero-request local audit, bounded Mac capability/canary plan, original-owner repair patch points and manager/daily integration. The 694-code acquisition remains HOLD with zero requests issued by this work.
