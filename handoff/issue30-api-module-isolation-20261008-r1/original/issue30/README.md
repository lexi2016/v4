# API 模块发布覆盖事故及剩余问题交接（2026-10-08）

用户要求：先记录“为什么单独模块发布会替换整个 API”，把本轮及此前发现的问题列到 GitHub，交由 Chat 写代码。本机已停止后续实现、测试、候选构建和部署；保留未完成修改供参考。此包是交接，不是可部署版本。

## 1. 核心问题及用户期望

**模块代码的边界没有变成发布边界。** 经理、预选池、研究等虽已有不同 router/domain，但 8873 仍从一个整套 app release 运行。实际发布工具切换整个 API 的发布目录；如果候选基于较旧快照，其他模块已有修复就会被遗漏。模块不是在编辑时互相改文件，而是在整体版本切换时发生功能回退。

用户提出 API 按模块拆分。请优先设计清晰的模块 router/service 边界、文件 ownership、共享装配入口与模块差异交付合同；仍保留 V4/8873 统一入口。源码模块化不自动保证发布隔离：即使继续整包原子发布，也必须从当前已接受的集成版本构建并保留非本模块内容。是否需要独立后端进程应基于必要性单独说明，不默认引入微服务、第二面板或多个公开端口。

## 2. 最新事故事实（晚间快照，区别于 #28 上午状态）

- 晚间实际 API：`manager-workbench-r1-mac-20261008-api-r2`，进程当时为 PID 34989、20:27 启动。API app 位于 V4 本机 releases 下该版本的 `app/`。运行身份是采样事实，接手时须重新读取，不可盲用 PID。
- manifest SHA256：`2cc1447a740195c4f50299330d845635ddf762c45eb59586436a527e4f8b75a8`；1016 项 app inventory SHA：`c371c633437e366d28549a94be35741e8d137d2a0836155695c9d125bb427f05`。
- active API plist SHA：`495a9be82e715979d59c03f5c4dd883a7570c55f15b72fa5ed309cacb3914356`。未上传 plist 或完整环境。
- `GET /api/v3/preselection-pools?date=20261008&limit=200` 返回 HTTP 200，但业务状态 `DATA_BLOCKED_EMPTY`，A/HK 都为空；HTTP 正常不代表业务正常。
- 10/8 池实际在已配置的 V3.5 state/data 来源目录；V4 state/data 对应池目录缺失。已有 premarket 30、research 149，合并去重 A=178，HK=100。其他真正空或缺失子池保留各自原因，不能全局阻断。
- 运行 `apps/api/v35_api/app.py` SHA `90a2bf6390c6c0e219aa3d9bb22bc3b3630ecb2d447df494ae69425933424ed7`，缺少 canonical 已有的两处预选池修复：传入 `preselection_source_root=resolved_pool_source`；空本地池分支使用 `if local_pools`。canonical 对应后像为 `435dcedd3beb43bf4a0ccb35ff6fc033ba536a940990c36f5f23358f5492b590`。
- 实际 domain 已接受该 source 参数。不能用“数据未生成”解释这次页面回归，也不能重造 producer 来掩盖读取路径问题。
- 经理发布会话已确认旧基线漏带该修复并冻结继续发布；本机会话没有执行恢复切换。保留经理公告、日期隔离、workspace 更新，不能为了预选池整文件覆盖回旧经理代码。

两处原修复及独立 canary 见 [固定 A 池修复](https://github.com/lexi2016/v4/tree/4ad7cc52257b49470b3004ebfee9649af43189dd/handoff/a-preselection-source-20261008)。该证据不能自动证明晚间 R2 恢复候选已完成。

## 3. 发布层问题清单

| ID | 优先级 | 已确认问题 | Chat 的修复与验收目标 |
|---|---|---|---|
| R1 | P1 | 模块交付最终切换整个 app；旧快照会漏掉其他模块修改 | 定义模块边界和集成规则；本次只改授权模块，共享文件需核前像，非 delta 文件必须保留 |
| R2 | P1 | 候选 manifest/inventory 只证明包自身一致，没有证明包含当前 active 版本 | 绑定 active release、manifest/inventory、逐文件 before/after SHA；旧包即使自洽也应拒绝 |
| R3 | P1 | 原 CAS 主要防切换时 active/plist 漂移，不能发现候选源自过时业务快照 | 构建、准备、真正切换前均验证集成基线；基线变化先重新集成，不直接切换 |
| R4 | P1 | 实际 `_switch_lock` 位于任务私有 evidence 目录，不是所有 API 发布者共用锁 | 所有正式发布入口共用同一 API 指针锁；并发、基线漂移应在 active 写入前拒绝；不能只改一个可绕过的工具 |
| R5 | P1 | 已完成源码修复与实际发布身份脱节，局部功能验收未覆盖其他模块保留 | 验收同时核预选池与经理业务行为，记录实际加载版本；源代码 PASS 不当上线 PASS |
| R6 | P2 | 多个任务有各自构建/切换脚本，canonical、API、Stage、scheduler 不同源根与版本 | 列清 owner、入口与发布指针；复用一条受保护发布路径，避免继续复制临时 publisher；不同 owner 不做整树强行同步 |

实际导致本次切换的代码只读附于 `source/actual_cutover_reference/api_only_cutover_r2_ready.py`，SHA `ddb7c5b5b95aed1e2e9fb8a592503b88ec3966f6e34c9350c47648bb0f97ce4a`。关注 `_load_candidate_release`、`_preflight`、`_switch_lock` 与 apply/rollback 入口。它来自经理任务的 staged 目录，不是 canonical builder；不要只修 canonical 工具后宣称实际入口已受保护。

此前 #28 已独立发现的另一套旧 install/recovery 工具缺陷也须保留：外部 CAS guard 未 pin SHA；候选与恢复两次 link 同时失败可使 active plist 路径缺失、仅剩隐藏 claim，恢复 helper 又拒绝缺失 active。仅在临时故障注入复现，非本机真实服务事故。不要混称它已在晚间 R2 实际发生；实现若复用该路径，需针对性处理。

## 4. 其他已发现问题与最新边界

详尽代码/证据入口是 [Issue #28](https://github.com/lexi2016/v4/issues/28)。下表区分尚未解决、已通过源码验收和未验证，避免把旧报告全部当成当前故障。

| 项目 | 已知事实及当前边界 |
|---|---|
| HK 10/8 阶段输入阻断（P1） | 已核 Top100 行的 signal_date 仍是 9/30，缺合格 10/7 价格信号与 9/30 Connect 资格分日期绑定；不是有效筛选后的 0 只。不得删 validator 或重标历史日期 |
| HK 来源三件套身份混淆（P1） | 上游 artifact/manifest/receipt 三件均已找回；缺的是目标 payload 的上游 SHA 绑定及合格日期证据。本地池 manifest/receipt 不能代替上游 run trio。10/7 close 所指底层来源仍有独立未找回缺口 |
| A 09:25 昨收/涨幅丢失（P1） | #28 上午证据：raw 171 行有昨收，adapter 漏传、持久化 schema 缺字段；API 昨收 null、涨幅 0。未拿到后续修复验收，不宣称仍做了晚间复现；用 100→105 的持久化回读验证 5%，缺基准保持 null |
| A 覆盖与研究字段（P2） | 上午 178 请求中行情缺 6–7 行；研究/新闻源稀疏、quality 字段合同和权威 owner 尚未闭环。不能一概推断行情不存在，也不能缺值填 0 或擅自 alias 分数字段 |
| 执行/自然证据（P2） | 部分有结果或 NATURAL 声明，但缺独立自然验收；不可变历史 manifest/逐 run 代码身份未闭环。10/7 HK 10/100 部分观察不是完整自然成功 |
| 历史 P2 后续已进展 | provenance 日期上界与历史不确定标记两项已在 Mac canonical 集成、独立 38/38 PASS，尚未部署；嵌套 provenance 未知字段约束仍未解决。不能重复把前两项写成未实现 |
| HK trio 后续已进展 | 两个 owner 当前依赖闭包隔离复验各 15/15 PASS，限合成目标；真实日期输入、完整 Stage、部署/API/UI/自然仍 CANNOT_CONFIRM。源码包通过不能解除上述 10/7 来源缺口 |
| 预选池 fallback 回归覆盖 | 先前非空 A 本地池补 HK 场景仍有隔离覆盖缺口；两个旧 fixture 因 provenance 缺失未到 API，不应声称完整回归全绿 |
| 旧 UI/历史项 | #21 的深链接当天已能选日期/阶段，其他旧 UI 项未重新验证；旧 #10/#11/#23 有各自日期/范围，不能原样算成本次复现 |

历史 P2 最新交付：[4c921878 固定说明](https://github.com/lexi2016/v4/blob/4c9218789fe320dd42c1946e5dfb5161d8f8ed2a/handoff/issue28-historical-p2-mac-20261008/README.md)。HK trio 最新交付：[66ed0693 固定说明](https://github.com/lexi2016/v4/blob/66ed06937c3c6235c3b978a2abdfe6607543a798/handoff/issue28-hk-trio-mac-20261008/README.zh-CN.md)。

## 5. 本轮停止时的代码与验证状态

`source/unreviewed_draft/` 是 Writer 停止时的精确源码副本，不写入仓库正式源码根，也不代表推荐架构或已验收实现。共修改五个 canonical 文件：`ops/api_release_integration.py`（新增）、`ops/build_release_candidate.py`、`ops/prepare_api_only_cutover.py`、`tests/test_api_release_integration.py`（新增）、`tests/test_build_release_candidate.py`。另附未改的 `ops/release_candidate_sources.py` 作为依赖参考。

Writer 报告执行：V4 venv Python `-m pytest -q -p no:cacheprovider --basetemp <evidence>/tests/pytest-build-release-candidate tests/test_build_release_candidate.py tests/test_api_release_integration.py`，18 passed。此前 16 pass / 2 fail 为目录 fixture 重复创建与既有 untracked 摘要兼容问题，已由 Writer 修复并复跑。**独立 Reviewer NOT_RUN；正式 TESTED/REVIEWED/BEHAVIOR_VERIFIED 未成立。**

实现只到候选构建/准备 guard。实际切换工具接线未完成；真实当前 R2 + 两 hunk 的 delta/candidate、完整库存保留核验、真实来源隔离 canary 均 NOT_RUN；未改 active release/plist，未重启服务，未改业务数据。API/UI 仍未恢复。不要花力气默认补完这份草稿，可按用户“按模块”要求重新选择更简单的方案，并说明取舍。

本地工作树 HEAD 为 `55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054`，已有大量其他会话 tracked/untracked 修改；本包按文件 SHA 冻结，不以该 HEAD 代表所有实际字节。无权覆盖其他改动。

## 6. 建议交付顺序和验收

1. 明确模块/共享入口/发布 ownership，给可实施的最小拆分方案；避免为简单隔离引入新系统。
2. 修整包过时覆盖：旧包缺 base/delta、错误 before SHA、未声明修改/删除、切换前基线变更、并发发布均在 active 写入前拒绝；所有实际入口必须接入。
3. 基于届时实际最新经理版本，只补两处已知预选池差异；非本批文件逐项保持。预选池返回同一目标日 A=178/HK=100（若源 SHA 已变须重算并解释），不改原始来源；保留经理公告/日期隔离行为。
4. 独立验收后才由获授权本机发布者切换；部署、API、重载 UI、自然时段分别报告。其他阶段问题按独立批次处理，不借模块化改交易/选股逻辑。

保留 `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。V4/8873 唯一入口、A/HK 分离、有效 A 汇总池不过度阻断；不动 Vibe8910，不建平行 producer，不上传原始行情/凭证/账户/完整 plist/venv/dist。当前不授权 Chat 的产物自动部署。
