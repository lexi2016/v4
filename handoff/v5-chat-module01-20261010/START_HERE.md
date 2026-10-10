# 第一模块编码交接：真实公告 → 经理保存 → 普通页面读回

日期：2026-10-10。用户最新分工：Chat负责方案与具体代码；嘻嘻负责必要材料、Mac落地、测试、页面验收及精确问题回传。此包是给Chat的编码任务，不是新代码交付或已执行部署。

## 本批目标

对应原V5模块13→18、P1中的最小真实链。保留V4现役服务，最终接入V5预览。先让已存在且原owner可验证的公告结果，在普通页面显示股票、理由、来源与缺口，并与经理保存的同一run/终态一致。

**V4审查中的逻辑路径是参考源码，不是V5部署目标路径。** Chat须先给出V4 donor→现有V5入口/consumer/frontend的映射，再在真正目标文件生成最小差异；不得把V4 workspace整文件覆盖V5 manager_plan，也不得替换现役V4。

## 已有材料，直接复用

- [源码审查包](https://github.com/lexi2016/v4/blob/d3578688995c7cf14edb3b771a36688e0558dc2f/handoff/v4-code-optimization-review-20261010/START_HERE.md)：60份源码/参考快照及身份索引。
- Chat刚交的REVIEW_FINDINGS.md、RECOMMENDED_PLAN.md、BASELINE_MERGE_MATRIX.csv、MINIMAL_MISSING_INPUTS.md：原审查会话已持有，主会话也已读取四份原件。无需用户重复整理。
- [现有V5前端候选](https://github.com/lexi2016/v4/blob/e0a6bc36f9563df6a4e0f37d4e16a59e14347227/handoff/v5-current-recovery-frontend-20261010/START_HERE.md)：3个TS与1个真实数据依赖测试；不能当纯合成测试独立通过。
- [V5固定代码](https://github.com/lexi2016/v4/tree/f7cb731c384ee6890a87d16c19a5b5a621779477/V5)：供追踪现有适配、manager_plan、ordinary read与frontend。其云端portable数据是旧PARTIAL/0结果，不得部署替代Mac真实generation。
- [原迁移执行计划](https://github.com/lexi2016/v4/blob/d1bf034640ca2e5957423de2745a98e159b69af2/V5/docs/superpowers/plans/2026-10-10-v5-migration-execution.md)：保留01—18/P0—P5，第一模块不代表三策略全部完成。
- [另一路已交局部修复](https://github.com/lexi2016/v4/blob/d659ff0dbcc00aa1944908cfc8b44443642ea171/handoff/selection-output-reuse-repair-20261010-r1/README.md)：公告最终SHA绑定顺序、CLI完整readback与超跌Decimal边界。仅在确实命中目标版本时复用，不重复实现、不整套覆盖、不把合成通过当本机通过。

## 本机既有状态（已有回执，不是本包重新实测）

- 已有392条公告决定：2 event / 0 earnings / 26 observe / 270 not selected / 94 unknown。不是392只入选股票。
- 经理run：5b4feaf7ef7d4d13bec639e90b6d3db0；产品SHA：56556a67ddc1a562e82b38e750be92fcfda070945397cc4eacffd1c79f42bcf0。
- 原生成时间：2026-10-10T02:23:24.502381+00:00；后续的真实回看不能冒当日盘前自然运行。
- 本机已存前端差异SHA：757fff2254cdb714946f6efdeb4675c86bbc97ea41f5df0556bd290348bd9804；候选与回滚已保留。
- 13:20 UTC前最后收到的部署任务回执：停止在候选启动之前，61796未由该任务切换，正常服务未关闭。端口权限错误不能用来推断进程停止；当前瞬时运行状态待落地时核。
- 本机真实原件保留在Mac；此次材料不要求复制到云端，也不要求重采/重分类/重导392条。

## 下一动作与反馈闭环

Chat读[编码任务](PROMPT_FOR_CHAT.md)，交固定代码候选、精确补丁、原件来源、针对性测试及Mac步骤。嘻嘻随后检查候选，按真实前像在Mac隔离落地，执行必要测试/真实API/内置浏览器验收；发现业务缺陷用[问题回传模板](MAC_FEEDBACK_TEMPLATE.md)交回同一Chat，不另开平行实现。

当前包只准备任务和材料，产品代码修改、测试、部署均为0。小时报不因准备编码任务自动恢复。
