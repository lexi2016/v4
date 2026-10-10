# 13号 Chat：公告研究与选股（原 M13）

日期：2026-10-10。编号沿用原 V5 总计划 01—18。本包是独立 M13 编码任务材料，当前仅完成文档准备；没有修改产品代码、运行产品测试、采集、导入、部署或发布。

## 直接提交

新开一个 Chat，命名“V5 M13 公告研究与选股”。提交本目录四份文件，并粘贴 [PROMPT_FOR_CHAT.md](PROMPT_FOR_CHAT.md)。Chat 负责方案和具体代码候选；嘻嘻负责统一集成、Mac 落地、实际测试和问题回传。

- [PROMPT_FOR_CHAT.md](PROMPT_FOR_CHAT.md)：可直接提交的独立任务
- [SOURCE_MAP.md](SOURCE_MAP.md)：固定材料、已核路径与文件边界
- [ACCEPTANCE.md](ACCEPTANCE.md)：针对性验收及 Mac 回传要求

## 本 Chat 独立负责什么

原公告采集/目录 → 正文与来源存储 → 原 Reader 语义/原独立 Reviewer → 原 owner 导入 → M13 独立读取与消费合同。保留现有采集器、原算法、原门禁和成熟数据；先定位真正缺口，再交最小差异。

M18 的经理保存/汇总/计划、共享前端、共享 API gateway、调度/发布底座由各自 owner 与嘻嘻统一处理。M13 只交接口合同、消费 fixture、具体跨模块请求；禁止本 Chat 直接改共享文件或替另一个 Chat 实现业务。

原 M13 的完整业务验收仍包含 M18 同 SHA 消费、普通页面同 run 和后续自然接续；这些是跨模块验收依赖，不因拆 Chat 而取消，也不因 M13 候选已交而宣称完成。

## 固定材料

1. [原审查材料 9cac0ff](https://github.com/lexi2016/v4/tree/9cac0fffe12fda6ec06e106206e0c647b427913f/handoff/v4-code-optimization-review-20261010)
2. [V5 固定代码 f7cb731](https://github.com/lexi2016/v4/tree/f7cb731c384ee6890a87d16c19a5b5a621779477/V5)
3. [原18模块总计划 24c6d60](https://github.com/lexi2016/v4/blob/24c6d60d524f43fcf4209ec8b078ec02cb34417e/V5/docs/superpowers/plans/2026-10-09-v5-master-delivery.md)
4. [迁移执行计划 d1bf034](https://github.com/lexi2016/v4/blob/d1bf034640ca2e5957423de2745a98e159b69af2/V5/docs/superpowers/plans/2026-10-10-v5-migration-execution.md)

代码基线不代表 Mac 当前运行版本；原审查切片不是完整可安装应用。不要拿云端旧 PARTIAL/0 portable 数据覆盖 Mac 真实 generation。

## 必须复用的已有事实

以下为旧交接收到的现场回执（R），本包未重新读取 Mac 原件：

- 392 条公告决定：2 event / 0 earnings / 26 observe / 270 not selected / 94 unknown。统计和为392，不是392只入选股票；公告决定、正文失败、发行人数等不同口径不能混加。
- 已有经理 run：`5b4feaf7ef7d4d13bec639e90b6d3db0`。
- 经理产品 SHA-256：`56556a67ddc1a562e82b38e750be92fcfda070945397cc4eacffd1c79f42bcf0`。
- 原生成时间：`2026-10-10T02:23:24.502381+00:00`。后续真实回看不能冒充当日盘前自然运行。
- 既有前端候选差异 SHA-256：`757fff2254cdb714946f6efdeb4675c86bbc97ea41f5df0556bd290348bd9804`。归共享前端集成，不交本 Chat 重做。

上述成果直接复用，不重采、不重读语义、不重分类、不重导这392条，不新建经理 run 或新 store 来替代。若需核身份，由嘻嘻按原 run/binding/SHA 只读核对；仅引用旧报告不算本轮通过。迁移计划中的较早“等待真实 reviewer”状态是历史记录，不据此重启已完成阶段；当前缺口以最新原件读回为准。后续新适用日需要新来源与真实原审核，不能套用旧 PASS。

## 旧 B01 已过时

旧“第一模块”是原 M13→M18 的跨模块交付批次 B01，不是总计划的 M01。它的跨模块写入范围现已过时，由本独立 M13 任务及另行 M18/共享集成安排取代；旧事实、固定来源和成功证据继续复用。不要把旧 B01 的11条逻辑路径转成 M13 的必改清单。

本包不恢复小时报，不启动运行任务，不增加已完成模块数。产品测试、Mac/API/UI、自然运行一律为 NOT_RUN，直到有对应固定候选的实际证据。

