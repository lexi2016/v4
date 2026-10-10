# V4源码梳理与优化审查交接

日期：2026-10-10（北京时间）。目标：让Chat基于实际源码判断最短优化路径，减少重复修复，先恢复真实业务与页面交付，再做有证据的性能和架构改进。

**本次是审查材料交付，不是新产品版本。没有修改现役V4/V5、部署、重新采集或运行产品测试。**

## 直接交给Chat

请复制 [PROMPT_FOR_CHAT.md](PROMPT_FOR_CHAT.md) 的任务，附本目录固定提交链接。重点请Chat交回逐文件合并矩阵、源码级问题清单、最小实施顺序与必要材料清单，而不是再次写泛化架构方案。

建议阅读顺序：
1. [CODEBASE_SCOPE.md](CODEBASE_SCOPE.md)：全18模块范围，哪些本轮深入读过、哪些仅登记原范围。
2. [STRATEGY_SOURCE_MAP.md](STRATEGY_SOURCE_MAP.md)：公告、美股、超跌的实际生产与算法链。
3. [DELIVERY_PIPELINE_REVIEW.md](DELIVERY_PIPELINE_REVIEW.md)：调度、原owner、保存、API、页面和发布的接线与版本冲突。
4. [OPTIMIZATION_PROPOSAL.md](OPTIMIZATION_PROPOSAL.md)：待审的优化次序、最小交付链、保留合同及验收。
5. [SOURCE_INDEX.json](SOURCE_INDEX.json)：统一源码索引，含精确原commit/path/blob/SHA256/大小/包内快照。
6. [PACKAGE_CHECKS.json](PACKAGE_CHECKS.json)：本轮实际交付检查，产品测试与Mac/UI验收明确NOT_RUN。

## 三个最重要的审查问题

- **不能按日期整文件覆盖候选。** 已读R3 router与四功能R2 router的US owner准备/读回能力不同，丢失接线风险真实可定位；它们不是可以盲目互相覆盖的完整新版。
- **reader、wrapper、历史成功产物不等于producer已接通。** 公告缺口要逐阶段定位；美股四键与原生关系材料链分开；超跌双门主筛选与另一四项条件链分开。
- **先保证可交付，再优化性能。** 已有真实输入的本机最小链不应等待云端全量迁移。性能问题本轮无profiling，静态风险不能宣传为已经测得的根因。

## 基线说明

没有把一个GitHub HEAD认定为当前Mac全量现役。包内分别保存历史canonical、V5保存的V4原owner、外部候选后像和交接文档。每一份快照的来源独立固定于SOURCE_INDEX。

本提交以`f7cb731c384ee6890a87d16c19a5b5a621779477`为仓库父节点，只为复用已存在的仓库对象；不是宣称它是V4运行基线，也不将V5分支改成V4现役。新增内容只在本handoff目录，不更新已有产品路径、不合并到main。

`sources/`、`strategy-sources/`、`source_snapshots/`是必要审查切片，不是可直接安装的完整应用。即使源码SHA全通过，也不能据此执行整树覆盖、启动脚本或声称测试成功。缺的依赖闭包和当前绑定由后续实施前按最小必要范围核对。

本包未新增上传Mac正文、真实行情、模型、凭据或会话数据；源码快照来自用户已有私有GitHub仓库。需要完整下载时，可使用GitHub对应分支的Download ZIP，仅本目录是本次新交付。

## 当前工作的边界

用户先要求反思，再要求整理V4代码并交Chat看优化。因此部署保持停止，当前仅完成源码分析、文档和GitHub材料交付。方案中的验收和改进均为建议，未作为本轮执行事实。

V5完整验收仍保留原01—18/P0—P5；本包不重新计完成数，也不以一个修复或一种策略代替18模块。内置浏览器、普通页面同run、真实数据与自然接续继续分别验收。
