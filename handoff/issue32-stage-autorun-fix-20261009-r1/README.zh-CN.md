# Issue #32：10/9 自动阶段准备与读取修复

目标固定为 **20261009**。第一轮原计划为上海时间 **09:15**；价格日和港股通资格日均应为 **20261008**。本包是供本机集成、独立验收和发布的源码候选，不是完整运行应用。

输入固定提交：`b00ca5a658a9de83cf5e54ad39aa68ddd5c23526`，问题包 24 个文件全部核对 Git blob、长度；来源清单 16 个源码路径、交付清单 23 个非自身文件的 SHA256 全部相符。API 修复基于 `2ead7eb9e9f067b69610d24990bc47f792bc75b4`。

## 1. 当前结果与业务边界

本轮修复源码可复现的问题，并保留缺口。**没有取得本机的 10/8 真实主表、完整价格输入或目标日 Stage 运行证据，不能据源码测试宣布 10/9 READY。** 本包的最终测试和独立审查结论以 `TEST_RESULTS.json`、`evidence/independent_review/REVIEW.md` 为准。

已知真实状态来自原问题包：A 股主池 37 行、研究池 186 行，初步合并 216 个代码键；这些数字未经过真实 consumer 和完整 Stage 输入验收。港股只有 0 行 `EXPECTED_MISSING`，无目标 Top100 评分目录，缺 `entries["20261008"]`，价格面板是否刷新仍未确认。现役 API 仍返回空。

**修正一项证据解释：**所附旧 dispatcher 在 executor 成功后才追加 `started_workload_ids`，所以空数组不能证明 executor 从未调用。`UPSTREAM_NOT_READY` 也可能由失败结果的文字或显式字段分类得到。现有摘要没有完整 `workload_results` 和实际 facade，尚不能确定 17:30／18:00 的具体失败模块或唯一 gate。保留原失败回执，不据此删除任何上游检查。

## 2. 源码改动

| 面 | 改动与作用 | 限制 |
|---|---|---|
| 证券主表准备 | 原采集路径增加上海日期边界；新 `--prepare-exact-date` 明确匹配已修复入口。当前快照只允许用于实际采集当天，跨午夜或请求其他日期失败。 | 10/9 的实时快照不能补成 10/8 历史主表。 |
| 原始主表恢复 | 将 canonical 已有的精确来源恢复能力适配到实际 shared owner；可用 `--verified-source-store-root` 恢复经校验的原始三件套，保持源 run、SHA 和 capture。缺失日期错误给出请求日期与已有最大日期。 | 只在真实原 owner 中存在合格旧记录时可用；本轮未发现或生成该记录。 |
| 预选执行链 | 价格／主表失败后停止依赖它们的 HK 评分；保留 A 与本地汇总的执行。必需 HK 输入失败不会被汇总命令成功掩盖，使用既有失败／重试分类，保留首个失败环节和子结果。 | 实际 ledger、运行 catalog 与 facade 未附，真实重试和历史 gate 仍需本机核验。 |
| 调度回执 | 增加明确的 invoked／succeeded 字段，保留旧 started 字段语义兼容性。 | 不能反推旧回执中未记录的事实；不重置已结算的历史 slot。 |
| API | 复用 Issue #30 的配置来源根、空本地池和 manager 保留修复；只对同日 HK 日期合同补读分支做局部适配。 | 使用 API 现有交易日历，缺失日历或非法来源仍拒绝；完整 app 与真实来源 canary 尚未运行。 |

源文件、前后 SHA、实际 owner 和参考 canonical 的对应关系见 `SOURCE_MANIFEST.json`。补丁按 owner 分组放在 `patches/`；实际旧 executor 和 canonical 拆分 helper 分别适配，不能跨版本整文件替换。

HK 0.2 模型、排序、选股策略和 Stage validator 不变。10/8 历史分日期问题（价格 10/7、资格 9/30）不随本轮关闭。历史 A 股字段、嵌套 P2 和历史缺失数据不并入本批。

## 3. 测试的实际范围

新增测试执行所附真实函数，用明确的测试边界替代缺失的 import、Futu 子进程、日历和 ledger。它们验证本次日期拒绝、精确恢复、前置失败处理、结果分类与 API 合同，**不生成真实行情或权威业务输入**。缺失依赖没有从 main 或历史目录拼装成所谓现役应用。

最终结果：本包源码 **150/150**，独立审查另跑 **17/17** 反例；审查范围内无剩余 P0/P1/P2 源码阻断项。API 组合 **72/72**，由 29 个未改旧例、1 个修正日期夹具的旧例和 42 个新例组成，并保留 1 条既有 TestClient 依赖弃用警告。旧夹具冻结重放 70/71 FAIL、首轮夹具适配 71/72 FAIL 及早前 scratch 混合发现的 5 项收集错误均保留；不能将 72/72 写成旧 30 例完全未改。

最终运行命令、解释器、结果数量、源文件身份和原始 RED／GREEN 记录见 `TEST_RESULTS.json`。Mac 接手应在独立副本运行本包全部测试；既有 Issue #30 的 Mac 218/218 已在输入包报告通过，不需要用重复测试数量代替真实来源验收。

## 4. 本机下一步

先读 `PROMPT_FOR_MAC.md`。从当前实际 active 的完整 app 建立隔离候选，核对前像、运行 roots、Python、calendar 和依赖身份，再应用对应 owner 的最小补丁。API 继续使用 Issue #30 的 delta／候选工具，本包提供更新后的 `change_sets/preselection.json`；旧 plan 不适用于新字节。

输入恢复必须得到 10/8 合格 master、精确 10/8 价格面板、10/9 shared Top100 三件套和本地 pool 三件套。接着核原调度的真实调用、原 Stage 的精确输入绑定和结果，再核 8873 同日期 API 与重载页面。自然 slot 必须另有自然 receipt，手工 canary 不计自然完成。

缺失的当前源码与证据按 `MISSING_CURRENT_INPUTS.json` 定点核查。查清历史 `UPSTREAM_NOT_READY` 优先需要实际 facade／ledger 与两份完整的脱敏 workload 结果；真实 Stage canary 则需从本机实际启动参数确认入口。本包没有凭空提供 Stage CLI。

本机对本目标必要、可回退研究服务的发布授权已在 Issue #32 说明；不沿用旧 Issue #30 文档中尚未授权的状态。此 Chat 环境未连接该 Mac 运行面，本轮没有执行真实部署、API/UI 或自然验收。

始终保留：`RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false`；V4/8873 单一入口、A/HK 分离、Vibe 8910 原样。
