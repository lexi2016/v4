# V4 经理工作台 API / UI 返修候选 · 2026-10-10 R2

**交付级别：PROPOSAL_ONLY。** 本包交付固定源码上的修复候选、完整改后文件、最小补丁、回归测试与离线证据。它不构成部署包或现役 API/UI 验收通过；全项目测试、类型检查和构建仍有失败，详见 `evidence/final-validation.md`。

本轮基于用户的 `V4_MANAGER_LIVE_UI_API_PROBLEM_20261010.zip`，SHA-256 `c8e8f42a108d144ab2a8182c516b7c0173f55cde8566d3d630709151303b5da4`。输入包 CRC、57 项源码清单、19 项证据清单和 evidence contract 已核对；外置与包内 `PROBLEM_REPORT.md` 字节相同。原包保持原样。

## 1. 本轮修复

| 问题 | 候选行为 | 验证边界 |
|---|---|---|
| 全局 manifest 指纹使未变的材料一并 stale | 只在原 reader 已验证的 V35 archive `source_refs` 边界，将顶层全局 `manifest_sha256` 留作来源记录；语义身份仍绑定实际来源、日期、路径、payload/receipt SHA、可用时间和内容 | 无关 registry 项变化保持身份；实际消费内容变化或无法验证时仍拒绝消费 |
| 已物化催化产物仍存在第二处 manifest 耦合 | 回放只放行两个已验证 binding 的顶层 manifest 差异，使用冻结来源记录重建原投影；保留完整快照、卡片、native witness 和 PIT 等值校验 | 独立审查先复现失败，再用原探针验证修正；没有放宽 archive 内容/时钟 schema |
| stale 缺少可定位差异 | 新计划保存分量指纹，读回附加 `MATCH / CHANGED / CANNOT_CONFIRM` 诊断；变化项包含来源日期、相对路径及前后指纹，provenance 变化单列 | 不展示原始 payload；不把诊断作为绕过 current-run、owner、日期或 stale guard 的通行证 |
| 每日三路摘要没有接线 | 在现有 panel 的实际 `render(value)` 中消费同一已校验响应的 `daily_channels`，前置 ANNOUNCEMENT / HK_CONNECT / OVERSOLD 状态、日期、owner/run/product、待核与 gap | 六组实际后端 service/router 合成 DTO 经过原 validator、请求解析和实际页面 mount；不是 Mac 浏览器验收 |
| 美股两个状态范围不清 | 显式区分“美股输入评估／完整度”与“每日 US-HK 已审映射”，由响应给出已审关系数 | 四项关系的 `VALID_EMPTY` 不代表全市场为空，也不代表完整美股输入 |
| 原始观察先于研究结果 | 计划状态、三路摘要和核心研究结果前置；原始观察放入默认折叠的完整审计区 | 测试保留并可展开全部 201 行；没有截断、改写或另建选股输入 |
| 日期和手动刷新读回 | 来源/选股日、计划日和公告 publication 日分开绑定；显式公告日期优先，缺省时保留原 owner 的前一 HK 日逻辑；手动 POST 后读取所选 canonical GET，取消或过期响应不得覆盖当前页 | 原有两项旧请求行为断言保留为 FAIL/合同冲突，未修改旧测试掩盖差异 |

`source_root_sha256` 的显示文案为“来源根路径指纹 SHA-256”：它是路径字符串的指纹，不冒充源码目录内容 SHA。

## 2. 源码与实际运行身份

| 身份 | 记录 |
|---|---|
| 固定 Git 基线 | `lexi2016/v4@c0fc35c7b39502f49e43c2e75139dad7822091cf`，tree `21e0e3ae3cd9434ae95400b4ed2abbd0c16ff1bd` |
| 用户包报告的已部署 fused release | `stage_r4_manager_r2_owner_input_r1_fused_r1`；PID `10321`；release manifest `fd7f21af0205b9d25a8ab5d33592aff42bf76c0419799b7c1724b94a286aeb86` |
| 唯一 canonical 项目 | `/Users/lexi/Desktop/学习/v4_app`；本轮未连接或修改该 Mac 项目/运行进程 |
| 本轮实际测试候选 | `/workspace/scratch/0e089a11ee60/live_ui_api_20261010/work/candidate/app`；Linux 隔离源码导出 |
| 配对基线 | 同任务目录的 `work/baseline/app`；生产源码保持冻结，只加入完全相同的测试文件用于对照 |
| 本轮 Git 分支 | `chat/manager-live-ui-api-repair-20261010-r2`；独立追加交接路径，保留原冻结分支及其他修改 |

**不要将旧候选、canonical 快照、API 快照或当前 Linux 测试根混称现役。** 本包新增修复没有部署。

同步前发现拟用 R1 分支已存在于 `8c8e35d9d53431c9082dec49f4976e363c275765`。本轮保留该并行交付，使用 R2 独立分支/目录；没有合并或改写 R1，其候选也没有替代本轮固定基线。此前执行证据中的本地 R1 路径是改名前的实际命令记录，最终包会在 R2 路径再次核验。

生产改动共 **9 个文件：8 个替换、1 个新增**。每个文件的完整前后 SHA、来源与字节数在 `SOURCE_MANIFEST.json`；完整改后源码位于 `after/`，原始前像位于 `before/`，最小生产补丁为 `PATCH.diff`。

其中 6 个前像直接来自 `code/current_fused_app`。`workspace_projection.py` 来自相同字节的固定 Git/包内 previous-reference，SHA 与包内 `root_cause_report_20261010.md` 报告的 fused SHA 一致。额外修正的 `archive_catalyst_inputs.py` **只有固定 Git 前像**，SHA `968b26e66cb041adcf503e251c2c710728ce33638627123ff618357398b37b71`；其已部署 Mac 前像仍为 **CANNOT_CONFIRM**，必须由 Mac 主控先核对，不能盲目覆盖。新增 `workspace_identity.py` 要求应用前不存在同名并行修改。

原 `research_lane_source.py`、`existing_materials.py`、`catalyst_observations.py` 和 `contracts/research.py` 字节未改。测试所需旧源支持、固定 Git 路径、SHA 与仅为测试导入补充的 `_namespace.py` 分类记录在 `support/TEST_SOURCE_INVENTORY.json`；这些辅助导出不冒充完整 Mac 发布源码。

## 3. 计划身份迁移与历史证据

新身份合同为 `CONSUMED_ARTIFACTS_V1`。新 workspace 附带分量元数据，必须与保存计划一致且可验证才可复用；旧计划缺少元数据时，保持不消费并显示 `CANNOT_CONFIRM`。两侧都是旧式内部 DTO 时，保留旧的精确身份/owner 守卫，并省略可选诊断。这里没有改写 sealed run、复用旧身份或强制 `CURRENT`。

因此，Mac 侧应用并验收这组源码后，旧计划可能需要通过原 owner 的合法刷新生成新合同产物。该操作未在此环境执行，也不由本包脚本自动触发。

输入证据中，目标日 `20261009`、公告日 `20261008`、观察/回看日 `20261010` 必须分开。同一 run `3bc75d1beea24036850b1af0f4d5f395`、同一产品 SHA `38eaad4b3d8adfd4738fa0bb4e6ef5ab969414447450e485614f384f48aab991` 曾在紧邻 POST + GET + GET 中为 CURRENT，随后浏览器 GET 为 STALE_INPUTS_CHANGED。输入包证明全局 manifest 是过宽失效的 contributor，但旧 manifest 原始字节和后次 GET body SHA 未保存，其他身份扩展也未闭环。**原历史 run 的唯一 changed field 仍为 CANNOT_CONFIRM。** 本轮新增诊断用于未来有完整元数据的读回，不能倒推该历史 run。

## 4. 验证结果与保留的失败

权威最终命令、运行环境、完整失败标识和基线/候选差异见 `evidence/final-validation.md` 与 `evidence/final-validation.json`。`evidence/RESULTS.json` 将候选、独立审查、离线集成、部署、实际 API/UI 和自然时段分开记录。

本轮后端 56 项定向回归的对照为 **16 FAIL / 40 PASS → 56 PASS**。原 76 项 Issue8R2 数据与安全回归按固定 Git 原字节恢复，在两侧均 **76 PASS**。本轮前端新增 44 项测试为 **34 FAIL / 10 PASS → 44 PASS**，包括 23 项诊断校验、15 项实际 mount 行为、6 项真实后端合成 DTO 消费。四个既有后端相关模块仍为两侧 **16 FAIL / 100 PASS**。

最终全套运行仍有失败，不能合称全绿：缺失的固定 Stage/full-app 支持、旧 owner/Mac fixture、已有业务行为断言和本次明确的合同差异均保留。并行全套运行中的短 TTL 测试失败及其单独复核结果分别记录；单独通过不改写原全套 FAIL。

全项目类型检查在两侧都保留 3 项错误；完整 Vite build 在两侧都因缺失入口失败。修改范围的严格 TypeScript 检查通过，不能替代完整发布构建。

测试实际环境为 Linux、Python **3.12.14**、Node **24.19.0**。Python 的 31/31 个锁定依赖版本匹配，但项目声明 **Python >=3.14**，因此该最低版本要求为 **NOT_MET**；Mac/Python 3.14 验证 **NOT_RUN**。完整环境和锁定来源见 `environment/`，没有上传运行时或 node_modules。

已物化催化 owner 的真实 archive 测试保留原 schema 对 acquisition 字段的限制，测试中有 1 个绑定 artifact、0 个时钟准入卡片。非空显式时钟卡片测试在 reader 输出/投影边界使用合成行；它证明投影回放的完整性守卫，**不证明真实来源 PIT 已闭环**。历史/auto view 的 provenance 不变性也仍是 **NOT_PROVEN**。

## 5. 离线复现与 Mac 核对入口

本包只提供只读核验脚本。以下示例用于已下载的交接包目录；它不会应用补丁、访问 owner、发送 HTTP、抓取数据或启停服务：

```bash
python tools/verify_handoff.py
python tools/verify_handoff.py --target-root /path/to/isolated/app --target-state before
```

任何目标 SHA 不匹配都应保留该差异，交 Mac 主控协调现役 owner/源码后再合并；不要使用 force/reset/clean 覆盖并行修改。`--target-state after` 可在隔离合并后核对 9 个完整改后文件。源码字节一致本身不代表运行身份或部署验收通过。

将 `regression/` 中的 4 个新测试按原相对路径放入隔离候选即可重跑。原 76 项回归与既有 fixture 的固定 Git 引用见 `support/REGRESSION_REFERENCES.json`，不重新上传其原 owner 响应。新测试需要现有源码支持，Python 精确命令与前端配置见 `REPRODUCE.md`。6 个跨语言合成 DTO 可由 Python 测试生成；未附带大体积响应或计划数据。

## 6. 仍需保留的数据与验收边界

- 目标 `20261009` / publication `20261008` 公告解析导入仍未闭环。旧 `20261008` / `20261007` 的 613 Reader、613 独立 Reviewer、33 selected、VERIFIED import 只能作为该旧日期子链证据。
- corrected V3.5 root 下 exact `20261008` panel 已存在；该日 security-master exact entry 缺失。六日 volume unit/scale 为 `NOT_PROVEN`，provider finality 为 `NOT_ATTESTED_BY_PROVIDER`。不能继续把 panel 缺失当作已证根因，也不能通过当前抓取回填 PIT。
- HK Connect 目标日 membership authority 未闭环。超跌仍有 693 待核、695 gaps 的输入报告；本轮没有补数据或提高其业务状态。
- 四个已审 US-HK 关系的 VALID_EMPTY 只在该局部范围成立。另一条 isolated run 的 external_finance READY/no market_snapshot 不覆盖现役局部关系结果。
- 用户报告的 2026-09-30 独立成功 receipt 本次未定位，保持 `CANNOT_CONFIRM`，不否定用户报告。
- 本轮没有实际 Mac owner/API/UI、修复后浏览器截图、browser-loaded bundle SHA 或自然时段验收；没有部署、启停服务、改日程或回写业务状态。

研究安全边界保持 `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`；A/HK 合同、完整预选池输入、BUY 门禁、Stage 与 Vibe8910 不变。
