# 主交付文档独立审查

**结论：PASS_DELIVERY_GUIDANCE_WITH_STATED_NOT_RUN_BOUNDARIES。** 已审查四份主文档在本报告 `REVIEW.json` 记录的字节版本，未发现未关闭的事实、身份或执行边界问题。本结论只适用于交付说明及所列源码/协议核对；不表示 Mac 集成、上线或阶段恢复已完成。

审查者为 `stage_receipt_binding`，独立于主文档作者。固定输入是 `lexi2016/v4@28ab2d35020adf031f10f38c1040514fc81b6d66`。正文依据固定问题包、已核历史 CLI 源码、候选源码和原始测试日志，不依赖 Mac 当前服务会话。

## 审查对象与结论

| 文档 | 核查结果 |
|---|---|
| `README.md` | A 前五阶段已各有 10 只、216 输入与 205/206 行情、HK 缺 10/8 资格主表等事实与原问题包一致。明确源码候选/测试完成与运行闭环 NOT_RUN 的区别。各组件测试数量按作者与独立新增覆盖分列，没有重复累计重跑。 |
| `PROMPT_FOR_MAC.md` | 要求先核真实 owner/解释器/config/加载 bundle，保留已部署并行修复，在现役完整 app 上应用最小差异；支持文件不部署。真实输入、单节点、按原流程发布及同一产物的 API/UI 读回均列为后续工作。 |
| `ROOT_CAUSE.zh-CN.md` | 原链的输入、行情、算法、回执和页面问题分别归因。最终字段投影的已证实缺陷与仍未核的实际 provider/builder 昨收链区分清楚。未把原 10/9 已结算产物说成已回填，也未把缺 HK 数据写成代码已解决。 |
| `MAC_ACCEPTANCE.md` | 原节点 CLI、日期与历史模式限制、三类输出隔离、原 Store/回执合同、实际 8873 读回和旧 release 回退要求准确；不删除 settled slot、旧 latest、回执或锁。真实自然触发与声明 NATURAL/DUE、owner 自存历史分别核验。 |

四份精确文档 SHA 与字节数，以及交叉核对的参考文件 SHA，见同目录 `REVIEW.json`。后续若改变受审正文，应核改动是否影响此结论。

## 事实与源码身份

原 `PROMPT_FOR_CHAT.md`、`DIAGNOSIS.md` 和 `CURRENT_API_UI_SUMMARY.json` 支持 A 前五阶段均有结果、完整 216 输入、竞价 205/216 以及其余四阶段 206/216。竞价原回执的 11 个缺口是 `EMPTY_PAGE`，文档没有将其扩大为供应商永久无覆盖。HK 缺真实 20261008 资格主表、20261009 正式池为 0，必须保留输入失败；10/8 价格观察、9/30 旧池和当前快照都不构成该日资格。10/9 不符合旧 Connect-closed 观察通道的前提。

独立读回 `SOURCE_MAP.json` 的 **15 个文件变体，逐个核对前像和后像 SHA，全部一致**。其中 7 个变体有本轮输入身份，8 个变体属于明确的历史条件件：1 个 API consumer、4 份 actual/canonical 节点 helper、3 个 UI 文件。共有 8 组补丁；这里核了文件身份，没有把此项记录成新的补丁往返运行。

文档与原 `SOURCE_MANIFEST.json` 对 actual Stage、canonical、actual API 三个根的区分一致。不同 runner/slot/receipt 字节不能互换。当前 API consumer、frontend source/bundle、节点 helper、plist/config 正文未附，文档没有把 10/5 参考版本冒充 10/9 当前运行版本；前像不匹配时要求在当前文件移植最小语义差异并补现场审查。引用历史支持文件建立测试闭包，不构成部署许可或现役身份。

## CLI、输入与回执边界

直接检查已核同 owner 的 10/5 历史 `node_entry.py` parser：存在 `--config`、`--node`、`--trade-date`、`--check` 等参数，默认时间来自实际 `datetime.now(SHANGHAI)`。文档中的 `STAGE_0945_1030` 指定单节点，没有伪称 `stage_center.runner` 自带 CLI。当前启动解释器、flags/bootstrap 和 config 仍须由 Mac 重读，特别保留 venv Python 的 lexical 路径。

历史 nodes parser 的 `--historical-backfill` 未传至 runner；文档明确指出不能用它证明隔离。原 `ops.run_stage_center_tick` 才把同名参数传至 `tick(... historical_backfill=...)`。文档没有提供绕过日期拒绝、伪造 `--evaluated-at` 或清理 live 幂等标记的操作。隔离 canary 只把原 raw/selection/receipt 输出根改为新独立目录，输入继续使用已核原 owner；也明确 canary 的结果不会自动出现在配置读取另一根的 8873。

HK 恢复指向已部署原 ensure 的 `--reuse-only --verified-source-store-root`，要求真实原三件套、日期、采集时间、代码集、PIT，以及原 producer/materializer 后续产物；保留源/目标 writer 静止限制，没有宣称历史并发 P2 随本轮自动关闭。A provider → SourceResult → builder/qmt → result 的真实同源昨收仍要现场验证；缺值保留 null/原因，不能显示伪造零，216 输入不受 UI 200 限制影响。

回执说明与已冻结 writer/reader 协议一致：未来真实调用/写入时钟、原 receipt root 内不可覆盖的历史正文、选股三件套原字节 SHA 与规范 SHA 分开核对，外层 dispatch/deadline 重写后仍须指向对应正文。原 consumer 必须把真实 `self.store` 传给 reader 才能核 selection 三件套；A 候选输入没有被 API 独立读回，HK 输入三件套未完全暴露。这些缺口没有被 owner 历史 SHA 掩盖，`execution_verified`/`natural_verified` 不会因自存档或 NATURAL/DUE 字样变为 true。

## UI 测试依赖位置参数

按 root 的明确任务，仅在独立测试 `work/ui_review/tests/component_harness.mjs` 调整一个依赖定位表达式：

```js
const runtime = createRequire(resolve(process.env.STAGE_UI_RUNTIME ?? resolve(work, 'ui_runtime'), 'package.json'));
```

未设置 `STAGE_UI_RUNTIME` 时仍使用原 `work/ui_runtime`；设置后可让交付包内同一套测试使用已安装的固定依赖。当前 harness SHA 为 `de4cffce748211dbbf627e1bb9a0a367cc4df1ddeff26d5cf243d4096f7ce7fb`。这只是测试依赖的位置参数，没有修改组件、App 或 API 合同源码。

显式指定原 pinned runtime 后，独立复跑原有 **25 项：25 PASS，0 FAIL，0 SKIPPED，0 CANCELLED**。命令与原始日志身份记录在 `REVIEW.json`，日志为 `work/ui_review/evidence/independent-runtime-override.stdout` 与 `.stderr`。Node 为 24.19.0，Vue/compiler/server-renderer 为 3.5.13；原始 `stripTypeScriptTypes` ExperimentalWarning 保留。

复跑后又读回 UI 三个产品文件及交付副本：App `e13a92e7…`、面板 `6cb4aecf…`、runtime contract `c440de3f…`，与 UI 已冻结独立审查版本完全相同。此次 25 项是相同独立案例的再次运行，不是新增 25 项覆盖。它们仍是真 Vue SFC 编译与 SSR，不等于完整 App 构建、浏览器交互或现役页面验收。

## 完成范围

本次审查没有未关闭 findings，也没有修改产品、业务数据、发布指针或 GitHub。全部交付字节清单校验、从最终交付目录启动全部 suite 的结果，属于 root 的最终组装与验证步骤，不由本次四文档审查替代。

Mac 当前身份复核、完整 app 集成/构建、真实阶段执行、历史缺数据恢复、部署、8873 API/UI 同一 run 验收、独立自然时段验收均保持 **NOT_RUN**。主文档对此边界的表述一致，可以作为接手说明；它们没有构成“页面已恢复”或“10/9 已自然就绪”的结论。
