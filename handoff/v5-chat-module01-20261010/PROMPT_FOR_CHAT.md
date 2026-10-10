# 请直接交代码：第一模块公告真实结果与经理普通页闭环

请基于你刚完成的四份V4审查交付，执行第一模块编码。不要重新做整库审查或只返回另一份方案。用户分工是：你（Chat）负责方案与具体代码；嘻嘻负责Mac落地、必要测试、内置浏览器验收与问题回传。Mac不负责重写业务代码。

## 目标与实际目标树

原V5 13→18/P1：复用Mac已有合格公告产品及真实经理run，使V5普通预览页面显示股票、理由、来源、日期、未评估与资格限制，保存/终态/普通读回身份一致。保留V4现役、BUY、8910，不交易、不扩大权限/凭据访问。

先读START_HERE.md的固定源码与既有结果。你审查的A/FOUR/D来自V4多个固定候选，只作语义donor。先核现有V5 manager_plan/announcement reader/module API/frontend，输出SOURCE_TARGET_MAP：每个donor函数、目标路径、现有等效修复、是否真正需改。已有V5等效实现保持原字节；不能将11条V4逻辑路径当作11个V5必改文件。不得为套用审查方案重建V5经理或覆盖整个V4。

## 有证据才做的最小差异

1. 保留A严格身份/页面语义；FOUR的US owner prepare与exact readback若目标链已接入则保留。需接入时配匹配的既有R3 owner/依赖，不拼旧vendor、不删kwargs糊弄兼容。US缺数据不应让合格公告消失。
2. 对本次经理run做精确产品+同run terminal读回，另报latest观察；保留日期/SHA/owner/PIT/安全字段。另一请求推进latest不应把本次已保存结果误报失败。复用已有run，不新建operation_id或新store。
3. 必要时把D冻结catalyst的局部重放修复适配A严格已验证binding谓词。完整来源/正文/时间/原引用继续敏感；只可忽略明确无关的registry-wide指纹，不能广泛删除SHA。
4. POST日期bindings必须进入完整响应validator；按目标实际DTO采用一次成功POST消费，不拼无条件二次GET。失败/超时/取消只凭真实terminal判定，副作用未知先读原run，不自动重复POST。
5. 保留selection/publication/plan/analysis日期区分；取消/切日/切view后不渲染迟到响应；历史默认只读，首次GET失败或缺read_context也不能放开生成；明确dynamic回看保持真实执行时点。
6. C的attention两行不是A必修，不为减少代码重复先重构。公告COMPLETE_EMPTY、旧US receipt兼容、超跌正式准入作为后续独立事项；除非确实阻断本批非空公告，不能扩大第一批。

## 复用既有成果

Mac已有392决定、manager run及前端候选，详见START_HERE。代码编写不需要搬运Mac全部正文/行情，也不要求用户重发已有GitHub源码。所需固定依赖由你按manifest补齐。活动Mac前像缺口只影响具体安装，不阻断基于明确固定目标源码交候选。

另核d659ff0两文件三修复是否已被目标实现覆盖；必要时引用其精确donor。它的historical runner和current-live workspace_plan不能混成同一个运行基线。

## 测试与边界

采用原项目规定解释器/依赖。测试包含exact run/latest交错、terminal缺失/借另一run、错误日期绑定、原来源篡改、取消与历史入口、健康公告+其他lane缺源、真实router DTO→完整前端validator。保持原非交易安全字段。必要import/typecheck/build有失败如实给日志，不用替身补绿，不把定向合成通过当完整工程通过。

真实392原件只在Mac落地验收；你这里若无原件标NOT_RUN，不造数据。原有成功且代码输入未变的证据引用，不反复重跑。原V5完整三策略、自然接续、18模块另验，不因本模块通过升级状态。

## 必须交付

- START_HERE.md：唯一固定commit、范围、实际测试、准确剩余限制。
- SOURCE_TARGET_MAP.csv：donor→V5目标映射，哪些已等效、哪些需改，11逻辑路径不强行全改。
- before/与after/完整修改文件、runtime.patch及reverse.patch，逐文件before/after SHA与新增路径。
- 依赖/manifest变化清单、必要测试源码及原始执行日志，保留失败与NOT_RUN。
- MAC_APPLY_AND_ACCEPTANCE.md：精确前像检查、隔离应用、候选启动、必要回归、真实同run API/静态资源/内置浏览器验收、单窗口切换及回退。路径不明不能猜覆盖命令。
- 如有代码级阻塞，只列精确文件/函数/缺失合同与最少补件；不要重新索取整库或已有回执。

如具已授权GitHub写权限，提交lexi2016/v4独立开发分支并远端读回；不改main/现役分支，不部署Mac。否则返回完整文件包。新结果由嘻嘻统一接收和Mac验收，再按准确问题回传给你。
