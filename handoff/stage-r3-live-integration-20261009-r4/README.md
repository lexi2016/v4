# R4：把已验收的 Stage 研究结果接入现役 API/UI

本包基于固定回传 `137431f5de3917ff4526784351f5638e115061e5`，完成现役 Issue32 页面适配、精确研究读取绑定与历史保留、Stage 发布工具接线。算法和真实研究 run 沿用已在 Mac 验收的 R3 `9a0c3f318a438b386d69a8385ce644ea18a31dfb`。

本包交付完整代码、逐文件前后 SHA、最小补丁、可复跑测试和落地命令。**R4 在 Chat 环境的实现/测试，与 Mac 接入 8873、浏览器及自然时段验收分别记录。** 本包不把 R3 的 352 项或先前隔离 HTTP/UI 回执重新称为 R4 现役验收。

## 修复内容

### 1. 使用现役页面的精确前像

三个 UI 文件均从固定 Mac 前像 SHA 对应的 Git 字节开始修改，操作均为 `modify`。`StageExecutionEvidencePanel.vue` 已存在，不能再按 absent/add 处理。完整 `App.vue` 保留经理导航、原请求、已有精确回补校验及事件行为；增加同日期、阶段、市场、run、artifact、算法/原产物 SHA 的展示判断。已经验证的研究结果可显示选中数、行情覆盖、名单来源限制和执行证据状态。

UI 构建工具先验证 prepared source manifest，再在**新的可写副本**中执行该现役 UI 的 `npm ci` 和 `npm run build`，核验锁文件、完整非 dist 源码图、原 HTML 入口、入口引用资源和完整静态文件清单。输入的只读目录保持原字节和权限。

### 2. 研究读取绑定保留原历史根

新增 `stage_center/research_read_binding.py`，通过现有 `GET /api/v3/workbench/stage` 路由接入。仅有明确生成、验证的 `approved_research_read.json` 与 `.sha256` 配对文件时启用；缺省仍走原读取路径。

普通请求 `?date=20261009&stage=STAGE_0930_0935` 可以同时读取已批准的 A/HK 结果。其他日期和阶段继续使用原配置历史根，原精确 BACKFILL/WATCH_ONLY 读取合同保留。没有把 canary 产物复制进 live state，也没有把唯一历史根改到 canary 目录。

绑定校验覆盖固定 run manifest、R3 SOURCE_MAP、Stage 候选源码 manifest 与逐文件 SHA、owner/current/history receipt、每市场 selection 三件套、run/artifact/算法/原产物 SHA、加载中的 reader 源码和安全字段。单市场产物失效只使该市场降级；共享绑定失效则明确拒绝该研究读取。缺自然运行证明不阻止有完整产物绑定的研究行显示。

### 3. 从当前完整 App 构建受约束的 Stage 发布候选

扩展固定 Issue30 guard 及两个既有 wrapper，新增精确 Stage 所有权、三个明确共享路径和完整静态 before/after 清单。源码删除仍不允许；只有完整静态差异证明覆盖的旧 dist 文件可移除。经理、预选、其他页面及非 delta 文件/目录权限由原完整 inventory 继续保护。

`prepare_live_release.py` 自动验证当前 App、prepared UI、构建回执和真实研究绑定，生成具体 change set、独立 Git source、delta receipt、完整 release candidate 及 manifest。Mac 不需要填写 `SOURCE_ROOT` 占位符、手写 delta JSON 或新增业务逻辑。

原通用 builder 的隔离经理状态计划仅作为构建证据保留，标记 `publication_eligible=false`。Stage 使用单独生成且再次核验的计划，保留当前经理状态根与 Stage 历史根。Stage 发布入口复用原 Issue32 发布器的共享锁、精确 preimage 替换和恢复流程，原脚本和冻结常量保留。准备和检查不启停服务；实际执行与回滚需要明确命令及精确 SHA。

## 源码范围与来源

| 范围 | 交付 | 边界 |
| --- | --- | --- |
| `after/api` | 4 个完整文件 | app 路由、研究 binding；consumer/evidence 与已验收 R3 同字节 |
| `after/ui` | 3 个完整文件 | 当前 Issue32 的 App、现有 panel、runtime 类型 |
| `release_tools/after/ops` | 3 个修改、6 个原样依赖 | 固定 Issue30 release chain 的最小 Stage 扩展 |
| `tools` | 准备、构建、测试、包校验与发布命令 | 新候选/回执目录；没有在 Chat 操作 Mac 服务 |
| `test_support/r3` | 61 个原样源码/测试依赖 | 仅供离线回归，不是可发布的另一份 Stage App |

所有完整前像、后像、字节数、来源和 SHA 在 [SOURCE_MAP.json](SOURCE_MAP.json) 与 [TOOLS_SOURCE_MAP.json](TOOLS_SOURCE_MAP.json)。最小补丁在 [patches](patches)。`verify_package.py` 将补丁与完整前后像重新生成比较，并验证所有文件清单、测试定义及固定用例身份。

便于人工核对的完整前后 SHA 表见 [FILE_IDENTITIES.md](FILE_IDENTITIES.md)；新增交接命令与原样 publisher/guard 引用见 [HANDOFF_TOOL_IDENTITIES.json](HANDOFF_TOOL_IDENTITIES.json)。Mac 运行后才会产生的绑定、delta、发布 manifest、静态 inventory 与操作回执 SHA 均由工具真实生成。

现役 App 前像根：

`/Users/lexi/Desktop/学习/agents调试/V4_ISSUE32_MAC_20261009/candidate/issue32_preselection_api_actual_r4/app`

canonical `/Users/lexi/Desktop/学习/v4_app` 存在独立差异和 dirty 状态，本包不向它应用整文件，也不使用其源码替代现役 UI。这里的前像证明是“固定 Mac 回执 SHA 与 Git 字节一致”，没有声称 Chat 直接读取了 Mac 文件。

## 固定研究结果身份

| 字段 | 已验收 R3 身份 |
| --- | --- |
| 日期 / 阶段 | `20261009 / STAGE_0930_0935` |
| backfill namespace | `85e29661ecd848fe9b8344ea59279e86` |
| A run | `run-2688466a1ae4464ba7237f0b` |
| HK run | `run-cfbdc9b36a7308da178d193a` |
| run manifest SHA | `9b5df949141ed1533cb7a71e2c46bebe341bea663f5f966bda16225754e89857` |
| 行数 / 行情覆盖 | 各 10 只；A 206/216，HK 695/695 |
| 运行性质 | `CURRENT_DAY_RESEARCH_REPLAY`；手动研究回放 |

上述行数和实际行情覆盖来自用户同步的 [R3 Mac 回执](references/R3_LOCAL_INTEGRATION_RECEIPT_20261009.md)。本次离线测试生成的合成 fixture 单独记录，不充当这批真实行情数据。

HK 证券资料仍是 10/8 参考名单、10/9 15:38:41+08:00 当前资料快照：`stale_universe=true`、`CURRENT_DAY_RESEARCH_ONLY`、港股通成员资格 `CANNOT_CONFIRM`，不能称为正式 `HK_CONNECT_D1_TOP100`。本包没有用证券资料替代报价，没有把下午采集标成 09:35 行情，没有改变正式 STRICT 默认合同或原四路算法/排序/权重/Top10。

## 验证与落地

冻结后的完整包，作者 **479/479**，独立复制包 **479/479**，零失败、错误、跳过；API 129、Vue 70、发布核心 152、整合 86、验收 runner 42。两次均重新生成 API→Vue 合成数据链并通过，不复用旧测试结果。四个独立发布 HTTP 反例也已全部拒绝并恢复前像。

最终机器结果、明确的未执行项及独立检查见 [VERIFICATION.md](VERIFICATION.md)。可直接执行的 Mac 顺序、API/UI 同 run 验收和回滚见 [MAC_STEPS.md](MAC_STEPS.md)。

机器交付摘要见 [FINAL_RECEIPT.json](FINAL_RECEIPT.json)，独立审查见 [INDEPENDENT_REVIEW.md](docs/INDEPENDENT_REVIEW.md)。[FINAL_SOURCE_FREEZE.json](evidence/FINAL_SOURCE_FREEZE.json) 记录最终源码、工具与测试和已复跑副本之间的字节一致性。

包的校验和用于检测缺件与字节漂移。可信入口是交付的固定 Git commit / 外部 ZIP SHA；自行同时改写源码和清单不构成独立验收。

`RESEARCH_ONLY=true`；`production_allowed=false`；`buy_gate_updated=false`；`orders_sent=false`。本包不更新买入门禁，不发送订单。正式 HK D1/资格/PIT、自动时段恢复和自然验收继续单独标记为未确认。
