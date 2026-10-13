# 经理工作台重写：三块需求与 Mac 集成交接

日期：2026-10-13（Asia/Shanghai）。状态：REQUIREMENTS_READY；业务代码、部署和自然验收均 NOT_RUN。

## 用户已锁定

港股为主，A股保留独立入口；旧经理代码只作学习参考，新活动模块不得导入或调用旧经理业务；保留既有研究规则，各策略分别确定范围；公告自动分析并独立复核；名单按分类和证据排序，不新增综合分；09:25冻结盘前版、阶段完成后更新日内版、16:30生成下一交易日草案；旧历史原样只读；完整工程验收后一次切换入口。

## 三块交付

| 需求 | 独占责任 | 交接对象 |
|---|---|---|
| [A：研究引擎与数据接入](A_RESEARCH_ENGINES.md) | 权威输入适配、公告/美股/超跌研究、名单分类与研究复盘计算 | B负责调用、存储和API；C负责展示 |
| [B：计划、任务执行、存储与API](B_RUNTIME_API.md) | 公共合同、Codex执行器、计划版本、定时入口、读回与历史适配 | 接A引擎，向C提供API；向Mac主控提供装配工厂与调度入口 |
| [C：页面与复盘展示](C_FRONTEND.md) | 新Vue页面、日期/版本导航、名单、详情、进度、历史及复盘 | 只调用B API；不计算策略或在前端判断资格 |

每块由用户指定对应chat；不在本轮创建chat或向其他chat发送消息。每块唯一Luna Max Writer和不同identity的独立Luna Max Reviewer；本主控组织Mac适配、集成测试、部署/API/UI/自然时段验证和问题反馈，不代替三块业务实现。

## 开工与合流顺序

1. 所有chat先读[共同合同](COMMON_CONTRACT.md)，不得自行改字段、规则、范围或排序。
2. B先交付公共类型、规范JSON样例和协议测试这一小批；A、C可同步用本合同设计和模拟输入测试，随后引用B固定commit。
3. A、B、C各自完成范围内代码、必要测试、独立审阅，交固定commit/PR或patch，不宣称Mac已落地。
4. Mac按B合同→A引擎→B实际调用→C实际API顺序集成，先单篇公告真实执行canary，再完整日期、刷新后页面与回归。
5. 完整工程验收通过后，Mac统一切换经理装配、页面和经理任务绑定；保留旧发布版本回退。09:25、日内、16:30真实任务分别验收，未发生时标NATURAL_SLOT_UNVERIFIED。

## 范围和源码身份

本批仅允许修改本目录需求文件；不得修改业务源码、服务、计划任务、历史业务数据或当前工作分支。源码参考根为 `/Users/lexi/Desktop/学习/v4_app`；本地HEAD为 `55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054`，工作树存在并行修改，故HEAD不代表全部当前字节。精确文件身份见[SOURCE_MANIFEST.json](SOURCE_MANIFEST.json)。实际活动API、scheduler、Stage版本没有在本轮重新核验，RUNTIME_IDENTITY=CANNOT_CONFIRM。

GitHub需求基线 `b22836ef3f8fcc6b9218f3422a9bcd7aa61152e9` 是保留旧源码/证据的交接快照，不是完整可运行应用。旧[Mac交接](https://github.com/lexi2016/v4/tree/b22836ef3f8fcc6b9218f3422a9bcd7aa61152e9/handoff/manager-workbench-mac-completion-20261008)及[10月7日方案](https://github.com/lexi2016/v4/blob/codex/manager-workbench-design-20261007/docs/plans/manager-workbench-optimization-20261007.md)只供学习。不能部署该交接树、用它覆盖Mac完整源码，或把旧源码版本当当前运行版本。

各chat以GitHub issue标明的本次需求发布固定commit作为共同起点，在独立 `codex/manager-workbench-a-20261013`、`codex/manager-workbench-b-20261013`、`codex/manager-workbench-c-20261013` 工作分支交付；本轮不创建这些实现分支。该起点用于交付新模块，不是完整应用：A/B以注入适配器和模拟执行器实现可独立测试的库，C在隔离测试环境验证新组件及候选挂载。Mac已有完整应用负责最终接入与全应用构建。不得要求下载不完整快照启动全站，也不得从零重建应用壳。

[学习规则与开发环境](LEARNING_REFERENCE.md)随本次固定commit提供实际源码的必要规则摘录、前端挂载原字节及依赖清单，远端chat无需访问本机路径即可开工。SOURCE_MANIFEST其他文件只标本机集成参考身份，不代表已上传当前字节，也不是实现前提；需更多精确片段时由Mac提供定向脱敏参考。业务配置的33美股标的/审核关系、日历和权威producer通过注入消费，最终由Mac绑定实际owner，不让chat猜测配置或复制共享producer。A/C依赖B后续公共合同固定commit；该依赖不授权修改B路径。新代码路径初始若在实施时已被其他人创建，先比较ownership和字节，不覆盖。

## 必须提交的代码交接

- 唯一目标、Writer/Reviewer身份、固定基线commit、源码根、变更文件及前后SHA；新文件前像ABSENT。
- 可应用的源码与必要测试、依赖清单、启动/调用方式、脱敏配置例子；不能只给ZIP或说明。
- 实际测试环境、命令、结果、独立Reviewer结论和未执行项NOT_RUN；禁止把模拟通过写成真实调用或自然验收。
- API/公共合同版本、依赖的其他块commit、输入owner列表、缺口、回退边界；不上传认证文件、凭证、原始行情、正式计划/响应、持仓、venv或构建产物。
- Mac反馈格式：issue块与候选commit、实际运行身份、复现步骤、期望/实际、失败层、必要脱敏证据、返修允许路径、复验PASS_SIGNAL。对应chat只返修归属范围；共享合同变更先由主控统一裁决，不跨块直接修改。

状态分开报告：IMPLEMENTED、候选TESTED/REVIEWED、INTEGRATED、DEPLOYED、API_VERIFIED、UI_VERIFIED、BEHAVIOR_VERIFIED、NATURAL_VERIFIED。候选PASS不自动证明其后的层。
