# 原15号模块Mac独立验收与回传

本文件是候选返回后的检查合同，当前所有产品执行检查均为NOT_RUN。此次仅准备文档，没有操作Mac、采集、产品测试、服务切换或部署。M15 Chat负责业务代码，嘻嘻独立验收；M02/M03/M04/M18各自问题转对应owner，不能在M15验收时跨写修复。

## 安装前的范围门

- 固定候选commit、实际文件before/after SHA、源→目标映射、完整依赖/PIN、解释器/依赖锁；逐文件核Mac前像，漂移先回传。
- 修改仅限M15适配器/自有vendor/manifest/专属测试。跨模块collector、source store、manager、gateway、前端或共享调度变更直接标越界，交集成者处理。
- 原活动V4、V5预览及8910的绑定、进程、静态manifest留证；核实际根/端口，不把旧61796记录当当前事实。只在独立M15候选根工作。
- 选真实HK目标与US session，固定原三文件SHA、cutoff、真实时钟、触发身份、reviewed seed/registry；行业/个股材料分别固定原正文/span/时点/native证据。已有成功原件先复用，不重复采集或回写源。

## M15模块内检查

| 检查 | 验收要点 |
|---|---|
| 闭包 | source manifest逐字核，namespace/常量/JSON/日历与传递依赖齐；不能靠外部sys.path、stub或放宽PIN补绿 |
| M03输入消费 | 原store exact-read与M15引用同一三文件；读取前后原件SHA不变。错session/phase、过cutoff、缺报价/坏安全字段拒绝；不填0 |
| 旧receipt | 完整新形状及恰缺两字段精确旧形状通过；仅缺一项、多缺、改值、多余字段、原字节或manifest篡改拒绝。原receipt不改写 |
| owner版本 | 若接R3，签名、budget、execution_context、exact-run、dispatch与恢复语义匹配；允许的M15写路径逐条核，不删参数或吞异常 |
| 种子daily | 四键、三张可匹配卡及无daily键主题卡范围保持；同输入下原关系类型、排序/理由和输出等价；有限空、范围外和未评估分别记录 |
| 材料行业 | 真实上涨行业/主题与可核港股业务材料join，行业路不错误要求显式ticker；无材料、无关系和被拒分开 |
| 材料个股 | 明确ticker关系、主体/span/hash及时点准入可核；peer不变供应关系，taxonomy不补关系 |
| 准入反例 | 缺master、假/缺取得时间、晚于cutoff、SHA变化、错误主体/身份均按原码拒绝；资格未知保持未知 |
| 独立保存读回 | daily run/artifact与本次输入一致，M15输出独立读取。latest被B推进时A仍按A exact读；原owner有terminal/dispatch则同run校验，不能借B |
| 故障恢复 | 超时/结果未知先查原run/attempt，不盲重试；失败不覆盖成功，不把缺源等同有效空；输出根隔离 |
| 输出合同 | 三路视图为种子daily、材料行业、材料个股，来源/范围/日期/资格/拒绝状态和安全字段完整，供M18消费的引用稳定 |
| 回退 | M15候选可独立回退，原数据/现役/其他模块不变；未实际执行回退明确NOT_RUN |

Chat侧合成/录制测试证明工程边界；Mac真实原件证明业务，两者不混计。既有同代码同输入证据可引用，实际delta影响的必要检查不能省略。每项分别记PASS/FAIL/BLOCKED/NOT_RUN和原始日志SHA，不以测试数或进程exit0代替业务证据。

## 跨模块联调单独登记

以下由对应owner/集成者执行，不允许M15 Chat借此修改共享代码：

- M03：原slot/CLI真实provider响应、三文件生产和下一适用US session自然接续。已有18/18合成采集测试不替代。
- M02/M04：真实主表/资格与材料正文/span/取得回执。缺失只回传最少合同，不造输入。
- M18：同一M15来源→原经理保存→同run product/terminal→普通API/页面。US source run、daily run和manager run分开；latest观察另报；健康公告等其他lane保留。
- 共享页面：股票/理由/来源/session/范围/资格/有效空与缺口，普通auto与dynamic区别、CURRENT_RECOVERY非历史声明、历史只读、日期绑定、刷新取消/迟到响应，由M18/UI集成统一验。

有独立M15候选且模块内工程检查可核，可以接收候选；缺真实材料或联调未完成时不能填写M15完整验收通过。原M15唯一退出仍要求同session种子及材料两类映射的真实结果/拒绝、普通消费一致、范围外与资格/自然身份保留、自然接续和独立回滚。全系统P5两连续适用交易日另验。

## 单问题回传模板

- M15问题编号/严重性/种子或材料行业或材料个股：
- Chat候选commit、Mac实际before/after SHA、是否越界/漂移：
- cwd、解释器/依赖、最短复现、exit、脱敏日志SHA：
- HK目标/参考/资格日；US session/phase/cutoff；真实时钟/trigger：
- 三文件SHA；reviewed/registry；材料/span/native引用；M15 run/artifact：
- 预期/实际与原拒绝码；exact读回/latest观察分别填：
- 合成是否可复现、原件缺口、未受影响路径证据：
- 需要M15修的最小delta，或交哪个模块owner的哪项输入/接口请求：
- 未执行检查明确NOT_RUN；原根/现役不变和回退证据：

只补必要源码差异、输入合同及日志，不重打整仓。私有正文、凭据及未授权原件不混入GitHub问题材料，不放宽原来源、PIT、资格或安全门来补绿。
