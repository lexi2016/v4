# Issue #29 独立审查

结论：`PASS_SCOPED_CODE_REVIEW_WITH_RECORDED_BASELINE_FAILURES`。已审2个生产文件的最小差异未发现新的 Critical / Important 阻断缺陷；新增回归通过。原测试的两项基线失败及完整父页依赖缺口保留，不能称全应用测试通过或日常运行恢复。

独立执行完成时间：2026-10-08 13:50:50 UTC。环境：Linux / Python 3.14.6 / Vitest 4.1.10；本轮没有Mac、live服务、正式计划、补采或发布动作。

## 范围与身份

审查根：`/workspace/scratch/a154a3323e32/worktrees/issue29`；固定前像来自 `b22836ef3f8fcc6b9218f3422a9bcd7aa61152e9`，本地组装前像为 `e521e8ebb3119e68095e02b1b54858c0dc0756a9`，不是可整树部署应用。本次审查历史读合同兼容与US reader失败DTO隔离，共2个生产文件、5个测试文件；准确集合及每份前后SHA见 `independent_result.json`。

- `v4/manager_research/workspace_history.py`：前像 SHA256 `da5e1223326631cc9070c3059ca606bac3840ef468ad5c06f2f3a51534f82ec1`；审查后像 `d46b84f084af5eb695812a7052520147722a80a6885fb3dfdb4c1a18de3c72b5`。
- `v4/manager_research/workspace.py`：前像 SHA256 `183e3ebd0322883a8f8cef37c0244f424f16c63d3120245e263bb9585133dea3`；审查后像 `ab25d4856019b10bda1cb73928e5e2e75fad870a8321025019dceeb2cf0b6b52`。仅原US reader异常handler变化，排除该handler后整份文件AST与前像相同。
- 新测试 `tests/test_manager_history_contract_20261008.py`：作者登记 SHA256 `36eeb5b9f41a927f6b9b19f6d1d1bd6f515986631ccd5754e14bbd423eacd774`，已逐行静态阅读。
- 原 `tests/test_manager_history_readback_r1.py` 只将一个过时“任何指纹变化即拒绝”测试更新成“跨指纹且原件无合同文本必须拒绝”；保留 owner 不得被调用的断言。

## 历史兼容审查

已审差异未发现新的 Critical / Important 阻断缺陷。此结论限于静态差异，不代表本机历史原件已获准读取。

1. 新兼容分支检查的是**已通过原 schema/digest/safety/window 门禁的保存原件**中的 `workspace.read_context.contract`。已核原 writer 经 `get_workspace()` 生成该文本并封入原产品；不是拿今天的接口合同名猜旧文件版本。
2. 保存指纹仍验证为64位小写hex；带指纹且源码变化时，原件必须明确保存受支持的 r1 合同。未知合同和缺合同拒绝；没有使用现场摘要SHA白名单。
3. `verified_plan_attempt`、semantic version、保存PIT、原 `_compute_workspace(...include_saved=False, context=原ctx)`、input_identity、14个冻结业务字段及重验PIT顺序保持。`_read_candidate`、`select_plan`、`_pit`、`unavailable`、历史失败US只读复核函数的AST与前像完全一致。
4. 14个冻结业务字段原样保留：schema/semantic/decision版本、target date、stocks、themes、materials、company_events、focus_symbols、rejected_relations、briefing、summary、market_screen、announcement_review。没有以计数相同代替字段相等。
5. 增加重验前后源码指纹比较；不一致时不返回consumed。成功/失败兼容证据只加到返回的read_context，未新增存储写入、producer、计划重跑或迁移接口。
6. 原无指纹legacy保留完整原owner重验；partial、候选未知、原执行kind和原run/cutoff仍按原规则返回，不升级为自然运行。
7. 新测试使用原writer保存后再模拟源码注释变化；两日期、缺合同/未知合同、坏指纹、来源与业务漂移、PIT、semantic、原scheduled attempt失败及存储前后字节均有相应断言。合法原证券/行情输入未附，测试身份始终是合成工程证据。

静态机械记录见 `static_history_checks.json`。其中 `workspace_read_control.py`、Mac StoreError `workspace_plan.py`、Mac merged `service.py` 和 `managerWorkspace.ts` 与隔离前像字节一致。此检查用于证明未被本项差异覆盖，不替代联合行为测试。

## US失败隔离审查

原异常fallback缺少 `daily_run` 的原schema、安全旗、覆盖字段和 `reviewed_research`。主控红灯日志显示真实Python manager GET产物进入冻结Mac TypeScript validator时5项失败、1项通过，实际错误为 `WORKSPACE_SAFETY_INVALID`；不是只更换展示文字的问题。

候选仅补齐该异常返回合同：reader不可用时 `CANNOT_CONFIRM`、覆盖计数null、run/source/capture字段未知，原plan reference仍NOT_CONSUMED且输入身份扩展为空。`matches=[]`与未知数量配对，不声明已筛选零条。20260930的事后研究引用按原Mac合同保留CANNOT_CONFIRM空卡片；其他日期为null，不猜旧美股session或原系统取得时间。现有成功reader路径、cutoff比较、产品SHA绑定完全未改。

冻结前端validator未改。独立跨语言测试调用真实Python manager GET，再交给 `validateManagerWorkspace`；四组日期/reader故障均可解析，并仍拒绝错日和伪造VALID_EMPTY。首屏测试使用已有合成公告fixture、真实request函数与原 `renderDailyChannels`，确认US未知不隐藏有效公告的股票/原理由及其他两通道。此为限定DOM函数验收，不是完整经理页面或真实公告33/54/75验收。

## 实际测试与不能相加的批次

收到主控“生产源码稳定”信号后才独立执行。准确命令、工作目录、exit code与日志SHA见 `independent_result.json`。

| 批次 | 实际结果 | 证据与解释 |
|---|---|---|
| 独立Python 7文件组合：新历史/US + 原历史readback/control/regex + workspace owner + daily channels | **114 passed / 1 failed；exit 1** | `independent_python_combined.log`。唯一失败为下述HK02既有fixture。新增34项在此批通过，不能再额外加34。 |
| 独立TypeScript首次组合 | 新US spec **6 passed**；原dailyChannels.runtime suite在收集阶段失败，0项执行；exit 1 | `independent_typescript_combined.log`。原父页缺 `managerAnnouncementAnalysis.js`，保留阻断。 |
| 独立TypeScript限定新US spec复跑 | **6 passed；exit 0** | `independent_typescript_targeted.log`。与上一批同6项重复，不能合计12。 |
| 历史作者原4文件冻结基线 | **54 passed / 1 failed** | 已读取 `history/baseline_history_regression.log`；同一HK02失败。其候选81/1含新历史27，与独立批次有重叠。 |
| 主控扩展原7文件冻结基线 | **126 passed / 1 failed** | 已读取 `backend_baseline.log`；下述Connect fixture失败。 |
| 主控扩展候选9文件 | **160 passed / 1 failed** | 已读取 `backend_final.log`；同一Connect失败，新34项通过。与上述批次重叠，不能汇总成总通过数。 |
| 主控前端限定组合 | **13 passed** | 已读取 `frontend_final.log`；新6项与旧7项限定合同测试，不是缺依赖的完整父页。主控记录限定tsc exit 0，本审查未重复执行tsc。 |

### 保留的两项基线失败

1. `tests/test_manager_history_readback_r1.py::test_exact_panel_selected_without_latest_substitution`：`PLAN_HK_02_PANEL_LATEST_MANIFEST_UNREADABLE`。历史作者在冻结前像完整复现；独立候选组合也复现。未放宽行情panel/date/PIT规则或更换该fixture。
2. `tests/test_manager_announcement_parity_20261008.py::test_missing_original_archive_is_not_empty_connect_selection`：旧fixture预期READY，冻结Mac规则返回PARTIAL。主控原前像126/1与候选160/1日志显示同一失败；已只读核 `connect_selection.py` 原规则在 formal_selection=CANNOT_CONFIRM 时标PARTIAL。该生产文件及fixture均未修改。

完整父页另缺原 `managerAnnouncementAnalysis` / `announcementAnalysis` 依赖；组装的 `researchAttention.ts` 也不是当前Mac caller所要求的完整对应版本。未补stub或拼接旧组件来通过构建，完整UI仍未验。

## 模块边界与最终限制

机械核对tracked diff和新文件准确落在7文件allowlist；仅另有用于测试的 `apps/web/node_modules` 链接，明确不进交付。已把精确2生产/5测试路径写回 `boundary/path_scope.json`。共享 `app.py`、Stage、输入producer、发布入口、安全门禁和Vibe8910没有进入本轮修改。

真实9/30完整原件和同cutoff原输入不在远端，不能从本候选推出其一定通过全部重验。若其source/input/业务投影仍不同，原件继续拒绝并报告具体理由，不自动修改历史SHA。部署、live API、普通UI、两个实际业务日期接续和自然运行均未在本阶段执行。

本审查不解除发布冻结。状态应记录为：`IMPLEMENTED/TESTED/REVIEWED`限上述两处候选及明确测试范围；`INTEGRATED`只限隔离组合；`DEPLOYED/API_VERIFIED/UI_VERIFIED/BEHAVIOR_VERIFIED/NATURAL_VERIFIED`不能从这些工程测试升格为真实运行，保留具体NOT_RUN及 `NATURAL_SLOT_UNVERIFIED`。
