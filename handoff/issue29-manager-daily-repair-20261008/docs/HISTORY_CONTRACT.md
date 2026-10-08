# Issue #29 B：历史读取合同诊断与最小兼容方案

## 结论

已确认早退原因是**把整组源码的字节身份同时用作历史产物的硬兼容门槛**。保存的指纹存在且不同于当前指纹时，reader 在业务原 owner 与 PIT 重验前直接返回 `HISTORY_READER_VERSION_CHANGED`。没有保存指纹的 legacy 计划却允许完整重验。因此，当前拒读只证明源码集合身份变化，不能证明旧计划损坏、当日未成功或业务语义已不兼容。

该缺陷可以做模块内兼容修复：保留源码指纹和缓存失效机制，以明确的合同版本与完整原截止时点重验决定历史可读性。只有重验全部通过才返回历史计划。不能仅移除判定，不能把已知旧 SHA 放入白名单。

本诊断只读本地及 GitHub 源码；没有读取本机原计划、运行 Mac 服务或正式 owner，也没有修改现有 `candidate/` 或 R1 交付。

## 1. 已核源码身份和直接调用关系

固定提交：`b22836ef3f8fcc6b9218f3422a9bcd7aa61152e9`。

| 文件 | Git blob | SHA256 |
|---|---|---|
| `handoff/manager-workbench-repair-20261008/after/v4/manager_research/workspace_history.py` | `4901ce1fb9ab2f73517275ad89fd187b27bff375` | `da5e1223326631cc9070c3059ca606bac3840ef468ad5c06f2f3a51534f82ec1` |
| `handoff/v4-running-source-20261005/canonical/v4/manager_research/workspace_read_control.py` | `2ef88175e1a232d669dc23a05f35c48e27309bcf` | `491e3569e8f00586ca6f4e9982e182584d2f2a0437f83da66767b7ffdbf1fb25` |

两文件均从固定 GitHub blob 读取完整字节并重算 SHA。核对副本只保存在原诊断暂存区，未随本包重发；固定来源见上表，待安装的实际变更后像见本包 `after/`。

`workspace_read_control.py:21,78–129` 定义：

1. 合同名固定 `20260923.workspace-history-read.r1`。
2. 排序枚举整个 `v4/manager_research/*.py`，再加 29 个固定依赖。
3. 固定依赖包括 Stage scheduler/contracts/calendar/candidate_input、市场及 US 日历、证据/研究 domain、原 IO/store/安全层、证券主表及 `DEPENDENCY_MANIFEST.json`。
4. 依次混合相对路径、文件内容 SHA256；缺失条件模块以 `MISSING` 编码。最多 128 路径，单文件 8 MiB，总计 64 MiB。
5. 注释和未改变读取语义的修改也改变指纹；条件模块出现/消失也改变指纹。

`workspace.py` 原 writer 把该指纹写进产品顶层 `read_contract_sha256` 并纳入原产品 digest。合同名在 `workspace.read_context.contract`，不是由这个 SHA 本身可逆恢复。

`workspace_history.py:249–280` 修复前顺序为：原计划选择及结构/安全/SHA/window 检查 → 精确 run 的 owner attempt 校验 → semantic_version 精确相等 → 非空 reader SHA 精确相等 → 保存材料 PIT → 原 owner `_compute_workspace(include_saved=False, context=原ctx)` → input_identity 精确相等 → 14 个冻结业务字段相等 → 重验结果 PIT。

所以，已知不相等会阻止后面实际用于判定历史内容是否合法的检查。

## 2. 三个观测指纹的证据强度

| 指纹 | 当前可验证来源 | 本轮能确认什么 | 仍缺什么 |
|---|---|---|---|
| `9cb7ed0bf2b09b2cb8b1e7a3658cd7ca187deda248fcfaa3d7fbc910e9a64d24` | Issue #29：9/30 原 run `ba13fba330464300b760fe940ba579a1` | 问题报告明确标识为原计划保存值 | 该 run 脱敏 header 与原 release 指纹所覆盖的逐文件清单 |
| `cab2d2061ca8c8498a89363d148cf004517e9f5f8a06d6dbfe50fdb502d3ba88` | Issue #29：较晚手动产物 | 问题报告明确标识为另一保存值 | 原 run 身份、header、原 release 逐文件清单 |
| `fc10fef5a0a8fb415dbb172f3748ddd5e663d41360b24aaea332ad2b89b44b42` | Issue #29：R2 计算值 | 固定现场观测，不是本轮远控重算 | R2 同一加载 root 的完整指纹依赖清单，含条件缺失项 |

本轮 GitHub code search 对第一指纹返回零条且 `incomplete_results=true`，不能把搜索结果当不存在证明。固定 `b228` 树及其 Mac source/status/file_map 未附上述完整历史依赖集合。协作检索 #8/#22/#24 暂未发现这三个完整指纹对应的清单。因此不能从三个 SHA 反推出哪个具体改动造成 `9cb→cab→fc10`，也不能宣称完成该三者的字节重构。

## 3. 可重现的机制证明

以下为本地机制诊断摘要：原诊断脚本 `inspect_fingerprint.py` 只用 AST 读取已核算法常量，以先前组装的 baseline 与 R1 candidate 源码字节计算指纹，不导入或执行应用模块。该脚本和完整 `fingerprint_diagnosis.json` 暂存清单未随本包重发；这些摘要不是现役 Mac 指纹证明。新增回归直接调用原 writer/reader 验证相同机制，见本包测试和独立审查。

- 组装 baseline：`bf24dac0e5330eea5b4b8402bd3b907eec113b4af138673a55c1bbcd7a7f6d94`。
- 先前 R1 candidate：`969af5b50343329c79d747c2da9ba77a834f43b5c929f4d131088b98f653c058`。
- 仅在内存追加一行 history 注释：`1fa8ce4aab7b9675ce8201bbf43aba6415eeaad851ba8a78fcbd002ebc2840fa`；没有写入应用源码。

baseline→R1 有 9 个指纹成员变化：`connect_selection.py`、`plan_owner_dispatch.py`、`service.py`、`workspace.py`、`workspace_announcements.py`、`workspace_daily_channels.py`、`workspace_history.py`、`workspace_plan.py`、`workspace_plan_autorun.py`。其中新调度/展示辅助模块同样被 glob 自动纳入。

两组中 `workspace_semantics.py` 的 SHA 同为 `dc8d1d330e4fdacf2ef7169a7ac62874bfd3e2658f8b4bcff0773e06e32c4f7f`；`workspace_projection.py` 同为 `027d855613e675e1f569b401b9a8344e40766b88c31e987e791d05a0b3a2f200`；`workspace_read_control.py` 也相同。这里证明的是**核心文件及显式版本未变仍会出现指纹差异**，不是证明所有其他业务行为等价。这两份组装树均不冒充 9/30 或当前 Mac R2。

## 4. 已实现的模块内修复

本项生产改动仅限 `workspace_history.py`，沿用原 `_compute_workspace` 和所有读取 owner。`contract_identity()`、原 memo key、数据 producer、Stage、BUY、日历、存储格式均不改。

1. 验证保存指纹类型及 64 位小写 hex 格式。区分无指纹 legacy 与格式损坏。
2. 对带指纹的跨源码历史读，验证**保存原件**的 `workspace.read_context.contract`，只接受明确支持的同一 r1 合同；不同/未知合同给具体不兼容原因。不能拿当前 API 响应的 r1 合同名反证旧原件合同名。
3. 指纹不一致进入显式 `SAME_CONTRACT_SOURCE_CHANGE`，保留保存值和当前值。它表示需要重验，尚未成功。无指纹 legacy 保持既有完整重验路径。
4. 原 owner attempt、schema、digest、安全旗、原 cutoff/window、semantic_version、保存材料 PIT 全部保持原规则。继续以原 ctx 做完整 owner 重读；不取今天/另一天/latest 替代输入。
5. input_identity 和 `_BUSINESS_FIELDS` 仍逐值相等，不删字段、不忽略差异、不重写旧 SHA，不把新增证据包装进旧计划。差异保留 `HISTORY_SOURCE_INPUTS_CHANGED` / `HISTORY_FROZEN_PROJECTION_CHANGED` 等具体原因。
6. 重验前后读取当前源码指纹，若期间改变则失败，避免把两套源码的结果拼成一次验证。
7. 全部门禁通过后，仅在返回的历史 `read_context` 增加兼容性证据：原/current SHA、合同名、验证方式及结果；原 run/plan SHA 和 cutoff 继续由现有 plan_product/read_context 字段提供。不写旧产品、不改生成时间、原 attempt 状态或 daily/natural 成功身份。

原 frontend `validateReadContext()` 已接受 r1 合同及额外字段，并继续要求历史 consumed/current 与严格 PIT。本次可以保留 UI 代码不变；完整 API/UI 验证仍由实际 Mac 集成执行。

**限制：**真实 9/30 原件如果在新原 owner 下不能保持相同 input_identity/冻结业务语义，通用同合同重验不会强行放行。届时需要读取具体差异及原版本，做显式、可审计的版本 adapter；不能扩大这里的兼容范围来“凑通过”。如果原件保存合同名缺失，也应把该实际缺口明确返回，而非猜测。

## 5. 针对性回归设计

| 场景 | 必须观察到的结果 |
|---|---|
| 同指纹、同输入 | 原历史读成功，记录原 run/cutoff，仍执行 owner 重验 |
| 同 r1、不同源码指纹、同输入同业务 | 先复现旧版早退，再验证兼容候选走完整 owner/PIT 重验后成功 |
| 对 included source 只改注释 | 原指纹变化；无代码语义变化仍需并通过完整重验 |
| 同时覆盖两个历史日期 | 各自保留日期、run、cutoff，不跨日回退 |
| malformed SHA/未知合同 | 重验前拒绝，给可区分的原因 |
| semantic_version 改变 | 保持 `HISTORY_SEMANTIC_VERSION_CHANGED` |
| 源输入身份变更 | 保持 `HISTORY_SOURCE_INPUTS_CHANGED`，不能只比候选数 |
| frozen 股票/理由/summary/announcement 变更 | 保持 `HISTORY_FROZEN_PROJECTION_CHANGED`，不得靠重封自校验通过 |
| 原或重验后 published/available/retrieved 晚于 cutoff | PIT 拒绝 |
| owner attempt 缺失/类型错/已失败/晚截止 | 保持原精确 attempt 门禁，不能借跨源码兼容放行 |
| 重验过程中源码指纹变化 | 新明确拒绝，不返回 consumed |
| 无 SHA 的 legacy manual | 保留原 legacy 全量重验和缺口状态 |
| 后写 latest 遮挡合法早期 run | 仍按原精确日期和盘前边界选择合法 run |
| 读取前后文件快照 | 原计划、latest 与 journal 全部字节不变；无新增产物 |
| 历史失败的 US 原 cutoff 只读复核 | 保留现有独立观察，不把失败计划当成功、不提升为映射完成 |

既有测试 `test_reader_version_change_rejects_saved_product_before_replay` 的预期需要按新合同明确替换为“同合同全量重验”；其它结构/SHA/PIT/owner/大小边界断言保持。不得批量跳过旧测试。

另有独立已知边界：history `_MAX_PLAN_BYTES=32 MiB` 与 #24 原 store 的 320 MiB 特定计划上限不同；本问题并未提供被拒的 9/30 原件大小，不能将它当本次已确认根因，也不在此顺带放宽。

## 来源

- [Issue #29](https://github.com/lexi2016/v4/issues/29)
- [固定 R2 history](https://github.com/lexi2016/v4/blob/b22836ef3f8fcc6b9218f3422a9bcd7aa61152e9/handoff/manager-workbench-repair-20261008/after/v4/manager_research/workspace_history.py)
- [固定 read control](https://github.com/lexi2016/v4/blob/b22836ef3f8fcc6b9218f3422a9bcd7aa61152e9/handoff/v4-running-source-20261005/canonical/v4/manager_research/workspace_read_control.py)
- [Mac source map](https://github.com/lexi2016/v4/blob/b22836ef3f8fcc6b9218f3422a9bcd7aa61152e9/handoff/manager-workbench-mac-completion-20261008/file_map.json)
- [Mac 分层状态](https://github.com/lexi2016/v4/blob/b22836ef3f8fcc6b9218f3422a9bcd7aa61152e9/handoff/manager-workbench-mac-completion-20261008/evidence/status.json)
