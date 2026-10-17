# Issue 45 implementation prompt (after source-baseline sync)

请从主控已发布到私有 GitHub 分支的 Issue 45 source-baseline 开始，在独立新 checkout 中修复四个业务断点。正式源码已经位于仓库根目录下的 canonical `ops/`、`contracts/`、`infrastructure/`、`v4/` 等路径；直接在新 checkout 中修改这些正式路径并从 repo root 跑测试。`staging/` 导出缓存仅存在于原始来源机器，远端分支不包含它，也无需读取。

先阅读本 handoff 的 `README.md`、`SCOPE.md`、`SOURCE_EXPORT_MANIFEST.json`、`DEPENDENCY_MANIFEST.txt`，再阅读既有问题材料：

1. `docs/handoffs/us_hk_friday_close_20261017/packet/CHAT_ISSUE.md`：历史故障证据和冻结业务边界。
2. `docs/handoffs/us_hk_friday_close_20261017/packet/CHAT_PROMPT.md`：原始修复验收合同；其中关于“当前 LaunchAgent 缺少四个 identity 环境变量”的陈述已被较新的运行状态取代，不能直接当成当前事实。
3. `docs/handoffs/us_hk_source_baseline_20261018/REMOTE_ROOT_README.md`：远端 repo root 的短入口页；它说明正式源码路径和本次 handoff 的位置。
4. `docs/handoffs/us_hk_source_baseline_20261018/staging/`：该路径仅记录本机来源校验缓存的位置；缓存只存在于原始来源机器，远端 checkout 不包含它，也无需读取或导入。用仓库根目录下已发布的 canonical 源文件继续工作。
5. `docs/handoffs/us_hk_source_baseline_20261018/SOURCE_EXPORT_MANIFEST.json`：逐文件源码路径、源/副本 SHA 和大小，以及当前三个实际运行根的关键源文件差异。
6. `docs/handoffs/us_hk_friday_close_20261017/packet/evidence/real_relation_projection.json`：667 股票 / 1,003 关系的无报价派生测试投影；它不是 owner artifact，也不是完整 recovery overlay。其 `staging/` 副本仅存在于来源机器，不是远端依赖。

## 在目标 checkout 中先核实当前基线

`SOURCE_EXPORT_MANIFEST.json` 的源端是脏的 canonical worktree `HEAD=55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054`，不是目标 GitHub 分支的证明。主控会提供已同步分支/commit；先确认其基线并对比 manifest，不要把本机隐藏源码或旧 ZIP 摘录当作 checkout 内文件。

上一份问题包的三处旧运行身份现已更新：US digest 当前为 `us-entry-count-repair-20261017-r1/app`，四个 `V35_APP_ROOT`、`V35_RELEASE_ID`、`V35_RELEASE_MANIFEST_PATH`、`V35_RELEASE_MANIFEST_SHA256` 环境键已绑定；manager scheduler 仍为 `zsxq-long-pdf-scheduler-20261016-r3/app`；selector API 当前为 `us-receipt-compat-api-20261017-r1/app`，其 `ProgramArguments`/`V35_APP_ROOT` 覆盖旧 `r11c` 的 `EnvironmentVariables`。manifest 给出核心文件的真实 SHA 比较。旧 LaunchAgent “缺 identity”描述不能继续当作当前状态；新绑定是否通过 dispatcher manifest 校验及后续链路是否成功仍须用当前证据确认。

当前源码工作树的 `ops/run_us_market_slot.py`、`ops/us_market_digest.py` 与 digest runtime 同 SHA；manager `supervisor.py`、`scheduler.py` 与 scheduler runtime 同 SHA；API `NativeAdapters`、`source_bindings` 等文件与所选 API runtime 有内容差异，详见 manifest。manifest 记录本地来源快照和 SHA；远端修改直接作用于新 checkout repo root 的 canonical 文件，无需读取不存在的 `staging/`。不要根据 release 名称猜测修复状态，也不要将差异解释为目标行为已验收。四断点的当前自然运行、API/UI、完整 owner-overlay 消费和通知证据在本 baseline 中均为 `CANNOT_CONFIRM`。

## 唯一修复目标

仅修复 V4 现有 US 收盘后选择链路中的以下四个断点，并使用正式源码 owner 及现有数据/API/selector：

1. **Dispatch/release identity**：验证当前 digest identity 绑定和 manifest 检查。若仍有故障，保留原 release-manifest 校验，修复 owner 边界并让失败可定位、fail closed；不以旧“缺环境变量”报告代替当前复现。
2. **日期与 session 合同**：将 scheduled date、trade date、US session date、HK target date、source cutoff、run ID、manifest、SHA 保持为独立可校验字段。冻结例为上海时间 2026-10-17 04:15 对应 US session `20261016`，HKEX `20261019` 休市，目标 HK session `20261020`；禁止静默退回 `20261015`。
3. **精确 source artifact 到已有 selector draft 的 handoff**：只有精确 session/target 的 owner artifact 与 receipt 验证通过后，幂等刷新已创建的 `20261020` 目标草稿。Capture、selector consumer、API/page reload、notification 分别记 receipt；缺失或 partial 输入保留原状态、覆盖率和错误，不 impute。
4. **真实 selector consumer 映射输入**：使现有 selector consumer 消费完整冻结的 667 stock / 1,003 relation overlay，并通过 consumer readback 证明 relation identity/count 守恒、原始 source/status/use-scope/evidence 字段保真。`OPEN` 和 `CLOSED_EXCLUDED_SCOPE` 不可成为候选；757 条 `CLOSED_RESEARCH_SCOPE` 不可升级为 `REVIEWED` 或 PIT 安全。Catalog/API 展示不构成 consumer 证明。派生 fixture 可做 source-level 测试，但不是完整 overlay/owner/runtime receipt。

## 冻结范围与安全

- 复用既有 producer、digest、manager scheduler、calendar、selector、mapping catalog 和 API；不增加 producer、数据底板、第二面板或平行 selector。
- 不回放或重新采集行情；不改 frozen capture、研究结果、原始输入或报告。after-close snapshot 不是官方 US 日收盘、owner artifact 或 receipt。
- 不修改本机 release copy、LaunchAgent、计划任务或服务；不部署/重启、不发通知、不做真实交易。
- 不改变 mapping/研究状态含义、排序/rank、BUY gate、provider 权限或交易行为。保留 `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。
- 旧问题包中的两个研究展示限制继续适用：Top 20 US 的 HK 代码字段汇总所有关系状态，可能包含 `OPEN`；候选证据以正向 `CLOSED_RESEARCH_SCOPE` 行为准。冻结 builder 的 `--verify` 仍会重建/覆盖输出，不能在 frozen 路径运行。油价相关上涨可能是航空等用户的成本压力，不自动构成利好。

## focused tests 与交付

从 repo root 安装 `docs/handoffs/us_hk_source_baseline_20261018/DEPENDENCY_MANIFEST.txt`，再按 baseline README 的 Python 3.14 测试命令从 repo root 对 canonical 文件运行。该命令排除一个单独的 11:30 intraday dispatcher 测试，因为它需要不属于本 Issue 45 闭包的 `test_v4_intraday_research.py` 与 `ops.run_intraday_research`；不要把它误报为失败，也不要改测试隐藏依赖。此前导出副本有三个可复现的源/测试断言不一致；最终冻结 SHA 的 reviewer 需独立复跑并确认，之后再由实际目标修复决定是否触及；不要在 baseline 阶段处理。

交付实际 diff、目标 branch/base、对应 runtime identity、每个 focused test 的命令和结果、四断点逐项行为结果、精确回滚文件，以及各层独立 receipt。完整 owner overlay 尚未被 runtime 消费验证前，必须保留 `CANNOT_CONFIRM`。不要把 Writer 测试称作独立审核；等待另一身份只读 Reviewer 对实际 diff、冻结 PASS 范围和目标行为出具 `REVIEWED` / `BEHAVIOR_VERIFIED`。
