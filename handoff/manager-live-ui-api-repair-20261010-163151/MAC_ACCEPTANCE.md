# Mac 独立验收与回滚交接

**当前交付：`PROPOSAL_ONLY / LIVE_API_UI_NOT_RUN`。** 下列是交给 Mac 执行者的后续验收方案，不是已经执行的操作记录，也不把本次修复请求扩展成真实 8873、owner capture/import、部署或市场数据写入授权。

目标为 `plan_date=20261009`、`selection_date=20261009`、`announcement_date=20261008`。事后人工执行必须标注 retrospective/manual；不能记作 10 月 9 日自然运行。

## A. 核对包与待测源，不接触运行服务

1. 核对下载 ZIP 的外部 SHA256，解压到独立交接目录。
2. 从包根运行只读校验与临时目录 patch roundtrip：

```bash
python3 -B tools/verify_delivery.py --patch-roundtrip
```

3. 对 Mac 上拟采用的源目录做只读前提检查；`V4_REPAIR_SOURCE` 应指向已确认版本的源码目录，而不是猜测的旧快照。下列环境变量只由执行者按实际路径设置：

```bash
python3 -B tools/verify_delivery.py \
  --source-root "$V4_REPAIR_SOURCE" --source-image before
```

该命令只读取目标，不应用补丁。它核对 7 份 before 字节、新 helper 必须不存在，以及三个原 reader/validator 的 SHA。不一致即说明版本需要先对齐。尤其要检查未被问题报告独立 live-pinned 的 `research_attention.py`；不得用更宽松的 `git apply` 结果替代这个前提。

4. 在独立的源码副本/工作树中应用，保留现役根和并行修改：

```bash
python3 -B "$V4_REPAIR_PACKAGE/tools/verify_delivery.py" \
  --source-root "$V4_REPAIR_ISOLATED_SOURCE" --source-image before && \
git -C "$V4_REPAIR_ISOLATED_SOURCE" apply --check "$V4_REPAIR_PACKAGE/runtime.patch" && \
git -C "$V4_REPAIR_ISOLATED_SOURCE" apply "$V4_REPAIR_PACKAGE/runtime.patch" && \
python3 -B "$V4_REPAIR_PACKAGE/tools/verify_delivery.py" \
  --source-root "$V4_REPAIR_ISOLATED_SOURCE" --source-image after
```

5. 按包内 runner 重跑 21 项后端和 23 项前端定向回归；再用 Mac 项目原有、锁定版本的测试/构建入口做集成验证。因为上传材料没有完整 package metadata、依赖锁和全仓配置，本包不伪造一个已验证的全工程命令。记录实际执行的完整命令、退出码、环境版本及输出。

`before/after` 才是应用源；`reference/` 和 `test_support/` 是核对/离线依赖，不能整目录覆盖 live 项目。不要从本包复制原 owner state 或市场数据；本包也不包含这些数据。

## B. 原 owner / API 验收条件

完成后续所需授权和隔离集成后，由现有 `ManagerResearchJobService.refresh_workspace_plan` 及原 API 路径承担验证，不建立替代 owner。

记录实际源根、应用 manifest、进程运行身份、8 份 after SHA、实际 Python 模块来源以及 build/bundle SHA。仅源码命中不足以证明服务已加载新代码。

### B1. 旧计划应保持明确不可消费

- 保留并验证原 per-run product 与 attempt；不手改其中的 `input_identity`、新 schema、components、product SHA 或 consumed/status。
- 新候选读到其余前提合法、但没有 v2 身份组件的 legacy product 时，应返回 `STALE_INPUTS_CHANGED`、`consumed=false`，诊断含 `SAVED_IDENTITY_COMPONENTS_UNAVAILABLE_OWNER_REFRESH_REQUIRED`。原有更早的拒绝状态仍优先：保存产品/attempt 校验失败可以返回 `READBACK_FAILED`，cutoff 缺失或保存 cutoff 晚于读取 cutoff 可以返回 `PLAN_AFTER_READ_CUTOFF`；这些拒绝不应被误判为必须显示 stale 才算成功，均不可消费。
- 现有 `ALREADY_MATERIALIZED` 分支不能消费同一 legacy product。若已过合法自然时间窗口，不为了这项测试改时钟、改日程或补造 SCHEDULED_PREOPEN / SCHEDULED_MORNING。相应函数逻辑已有离线回归；真实窗口验证另记状态。

### B2. 同 run、同 product、同日期重复读回

- 在适用执行上下文中由原 owner 生成新 v2 产品，保存原 owner receipt、准确 execution_kind 与完整日期绑定。事后手动运行不能冒充自然冻结。
- 记录原 POST 的请求路径、参数、时间与响应；紧邻两次 GET，再做一次独立进程/浏览器读取。已知读回入口是 `GET /api/v4/manager/research/workspace?date=20261009&view=dynamic`，日期参数的最终解释以原 response `date_bindings` 为准。
- 保存每份响应体，计算 body SHA；记录 `run_id`、product SHA、saved/current input identity、identity schema/components、date bindings、semantic version、research cutoff、owner-attempt identity、status/consumed 和四个安全标记。
- 在所有 plan-relevant 输入不变时，新计划应保持同一 run/product/date，诊断为 MATCH，CURRENT/consumed 语义一致；读前读后 per-run 文件 SHA 不变。
- 如果实际相关输入改变，接受真实 stale，并要求诊断给出能够追溯的 component、saved/current SHA 和来源。不能把“没有 stale”作为无条件成功标准。

### B3. 因果边界验证只在隔离副本中做

以下变体不得写进权威 registry 或实际 owner artifact：

| 隔离变体 | 预期 |
| --- | --- |
| 只改变未消费 registry entry，因而全局 manifest SHA 改变 | input identity 不变；新全局 SHA 仍作为 provenance 可见 |
| 改变实际 consumed payload、receipt、entry SHA、source/root/date/path | identity 改变或原 reader 验证失败 |
| 改变语义 available_at/content | identity 改变或校验失败 |
| 仅在 source_row/HK/Stage/未知绑定中改同名 manifest 字段 | 不能被通用剥离误忽略 |
| 新产品在 date、cutoff、semantic version、product hash、安全标记或同 run attempt 不合法 | 保持 fail-closed，不可消费 |

原历史 live changed field 只有在取得缺失的旧/新原始输入与准确来源差异之后才能从 CANNOT_CONFIRM 升级；本轮修复与后续新 run 的成功都不能倒推它。

## C. 真实页面验收

记录浏览器**实际加载**的资源 URL 和 bundle bytes SHA，与部署构建产物核对。候选 build SHA 不能代替 browser-loaded SHA。刷新后在宽屏及接近原截图的约 670px 窗口各保存一张完整、带日期/状态的截图。

- 计划消费状态之后可见 `ANNOUNCEMENT`、`HK_CONNECT`、`OVERSOLD` 三路状态；当前接口给出的 CANNOT_CONFIRM/PARTIAL 如实展示。
- 日期、数据日、run/product/input identity 与同一已保存 response 对齐。未知数量保持未知；READY_EMPTY 只能来自合法 owner 结果。
- 计划 stale 时三路摘要仍可见，同时显示真实输入变化或 CANNOT_CONFIRM 诊断；不得隐藏 stale 以制造闭环。
- 上层“美股评估/完整度”与“每日 US-HK 已审映射”相邻且范围清晰。当前 4 项已审、VALID_EMPTY、0 匹配仍有局部覆盖说明；变更测试关系数时数字必须随响应变化。
- 原始观察默认折叠，展开后可查看全部 100 行与来源；筛选/背景区仍可用。再次读取不残留上次日期/结果。
- 合成日期错配、安全标记或 run/product 绑定异常的负向验证只能走隔离响应；真实页面应拒绝异常合同，不继续显示旧的已核结果。

前端独立组件测试已覆盖这些行为的主要分支；真实 Vue 宿主样式、API 数据、浏览器缓存和实际加载 bundle 仍需此节现场验收。

## D. 公告与其他数据缺口的后续交接

目标 `20261009 / 20261008` 的公告分析/导入仍 NOT_RUN。需要完成该链时，使用原 `ops/run_manager_daily_announcement.py` 的 `capture`、`prepare`、Reader/Reviewer handoff、`register-handoff`、`import`、`readback` 入口；参考原问题包 `ONE_DAY_OWNER_REUSE.md`，按 owner 真实 evidence/run/root 绑定具体参数。本包不执行这些入口，也不复制前一日 613/613/33 结果为本日结果。

HK exact-date membership、安全主表、六日 unit/scale 与 provider finality 只接受原权威来源合同。修正 root 下 20261008 panel 已存在；不能继续诊断为 panel 缺失，也不能用今天 capture 回填 PIT 日期。US 四关系映射及另一 isolated run 的 external_finance 缺 market_snapshot 要分开记录。

## E. 回滚

在隔离副本中，只有当前文件仍精确等于 after SHA 时，才使用反向补丁：

```bash
python3 -B "$V4_REPAIR_PACKAGE/tools/verify_delivery.py" \
  --source-root "$V4_REPAIR_ISOLATED_SOURCE" --source-image after && \
git -C "$V4_REPAIR_ISOLATED_SOURCE" apply --reverse --check "$V4_REPAIR_PACKAGE/runtime.patch" && \
git -C "$V4_REPAIR_ISOLATED_SOURCE" apply --reverse "$V4_REPAIR_PACKAGE/runtime.patch" && \
python3 -B "$V4_REPAIR_PACKAGE/tools/verify_delivery.py" \
  --source-root "$V4_REPAIR_ISOLATED_SOURCE" --source-image before
```

反向结果应恢复七份原文件并移除新 helper；原 owner/validator 字节不变。若后续有人改过这些文件，应先核对并行差异，而不是 reset/clean 或覆盖。真实部署的版本切换沿原发布流程执行，独立保存版本、构建与运行身份；本包没有执行服务切换。

回滚源码不改写计划、attempt、registry 或市场数据，也不把任何旧计划强制改成 CURRENT。回到旧实现会恢复原全局 manifest 耦合行为；需要在回滚记录中明确这个已知限制。

## F. 验收记录最小字段

分别报告候选、独立审查、Mac 集成、部署、owner、API、UI、自然时段的 PASS/FAIL/NOT_RUN；附命令、源根与 SHA、run/product/date/cutoff/attempt/body SHA、浏览器实际 bundle SHA、读取前后 immutable product SHA、三个 channel 及 US scope、剩余 CANNOT_CONFIRM 和四个安全标记。没有对应 receipt 的阶段保持 NOT_RUN，不能用本包的合成成功填入。
