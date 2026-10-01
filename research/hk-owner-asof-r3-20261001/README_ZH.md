# V4 HK 原 owner / 来源 as-of 最小接入候选

固定输入：`3ed9e89a1de1616d89ddbe166484227b5fcd42fa`（PR19）。本包只含 HK 接入相关双前像、双后像、补丁及合成验证。A1445不追加，经理/F5/Vibe及六项旧catalog差异不处理。

## 实现与范围

原 preselection owner 调用既有 `stage_center.hk_universe_preflight.ensure_hk_connect_universe`，不再直接跳到 `ensure_hk_security_master --reuse-only`。只有原publisher确认本日来源后，原master及HK0.2子进程才继续。原publisher的当前上海日期限制、原capture、plate与SHA校验保持；本包不替换publisher，不重建9/30 authority。

价格日由 `hk_securities` 日历的目标日前一证券交易日确定；资格来源采用实际验证的原成员快照as-of，而不是推算“上一Connect日”。本版本只支持原capture当日有效的来源（`EXACT_CAPTURE_DATE_ONLY`）：price日/as-of独立字段，即使日期相同也分别绑定；没有官方连续有效证据的旧资格快照不自动续期。比如10/8目标需要10/7证券价格日及对应原capture；9/30生成的10/8快照保持原日期，不是10/7刷新。

shared新增读侧绑定复用原universe reader和原security-master reader，交叉核对原代码集合、source/codes摘要、current、artifact、manifest、receipt、两个真实capture与master身份。原source时间不借用master时间补齐；不存在capture/身份不符则CANNOT_CONFIRM。来源证明经原shared manifest携带，projector输出到原池，原Stage D1读取器核验证明及正确价格日。没有第二producer、selector或数据根。

原SourceSpec只接受路径中立字符串。本候选将完整原来源证明按canonical JSON的UTF-8字节hex编码存入`eligibility_asof_hex`，读回可逆还原；原timestamp内容不更改，不放松路径/存储合同。

HK-only scheduled入口仅投影HK池，不调用A采集/复盘/模型生产，不写A空占位。活动版本保留r9正式池reuse与原非HK逻辑；calendar增加专用policy，catalog仅`preselection_pools.run_policy`一项变化。双方开市仍走原双市场流程。只有HK来源缺失不等于A池无效。

## 双基线，不得叠加

`canonical/`是已含frozen_r2的3ed源码，8运行文件增量。`active/`是3ed导出的三处活动物理owner（10文件）：preselection_app、shared_package、stage_app；按各自原件适配。两者不是同一安装前像，不能将canonical完整模块复制覆盖活动r9单体模块。

每个路径的完整before/after、大小、SHA256、Git blob均列于`SOURCE_SHA256.json`。18份前像均逐文件与3ed对应Git blob一致；不是拿缓存日期或文件名猜版本。活动native VIPDOC记录、评分函数及非HK projector函数AST相同，见`STATIC_PRESERVATION.json`。本包没有A1445源码或前端改动。

## 实际测试

同一新19项，在两个隔离导入载体分别运行：canonical RED 1 pass/18 fail；GREEN19 pass/0 fail/0 error/0 skip/exit0。active同样1/18→19/0/0/0/exit0。两个载体是同组用例，不是38项独立业务证明；旧r2 20项及A1445 17项未运行。

覆盖HK-only10/7→10/8、双方开市10/8→10/9、原owner调用publisher、原来源缺失中止master/模型子进程、真实shared store与projector、Stage D1读取器、显式分离root、两个真实CLI解析/读回、已实际落盘的合成A池/receipt/manifest原条目保全，以及capture/日期/来源SHA反例、不可变早期10/8冲突。模型推理、网络Futu、自然parent调用以明确合成边界代替，不使用实际行情。A池是真实存储写入的合成样本，不是用户Mac正式池。

重要载体限制：所有被修改源码按3ed前像核对；未随本任务导出/未在当前容器完整重组的依赖由既有缓存提供。特别是作者测试中的原publisher/universe-reader合同载体使用651个合成代码，**不等价于当前活动publisher/实际696资格源验收**。不把这些缓存依赖作为后像安装。`TEST_DEPENDENCY_LIMITS.json`记录实际导入字节；Mac须在实际活动owner及其shared reader上验证同组测试。测试能说明新增接线及来源合同，不能证明149文件整体、实际进程或自然来源已通过。

早期19项之前的真实失败输出留在`validation/earlier`：缺来源绑定、CLI字段未接、路径中立合同不允许原始时间字符串、以及合成fixture缺research_only和错误要求整个共享manifest字节不变。后两项是fixture修正，不算产品故障；最终两套19项均为相同最终测试SHA。没有跳过/吞异常拼全绿。

作者Linux Python3.13.5，不重装、不为版本改业务。最终Mac现有服务解释器/依赖为准；HK模型专用子解释器仍由原owner绑定，不替换。

## 明确保留的真实缺口

1. 9/30缺capture的authority与10/8早期旧快照不修补。若10/7自然刷新遇原same-target不可变冲突，本候选明确拒绝并保留旧件，不自动quarantine/覆盖/借历史backfill。真实10/8未恢复；需Mac按原已批准owner的冲突处理合同独立决定，不能由代码绿色结果替代。
2. 真正当日原publisher capture、完整资格/价格来源、actual master、进程加载和自然父回执尚未取得；全部保持CANNOT_CONFIRM。原publisher/共享universe reader的实际身份及动态成员数兼容须Mac核验，不修改651/696常量凑数据。如该依赖仍有不适用的旧计数合同，仅反馈其原路径/SHA/相关函数；不索项目或行情包。
3. 真正已存在的Mac A池保全、Stage/API同根以及普通页面读回尚未执行。HK空卡片合并状态展示本批未改。
4. A1445既有ZIP仅引用；新Mac独立17项及4076→811b原件回放仍NOT_RUN。

## GitHub交付状态

当前连接的48个GitHub动作只有读取，没有create/update/push。因此未推送，也未创建新Draft PR；不能把PR19称为本批修复PR。

包外/包内`GIT_DELIVERY.json`和增量bundle固定本批本地Git提交，直接parent为3ed，保留原README和交接树SHA，只新增`research/hk-owner-asof-r3-20261001`交付目录。Mac可在有3ed完整对象的仓库取回这个提交并创建Draft PR；无需再编码或索取token。见`WORK_ONCE_ZH.md`。

RESEARCH_ONLY；production_allowed=false、buy_gate_updated=false、orders_sent=false。不部署、不合并、不真实selection或交易，不启动旧producer，不扩修。
