# M13 验收与 Mac 回传

本文件是将来执行规范，当前未运行产品测试、Mac操作、API/页面或自然链。动态结果初值统一 NOT_RUN。材料检查通过仅说明文件完整，不能升级业务状态。

## 1. 候选准入：Chat 必须先自查

- 唯一M13候选版本、固定基线、逐文件白名单、before/after/正反补丁/SHA闭合；每条新依赖可溯源。全部实际变更须落在M13独占白名单，公共文件改动为0。
- 原采集/算法/分类/资格门、真实Reader/独立Reviewer、原owner导入与readback复用；现有等效能力保持原字节。
- 392决定、原产品/回执、5b4f经理run不重建；源run与经理run不混用。source字段只来自实证。
- shared gateway、经理保存、共享前端未直接修改；所需接线已转成消费合同/fixture与精确跨模块请求。
- 必要依赖/manifest变化完整披露。固定vendor字节或PIN有变化须有原缺陷与最小闭包证据；不得绕门。
- 没有“独立Reviewer PASS”伪造、“source_origin_verified”强置真、把NOT_RUN写PASS或把合成结果写自然运行的行为。

## 2. 必要针对性测试矩阵

测试沿真实入口/调用链，先读仓库指令采用规定解释器与依赖。选与实际差异有关的测试，不靠替身补绿。已验且输入/代码未变的历史证据引用即可，不能把不同提交测试次数相加。

| 场景 | 预期 | 本包动态结果 |
|---|---|---|
| 原目录完整性/真实空 | 缺页、重复art_code、错误总数、截断不能称COMPLETE_EMPTY；证据完整空与失败区分 | NOT_RUN |
| 正文与原source绑定 | 错issuer、换PDF/正文/原引用/hash、失败正文未评估均按原门禁处理 | NOT_RUN |
| 原语义与独立审核 | 缺返回、Reader=Reviewer、旧revision、parent product/receipt错误不能导入；不得自行PASS | NOT_RUN |
| 精确修订身份 | semantic/reviewer/decisions/source/capture任一变化使旧绑定无效 | NOT_RUN |
| 原owner保存/幂等 | 同输入只复用原成功；不同产品不能覆盖；中途失败保留成功与明确状态 | NOT_RUN |
| M13独立读取 | target/publication/cutoff、product/receipt/binding SHA正确；读取前后输入不变 | NOT_RUN |
| 默认与显式日期 | 原日历导出相同有效产品；错日拒绝，不改标签伪装默认读 | NOT_RUN |
| 只读隔离 | GET无网络采集、导入、存储写入、新operation_id；不触碰V4私有根 | NOT_RUN |
| 消费fixture | M18能识别已提交产品与缺源/PARTIAL/有效空/STALE；不借另一产品或run | NOT_RUN |
| 安全/限制 | BUY、orders、production安全语义不变；PIT/首次发布/Connect未证不提升 | NOT_RUN |
| 新适用日接续 | 新来源与实际审核/实际cutoff绑定；失败可恢复，不复用旧392冒充新日 | NOT_RUN |
| 必要import/typecheck/构建/原回归 | 对候选完整依赖运行，失败原样披露；无环境则注明阻断 | NOT_RUN |

M13独立测试通过不等于 M18 保存/普通API/页面集成通过。M18负责本次经理exact run与terminal、latest交错以及其他lane缺源不抹健康结果；共享页面负责日期/刷新/取消/历史/迟到响应等。M13提交相应fixture和预期，不越界修改这些实现。

## 3. Mac步骤由嘻嘻统一执行

Chat应把以下流程落实成候选适配的精确操作文档；本任务不会执行这些步骤。

1. 只读核实际Mac活动版本、M13 owner/binding/源根、解释器与依赖；记录实际路径和SHA。对候选before逐文件比较。前像漂移先核差异，不强行打补丁或覆盖整树。
2. 保留V4服务/数据/8910、当前真实M13产品、原经理run和回滚。候选落在隔离M13位置；不改变公共generation/共享端口/公共路由。
3. 对固定候选执行必要定向测试及聚合回归。每套记command/cwd/time/exit/log/SHA，保留stderr，分别统计。
4. 对既有392与5b4f引用，仅在原记录上做必要的精确只读校验；新旧产物不混合，不重新采集、分类或导入，不自动新建经理计划。原证据缺字段时报告UNKNOWN。
5. 通过原M13 owner/reader验 target/publication/cutoff、source run、原body/semantic/reviewer、binding、product/receipt SHA；返回值相同还要核原件身份，不能只看HTTP200。
6. 把M13候选、消费合同与fixture交统一集成。嘻嘻联同M18/共享owner核已存经理产品内的M13引用，并安排普通API/页面同run验收。此步骤未执行保留NOT_RUN。
7. 只有收到该候选已纳入单一发布窗口的安排才切换；核实际code/data generation、静态资源及健康端点。没有切换就明确“未切换”，不把端口权限错误解释成进程停止。
8. 失败回退M13候选及其授权的独立绑定；共享切换/回退统一执行。业务缺陷回原M13 Chat改唯一候选，不在Mac另写一套业务实现。
9. 新适用日按原来源/审核/owner合同接续，保留真实起止与触发身份。历史回放/人工恢复分别标记；原计划要求的连续适用交易日自然证据未满足前，不计M13完整完成。

## 4. 回传给同一13号Chat的格式

- 候选commit/分支、原模块M13、文件白名单与实际before/after SHA
- Mac时区、实际时间、解释器/依赖、owner根/只读绑定（敏感绝对路径按最少必要原则）
- 实跑command/cwd/exit、日志位置与SHA；每项PASS/FAIL/BLOCKED/NOT_RUN
- target/publication、实际capture/cutoff、source/evidence run、reader/reviewer与修订身份
- 原M13 product/receipt/binding SHA；M18经理run/product/terminal仅作引用，未知字段不补造
- 失败最短步骤、预期/实际、原拒绝码、精确函数/必要trace、影响范围
- 是否只发生于合成fixture/真实原件，是否依赖跨模块请求
- 是否真正切换、当前活动generation、是否回退；未执行明确NOT_RUN
- 要Chat交的最小修复；不重复索要整库或不相关正文/凭据

外发材料不得带凭据或不必要私有公告正文；真实来源原件继续留Mac。遇不明副作用先读原attempt/run，不盲目重复POST或导入。

