# 返修结论、证据与验收边界

## 1. 本轮完成到哪一层

两处真实源码缺陷已有失败复现、最小修改和独立前后验收。新增三个测试文件共 20 项，其中 12 项经过 create_app，8 项直接核原生 consumer；在固定基线为 17 PASS / 3 FAIL，在候选为 20 PASS。包含原有测试的四组共 295 项，基线为 265 PASS / 30 FAIL，候选为 268 PASS / 27 FAIL；剩余失败 node 集合完全相同，没有把它们跳过、改成预期失败或计为通过。

本轮的运行是 Linux 上的隔离合成工件测试，实际工厂为 `apps.api.v35_api.app.create_app`，服务类型为 `_v4_manager_research_runtime.service.ManagerResearchJobService`。公告测试使用原 MaterialStore、capture/register/import owner 和实际 ASGI API；HK/计划测试使用原 V2 纯合同 owner、原 master writer、原 research archive store 和原 injected readers。新增测试拒绝外部 socket 连接。没有运行真实采集、Mac owner state、监听在 8873 的现役进程或浏览器。

| 验收层 | 当前状态 | 证据范围 |
|---|---|---|
| 输入包及源码身份 | PASS | 两 ZIP 相同，63 项 payload manifest、51 项 source snapshot 校验；20 项固定 R2 前像一致 |
| 两处修复候选 | PASS | 完整前后源码、最小 diff、3 个独立 RED → GREEN |
| 独立审查 | PASS，限定范围 | focused 20 项（12 项 create_app、8 项原生 consumer）；源码审查结论及额外边界记录见 review/final_code |
| 隔离应用链集成 | PASS，合成输入 | 原 owner/reader/store/API；只证明测试中声明的输入与条件 |
| 全部已执行测试 | FAIL | 268 PASS / 27 FAIL；完整四组日志与每项 node 在 evidence/final |
| 完整 Mac/Python 3.14 发布闭包 | NOT_RUN | 当前解释器 3.12.14；缺少部分原始发布文件/fixture |
| 实际四项业务输入与选股结果 | CANNOT_CONFIRM | 请求包只提供脱敏元数据，没有真实 owner 工件 |
| 部署、8873 API/UI、自然时段 | NOT_RUN | 本轮没有服务操作、业务写入或上线权限使用 |

`CURRENT` 表示保存产品与当前验证输入一致，不等于业务完整、可买或自然运行成功。合成缺输入用例即使 CURRENT，owner attempt 仍为 PARTIAL，原 gaps 保留，四个安全标志保持 `RESEARCH_ONLY=true / production_allowed=false / buy_gate_updated=false / orders_sent=false`。

## 2. 两处根因与最小修改

### 2.1 HK membership 的两种时间用反

原 V2 reader 在 `domains/manager_research_evidence.py` 返回两类时间：`available_at` 来自持久化 publication，`read_at` 是本次读取的 witness clock。固定 R2 的 `connect_selection.filter_cards` 排除了前者、保留后者。带 membership 元数据的材料卡进入完整卡片 input identity，产生两个方向的错误。

第一，所有六件 authority 工件、master 和 research archive 字节不变，只把 reader 时钟从 08:00 推进到 08:01，原代码使保存计划变成 STALE。第二，保持读取时钟不变，将合成 publication 的真实 availability 从 07:02 改为仍早于 cutoff 的 07:03，并用原 canonical 算法重新封 publication SHA，原代码却继续 CURRENT。这两个用例分别独立失败，避免后一个断言被前一个失败挡住。

候选只将排除字段改为 `read_at`，保留 `available_at` 与其它 source lineage。顶层 membership diagnostics 仍显示原 `read_at`；没有更改 V2/root/owner/date/SHA/cutoff gate。修复后两个方向都正确。源时间改变的实验是显式合成输入更改，不是对真实 authority 的重写示范。

### 2.2 定时复用漏比完整日期绑定

`refresh_workspace_plan` 的定时 duplicate 分支原来核 input identity、semantic version、execution kind、owner attempt 和 cutoff，但不核完整 `date_bindings`。在 target=20261009、旧 selection=20261008 的保存产品上，实际 dispatch → ops autorun → 同一个 app service 可能返回旧 run 的 ALREADY_MATERIALIZED；而 selection=20261009 的普通 GET 正确判为 STALE。

候选增加 `existing_workspace.date_bindings == prepared.date_bindings`。不同绑定由原 owner 生成新 run/product/attempt；不改旧不可变产品。MORNING 与 PREOPEN 在相同完整日期、输入与 cutoff 下均保持同 run、同 product SHA、无重写。普通 GET 对不同 selection 和不同 reader 仍返回 STALE，且无业务文件写入。

这不是对附件 `5df99128… → 7c5d9f18…` 的直接归因。该附件的最小独立 owner 与实际 app 使用不同 reader 注入，且 HK authority 尚未绑定；原 stale guard 对真实输入差异的拒绝本来就是正确行为。

### 2.3 保留的额外身份边界

独立审查另检查了把 scheduled owner 的研究 cutoff 和 witness 同时推进 30 秒的场景。现有 `market_screen.data_context.research_cutoff` 参与输入身份，因此会生成新 run。两项最初“应复用旧 run”的探针为 FAIL；后续分类检查确认变化来自实际研究 cutoff，而非仍残留的 membership `read_at`。源码保持原样，完整探针记录保留。

本包只证明同 cutoff 的重试复用以及按保存上下文的 GET 稳定；**不承诺跨 cutoff 的所有相同 source bytes 刷新都复用一个 run**。若原 owner 需要更强幂等定义，应先明确新研究时点是否构成新输入，不能直接剥离 PIT 上下文。

## 3. 四项原业务缺口：owner、consumer、接受条件

| 冻结问题 | 原 owner 与已确认 consumer | 本轮证据 | Mac 原 owner 接续与接受条件 |
|---|---|---|---|
| 公告未导入 10/09 选股 | 原 catalog/body capture、真实独立 Reader/Reviewer、register-handoff/import → announcement_analysis/workspace_announcements → workspace daily channel | 完整 create_app 导入合成已注册产品后，原 SELECTED row、product/run/manifest/import receipt SHA 被消费；错 publication、损坏 Reader 字节仍拒绝。HK/screen 缺项和另一路 review NOT_RUN 不全局阻断已导入分析 | target=20261009、publication=20261008 的真实 capture、Reader、Reviewer、不同身份及原 SHA；同 manager root 原 import 后 GET VERIFIED/CONSUMED。缺原工件保持 CANNOT_CONFIRM，未评估保持 PARTIAL |
| HK Connect 目标成员未验证 | 原 HK universe V2 owner → domains.read_universe_evidence → connect_selection.read_scope/filter → workspace/channel | 完整合成六工件链可到 OWNER_VERIFIED；坏 root/日期/owner SHA/publication/manifest/cutoff 拒绝 | 明确目标日 20261009 原 authority root、contract owner root/SHA，artifact/manifest/receipt/current/capture/publication 同根可验证。上一完整 session 的 capture 只作诊断，不能替代目标 V2 |
| 超跌缺 10/08 master | 原 security-master/HK02 panel owner → create_app screen root → workspace_plan.read_rebound_screen | 精确 10/08 master/panel 可消费；较新 10/09 entry 不替代。即便数值足够，未证实 volume units/scale 时仍 pending | 同一 screen root 的 20261008 exact master index entry、snapshot、manifest/receipt、可用 panel 与所需 60/5 session，所有 availability 满足真实 cutoff；还须正式支持的全六日量纲/scale 证明 |
| 保存计划与当前输入不同 | 同一 create_app 注入的 ManagerResearchJobService.refresh_workspace_plan → 原 immutable product/journal → GET | 同绑定同输入刷新后 CURRENT；不同 reader/日期/持久化 source identity 仍 STALE。修复读时钟与定时日期漏比 | 输入与 reader 配置固定后使用原 owner 刷新；GET 比对相同 date bindings、run、product SHA、input identity、同 run attempt。不能强改 consumed/status 或迁移旧产品标签 |

### 超跌还存在正式 reader 能力缺口

`workspace_plan._screen_panel_volume_evidence` 与 `_screen_supplement_volume_evidence` 当前均保留 NOT_PROVEN。native observation v1 证明原始字段和观察时间，不能证明继承历史的单位/scale。代码明确要求未来正式 owner attestation 通过新的 reader contract 接入；随手添加 `SHARES`、`LOTS` 或 lot_size 不能证明全六日比较口径。

因此，补精确日 master 解决的是读取缺口；当前不保证严格选股完备。不能把无 strict rows 的 0 当成全市场 VALID_EMPTY。这个能力缺口应由主控和原 owner 在已确认来源范围内单独闭合，本次没有制造来源证明或新增平行 producer。

### 公告 CLI 版本必须核对

上传的历史 runner SHA 为 `bfb853fb982e0b2da1024fa942ae9dc5d67fa88a8d112f46054608641129c1ee`；其 readback 将完整 API 返回缩成薄 product，遇带 handoff 四绑定字段的 receipt 会报 `ANNOUNCEMENT_OWNER_IMPORT_RECEIPT_HANDOFF_BINDING_INVALID`。

固定 Git 支撑中的 CLI SHA 为 `aee0e5c31f30b296864a7ad81263fbc748b65cb9b4d443f83a756019cbc94a38`，已调用原 `validate_owner_analysis_readback(result)`，对同一 R2 owner GET 可通过。本轮没有重复修补已修好的 CLI，也没有将历史 runner 覆盖进候选。Mac 必须核实际执行字节；未核仍 CANNOT_CONFIRM。

## 4. 完整测试账本

下表来自最终统一 API 支撑的两树独立进程，所有原测试字节未改。每组准确 argv、cwd、环境、测试 SHA、失败 node 和日志 SHA 在 `evidence/final/{baseline,repaired}/*.json`。

| 测试组 | 数量 | 固定基线 | 候选 |
|---|---:|---:|---:|
| 新增应用工厂与原生 consumer：公告 1 + HK 12 + plan 7 | 20 | 17 PASS / 3 FAIL | **20 PASS** |
| 相邻 owner、精确页面日期、定时派发、HK/volume 合同 | 113 | 112 PASS / 1 FAIL | 112 PASS / 1 FAIL |
| 请求包四份原 regression specs | 103 | 78 PASS / 25 FAIL | 78 PASS / 25 FAIL |
| 既有 announcement parity + handoff | 59 | 58 PASS / 1 FAIL | 58 PASS / 1 FAIL |
| 合计 | **295** | **265 PASS / 30 FAIL** | **268 PASS / 27 FAIL** |

独立审查的复跑与边界探针不重复加入这 295 项。已知 Starlette TestClient/httpx deprecation warning 原样保留。

### 27 个剩余失败的处理

| 分类 | 数量 | 结论 |
|---|---:|---|
| 发布快照缺 apps/__init__.py | 13 | supervisor fixture 复制即失败，真正 binding 断言 NOT_RUN；冻结 tree 无已确认原字节，不造空文件 |
| Python 3.14 入口门禁 | 1 | 本环境为 3.12.14，原 CLI 显式抛 PYTHON_314_REQUIRED；未改门禁 |
| 缺精确冻结 observation fixture | 1 | V4_INPUT_ROOT 未绑定且 FROZEN_SELECTED_FIELDS.json 未提供；不构造替代真实冻结子树 |
| 旧 V2/calendar fixture 与当前 admission 合同不符 | 3 | Issue8 两项缺 V2 membership_semantics；parity 一项缺 calendar_applicability；当前门禁正确拒绝 |
| catalog 合同版本差异 | 2 | 旧 master 交集断言与 source-identity reference 合同不同；后者仍不授予选股/BUY 资格 |
| plan legacy/mock/journal 断言 | 7 | legacy 缺同 run owner journal 1 项，矛盾 mock envelope 5 项，真实严格 journal 顺序差异 1 项 |

真实故障注入确认 journal 在最终读回失败时可能经历 `RUNNING → SUCCEEDED_EMPTY → FAILED`。所有已测真实故障最终没有成功返回，后续真实 GET 拒绝消费；但“任何时刻都不出现成功 journal”的严格断言未满足，继续保留 FAIL。并发观察、进程中断和自然 I/O 故障不是本轮已验证内容。详见 `review/baseline_triage/TRIAGE_REPORT.md`，不能把全部失败统称为无关旧测试。

## 5. 源码和运行身份不混用

固定 R2 原路径是 `/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_THREE_CHANNEL_DEPLOY_20261009/candidate/three_channel_release_r2/app`。它是附件记录的候选，不是本机或 Mac 现役身份。唯一 canonical 项目仍为 `/Users/lexi/Desktop/学习/v4_app`；API 与 Stage 的真实运行根、PID、启动参数、release/config manifest 和端口身份由 Mac 原主控另核。

本轮 Linux 运行根分别为 `/workspace/scratch/0e089a11ee60/four_function_gaps/work/baseline/app` 与 `.../work/repaired/app`。附件并非完整可运行发布，测试额外使用冻结 Git 支撑、30 份原通用 namespace helper、原 daily_materialize，以及已逐 blob 校验的 API support 对齐。支撑仅用于这两棵隔离测试树，不进入生产补丁，也不证明 Mac 采用同一完整组合。

最后严格全文件比较曾因 CPython cache 字节变化返回失败，原记录保留；之后逐源码字节核对确认非 cache 源码未变，前后生产差异仍仅两个允许路径，20 个固定 R2 前像匹配。见 `evidence/final/source_integrity.json`。缓存不进入交付，不据此改判测试结果。

9/30 用户所述独立成功入口 receipt 本包未定位，保持 CANNOT_CONFIRM，不否定其存在。已提供的 9/30 US attention 固定范围 READY、10/07→10/08 公告 PARTIAL，以及 10/09 孤立 mapping 4/33 reviewed/非全市场记录，均不能替代 10/09 四项完整验收。
