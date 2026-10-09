# 公告 owner → consumer 接入验收

## 结论

**本轮未确认公告消费器缺陷，因此保留 R2 `workspace_announcements.py` 与 `announcement_analysis.py` 原字节。** 用同一套 8 项测试分别运行恢复为包内 20 个原 R2 目标文件的隔离副本、以及本轮合并候选，两次均为 **8 passed / 0 failed / 0 errors**。这里验证的是 Linux 离线合成工件下的实际 `create_app` 注入与 HTTP 路由行为；不是 Mac、真实公告、实际 Reader/Reviewer、自然时段或已部署 API 的验收。

现有 2026-10-09 target / 2026-10-08 publication 现场投影中 capture、Reader、Reviewer 为 NOT_RUN。`ANNOUNCEMENT_ANALYSIS_NOT_IMPORTED` 忠实反映原 owner 输入尚未形成，不能用本次合成测试把该真实日状态改成成功。

## 沿链路查实的行为

测试使用原 `capture → prepare → register-handoff → import` 入口，保留 catalog、源正文、原始 Reader/Reviewer 文件、handoff、产品、owner receipt 的 SHA 与日期绑定。Reader 和 Reviewer 是显式标记的、不同身份的离线测试输出。`create_app` 创建自己的 provider、共享 MaterialStore、私有包 service 和 reader；测试只替换数据源 transport 与时钟，禁止 socket 连接，不替换任何业务验证器。

| 情况 | 原 R2 | 本轮候选 | 确认内容 |
|---|---|---|---|
| 完整审阅并显式 SELECTED_EVENT | PASS | PASS | 同一服务先读未导入，再导入，GET 变为 ANNOUNCEMENT READY / 1 candidate；输入 identity 改变；product、handoff、evidence run、owner receipt SHA 一致 |
| 完整审阅并全部 NOT_SELECTED | PASS | PASS | 1 个已审股票、0 个待审、0 selected，通道 READY_EMPTY；不是因为缺数据或所有计数为零而冒称有效空 |
| owner 工件不存在 | PASS | PASS | NOT_RUN / CANNOT_CONFIRM，candidate_count=null，没有发起源采集 |
| 原始 Reader 文件字节变化 | PASS | PASS | REGISTERED_HANDOFF 阶段报 OUTPUT_SHA_MISMATCH，拒绝消费，保留观察到的原产品身份 |
| 原始 Reviewer 文件字节变化 | PASS | PASS | 同上，不能只凭产品与 receipt 存在就消费 |
| 请求相邻 publication 日期 | PASS | PASS | 不借用 10/08 产品满足 10/07；该精确 pair 继续 NOT_IMPORTED |
| owner import 晚于计划 cutoff | PASS | PASS | 验证工件身份成功，但返回 NOT_CONSUMED_AFTER_CUTOFF，无股票进入通道 |
| Reader/Reviewer 仅空白差异的同一身份 | PASS | PASS | 原 register-handoff 拒绝，不写 analysis product 或 handoff manifest |

每个只读场景均比较读取前后的 manager-state 文件 SHA 集合及 source transport 调用列表，确认 GET 没有改文件或再次采集。成功用例仅有 3 次合成来源调用：目录第一页、目录终止空页和一页正文。四项研究安全标志保持 `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`，`natural_run_verified=false`。

## 最小交付

只新增 `tests/test_manager_four_announcement_integration.py`，生产公告模块无 diff。前轮已经修复的 `ops/run_manager_daily_announcement.py`（SHA `aee0e5c31f30b296864a7ad81263fbc748b65cb9b4d443f83a756019cbc94a38`）作为既有、明确标识的测试支持依赖复用；不再次修改包内 REFERENCE_ONLY 旧 runner，也不把其身份冒称为当前 Mac R2 ops 源码身份。

原 R2 / 候选公告源码 SHA 均为：

- `workspace_announcements.py`: `82187a190f2a308cc193473a9583f0c8edb82782ce45217a1dce8c866f172f0b`
- `announcement_analysis.py`: `b60b8c0c663b203d2ece5a5b451eb41ca296396b2db3630dff4a92a8566f373f`
- 新测试文件: `d44e07587ea0ee39d88b47eb08f1cca3fba173a952f6fe40d034ee13ce2ba0ce`

完整身份见 `source_identity.json`；20 个原 R2 文件恢复记录见 `r2_baseline_identity.json`；环境、逐项结果、命令及早期诊断见 `test_summary.json`。

## 运行命令与结果

解释器：`four_gaps/test_env/bin/python`，Python 3.14.8。保留项目 warnings 策略，出现 1 项已有 `StarletteDeprecationWarning`（httpx TestClient）。本轮未以过滤警告方式制造无警告结果。

候选，cwd=`four_gaps/app`：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=. \
  /workspace/scratch/21926b793c00/four_gaps/test_env/bin/python -m pytest -q \
  tests/test_manager_four_announcement_integration.py \
  --basetemp=/workspace/scratch/21926b793c00/four_gaps/announcement/pytest-app-contract04 \
  --junitxml=/workspace/scratch/21926b793c00/four_gaps/announcement/app-contract04.xml
```

结果：`8 passed, 1 warning in 2.14s`，exit 0，日志 `app-contract04.log`。

隔离原 R2，cwd=`four_gaps/announcement/r2_baseline_app`，同一命令但将 basetemp 与 JUnit 路径分别改为 `pytest-r2-baseline` 和 `r2-baseline.xml`。结果：`8 passed, 1 warning in 3.24s`，exit 0，日志 `r2-baseline.log`。

早期未通过运行均保留：默认解释器缺 starlette；应用依赖闭包中的 selection/runtime_graph 原件缺失；测试最初外置 provider 与应用共享 MaterialStore 不是同一对象；测试 source response 没有使用私有注入包的类。前两项由父任务补齐既有源依赖，后两项只纠正测试 fixture。它们不计为公告生产业务的“红测”，没有据此修改或放松业务代码。

## 原 owner / 消费端 / 未确认项

- **owner**：原公告 catalog/body capture、实际 Reader、身份不同的实际 Reviewer、原 register-handoff/import。
- **consumer**：R2 `create_app` 注入 `ManagerResearchJobService`，原分析 import/read、共享 handoff 消费验证器、workspace channel 与输入 identity。
- **离线接受条件**：正向及失败边界 8/8 已验证；原 R2 已能消费完整合法工件。
- **真实日接受条件仍 CANNOT_CONFIRM**：10/09 实际 owner 工件、实际来源/日期/获取时间/cutoff、源 SHA、真实独立 Reader/Reviewer、正式 owner import、真实 API/UI 回读及自然时段均未在此环境运行。
- 完整工程测试命令交父任务合并门禁执行；本子任务没有把上述 8 项局部测试宣称为全仓回归。

不要随交付打包 `pytest-*` 合成状态目录或 `r2_baseline_app` 源码副本；必要交付是新测试、精简报告、身份清单和两次通过日志/JUnit。
