# 实际执行环境与验证结果

本轮实际环境为 **Linux x86_64，CPython 3.14.6**；使用固定源码中的 `uv.lock`，numpy 2.5.3、pandas 2.3.3、pyarrow 24.0.0。依赖锁 SHA256 为 `7cb690f890cc28b6a79311f07e724f61c3dc4411494d480c0041f075f0825bfd`。详见 [ENVIRONMENT.json](evidence/ENVIRONMENT.json)。这不是 Mac 原生或私有资产验收。

## 最终定向结果

| 范围 | 实际结果 | 证据 |
|---|---|---|
| 经理跨日 + 接口 + 原链与每日接线 | **82 PASS，0 SKIP** | [最终日志](evidence/manager/final-targeted.log) |
| 超跌新增完整身份比较回归 | **18 PASS** | [新增身份日志](evidence/rebound/green-owner-identity-locked.log) |
| 超跌原四模块 | **77 PASS + 4 SKIP = 81 项** | [原四模块日志](evidence/rebound/rebound-four-modules-locked.log) |
| e06d 原 98 项 + 新 28 项 | **126 PASS，0 SKIP**，13 文件分别独立进程运行 | [全套摘要](evidence/revision/final-suite/SUMMARY.json) |
| 修订 helper / 原门禁最终整合者复跑 | **20 PASS / 8 PASS** | [helper](evidence/revision/root-tool-final.log) / [gate](evidence/revision/root-gate-final.log) |
| 三份补丁在新基线副本应用 | git apply --check / apply 成功；全部文件逐字节等于已测候选 | [补丁应用证明](evidence/PATCH_APPLICATION_VERIFICATION.json) |

命令（将 `V5_TEST_PYTHON` 设为独立 3.14.6 环境解释器）：

```sh
# 经理候选 V5 根；fixture 指向原 e06d bundle 的绝对路径
PYTHONPATH=src:tests "$V5_TEST_PYTHON" -B -m unittest \
  test_daily_review_handoff test_manager_current_recovery test_daily_revision_chain \
  test_manager_plan test_us_mapping_scope test_run_ledger test_daily_dispatch \
  test_daily_us_owner test_daily_owner_adapters test_daily_manager_assembly -v

# 超跌候选 V5 根
PYTHONPATH=src:tests "$V5_TEST_PYTHON" -B -m unittest \
  test_rebound_owner_identity test_rebound_panel_repair test_rebound_raw_repair \
  test_rebound_admission test_rebound_observation -v

# revision 候选 bundle 根；原模块命名空间须独立进程
for test_path in tests/test_*.py; do
  "$V5_TEST_PYTHON" -B -I "$test_path" || exit "$?"
done
```

原四模块 4 个 SKIP 的原因是 `V5_REBOUND_REPAIR_ORIGINAL_TESTS` 与 `V5_REBOUND_OBSERVATION_ORIGINAL_TESTS` 没有设为 1；相关真实模型/私有输入未提供。没有删除 skip 条件。full discovery 还有 `V5_REBOUND_OWNER_ORIGINAL_TESTS` 的一个原 opt-in SKIP。

## 完整 discovery 不是全绿

经理最终源码：**Ran 541 tests in 143.678s；FAILED (failures=7, errors=24, skipped=9)**。候选中每一个失败/错误均在未修改 `3d9541ac` 的相应模块重跑中复现，名称集合完全一致。基线对照为 `Ran 60 tests in 22.519s；FAILED (failures=7, errors=24)`。[完整日志](evidence/manager/final-full-discovery.log) · [基线日志](evidence/manager/baseline-failures.log) · [逐项对照](evidence/manager/final-full-suite-comparison.json)。

经理 24 个 ERROR：19 个缺少真实公告或 US 请求文件；4 个 `test_manager_membership` 使用当前日期遇到非已验证 HK 交易日；1 个 `test_manager_panel_observation` 没有可用的 row_summary。7 个 FAIL：同模块 1 个日期/观察断言，另 6 个是既有 worker/review 的 runtime module_id/release_id 未绑定。原基线同环境逐项复现，未通过改日期或刷新无关 pins 掩盖。

超跌完整源码：**480 项，6 FAIL、19 ERROR、5 SKIP**。19 个 ERROR 同为缺少真实公告或 US 请求文件；6 个 FAIL 同为既有 runtime 身份未绑定；在未修改 `ebe5944e` 的 33 项失败模块对照中全部复现。[完整日志](evidence/rebound/full-discovery-locked.log) · [基线差异比较](evidence/rebound/baseline-failure-comparison.json)。

这些全量结果只能说明已知环境/基线缺项被完整报告；不能把缺少输入的路径视为已验收。FutureWarning 与 ResourceWarning 保留在原始日志中。

## 明确未执行

真实原 reviewer 补充返回、原 392 条公告业务 create/import/readback、宿主真实模型通道提交、Mac 私有 repair child 发布、生产 API/Chrome、自然时段、集成及部署均未执行。定向测试包含合成 fixture 和本地只读 HTTP 边界验证；不冒充生产 API 或 Chrome。
