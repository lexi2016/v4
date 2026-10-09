# Stage 最短链路修复候选 · 20261009

**已交付最小代码、精确前后 SHA、针对性测试和独立审查；未执行 Mac 集成、发布、业务数据恢复、8873 API/UI 或自然时段验收。** 原 HK 10/8 资格主表仍缺，10/9 正式池仍应报告 BLOCKED_DATA。A 前五阶段已经各有 10 只结果，不能称未计算。

从 [一页根因](ROOT_CAUSE.zh-CN.md) 与 [Mac 接手提示词](PROMPT_FOR_MAC.md) 开始。固定输入为 [28ab2d35 问题包](https://github.com/lexi2016/v4/tree/28ab2d35020adf031f10f38c1040514fc81b6d66/handoff/stage-minimal-flow-20261009)，本候选保留其已部署预选 API/scheduler/shared 和既有 Stage 算法。

## 修改与身份范围

| 组件 | 最小改变 | 前像可信范围 |
|---|---|---|
| A auction/live 结果投影 | 输出真实同源已得昨收与日涨幅，缺值 null＋原因；末尾 card 不再把缺昨收变成 0。 | 本轮 actual Stage；两个文件与 canonical 同字节。 |
| 原 Stage writer/slot | 真实调用/写入时钟、同原目录不可覆盖 owner 正文、原选股三件套绑定；恢复只更新指定市场。 | 本轮 actual 与 canonical 分别给各自前后像。 |
| 原 API reader | 选股结果与运行证明分开展示；核 owner 历史及原 store 三件套；异常状态一致拒绝。 | 本轮 actual API；canonical API 当前身份未附。 |
| 原 API consumer | 现有调用增加 `selection_store=self.store`。 | 仅 10/5 历史前像，条件件。 |
| 原节点 helper | 等待后读实际唤醒时钟，再用原 `_node_mode` 分类。 | 仅 10/5 同 owner/对应 canonical 历史前像，条件件。 |
| 现有 UI | 显示 A 已计算/行情缺口、HK 未进算法、回执声明/历史绑定/自然未验证。App 仅一处文案。 | 仅 10/5 历史前像；当前 frontend bundle 未核，条件件。 |

[SOURCE_MAP.json](SOURCE_MAP.json) 列每个补丁、完整前后 SHA、实际目标根和条件；匹配前像后才应用。各 `before/after` 提供完整改动文件，patch 只含最小差异。actual/canonical 的不同版本分别处理，不替换整个 API 或把历史 snapshot 冒充现役。

原算法保持 `V3_STAGE_SELECTION_V1` / `eee20b08b50a693dd673f93937ef4eedc63e909295820a0141ce5e728a3754d2`。报价补丁没有改评分入参、权重、排序、Top10 或价位规则。216 输入不按 UI 200 截断。没有添加 producer、来源、fallback、全局门禁或交易动作。

## 定向验证与独立审查

测试按组件报告，不把 reviewer 重跑作者套件累加成新的覆盖数量。

| 范围 | 作者最终 | 独立追加探针 | 主要证据 |
|---|---:|---:|---|
| A 投影与原排序/算法保持 | 65 | 15 | [字段分析](work/quote_fields/FINDINGS.md)、[独立审查](work/hk_entrypoint/quote_review/REVIEW.md) |
| writer/slot | 39 | 7 | [writer](work/receipt_binding/README.md)、[独立审查](work/hk_entrypoint/receipt_review/REVIEW.md) |
| API reader/原 consumer 调用 | 28 | 34 | [API](work/api_ui/README.md)、[真实 SelectionStore 往返审查](work/hk_entrypoint/api_review/REVIEW.md) |
| 原等待/节点时钟 | 29 | 22 | [入口说明](work/entrypoint_clock/README.md)、[独立审查](work/hk_entrypoint/clock_review/REVIEW.md) |
| Vue 组件编译与 SSR | 23 | 25 | [UI 说明](work/ui_presentation/README.zh-CN.md)、[独立审查](work/ui_review/REVIEW.md) |

环境：Linux、Python 3.14.7；UI 为 Node 24.19.0 与 Vue/compiler/server-renderer 3.5.13。切片测试使用本轮源码及单独 pin 的历史支持文件和明确边界；独立 API 往返实际调用原 SelectionStore 发布/读回。它们不是完整现役 app、真实采集、HTTP 或浏览器测试。Node TypeScript strip 的 ExperimentalWarning 保留。

已复现再修复，原始 RED 与审查反例保留。独立 review 关闭了 reader 的时钟键名、状态一致性、非法状态类型，以及 UI 新摘要缺市场时误退旧回执等问题。writer 曾因旧 baseline 测试进入全目录收集出现 39 PASS＋2 RED；交付候选仅收两份明确候选测试，baseline 脚本保留在 evidence，未把这两项失败计为候选通过。clock 首轮独立 fixture 少 calendar_provenance 的失败也保留，修复的是测试接缝而非产品。

[TEST_RESULTS.json](TEST_RESULTS.json) 和 `evidence/final-package/` 是从本交付目录重新运行的最终结果；[FILE_MANIFEST.json](FILE_MANIFEST.json) 覆盖交付文件身份。复跑入口：`tools/verify_package.py`、`tools/run_targeted_checks.py`。依赖准备和原真实单节点命令见 [MAC_ACCEPTANCE.md](MAC_ACCEPTANCE.md)。

## 仍未完成的闭环

1. **HK 真实数据**：缺 20261008 资格主表原三件套。价格观察存在不等于资格；9/30 旧池和今日 snapshot 都不可改标。原恢复步骤见 [HK 与入口核查](work/hk_entrypoint/HK_AND_ENTRYPOINT_REVIEW.md)。
2. **A 字段取得与缺行情**：本候选修最终投影；并没有取回缺失 10–11 只，也未证明当前 provider/builder 的昨收已全链透传。当前源缺项保留 null。旧 run 不回填；新投影要新合法结果才生效。
3. **当前完整运行身份**：conditionals 的当前 source/bundle/入口未附；支持文件不能部署。先核现场版本，再集成最小 diff。
4. **自然证明**：新 owner 历史与真实写入时间只增强可追溯性；`execution_verified`、`natural_verified` 不自动提升。A 候选输入与 HK 完整输入三件套还有明确未绑定/未暴露字段，不能宣称全输入链已独立核实。

详细缺口在 [MISSING_CURRENT_INPUTS.json](MISSING_CURRENT_INPUTS.json)。本轮的状态是源码候选完成并经所列范围测试/审查；`INTEGRATED_ON_MAC`、`DEPLOYED`、`REAL_STAGE_VERIFIED`、`API_UI_VERIFIED`、`NATURAL_VERIFIED` 均为 NOT_RUN。

唯一完成标准仍是：固定日期/阶段，用可追溯预选池及合法阶段行情调用原算法，产出可核 run/三件套，在 8873 同一日期/阶段读回一致，并另核真实自然触发。包内测试数量、进程健康或其他 hourly 任务成功都不替代此标准。
