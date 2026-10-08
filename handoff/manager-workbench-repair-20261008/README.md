# 经理选股工作台：修复候选与分层验收交付

**本包交付了业务代码修复、回归测试、独立审查、精确补丁和部署核验要求。它不是已部署的完整 release，也不证明三路已在 Mac 自然运行。**

冻结问题包基线：[`lexi2016/v4@0fd5eb374cb155232ed003d5fc4d0d3594252491`](https://github.com/lexi2016/v4/blob/0fd5eb374cb155232ed003d5fc4d0d3594252491/handoff/manager-workbench-problem-pack-20261008/README.md)。已先读取并核对 README、evidence.json、source_map.json 的全部内容及 manifest SHA。

## 已交付的修复

| 范围 | 实际行为变化 |
| --- | --- |
| 公告一致性 | import、analysis GET、workspace 共用精确日期对的消费校验，核产品/source/judgment/handoff/owner/evidence run/cutoff；保留失败产品身份和具体原因。当天有效产品不会被旧产品的坏回执遮住。 |
| 公告判断完整性 | 合法导入但 NOT_ASSESSED 的产品显示待核，不冒充已核空集；原始入选理由与引用直接进入首屏。默认晚间请求补入次日计划的正确公告对。 |
| 港股通 | 正式资格只接受目标日 HK_UNIVERSE_V2；D-1 capture 另列。已定位真正的 D-1 Top100 Stage 消费者并保持其代码不变。缺原归档/发现等 focus 输入时不能报告空选股。 |
| 超跌 | 修复补充数据读取时丢失 panel 发布时间的字段错误；按原 HK 日历区分盘前/盘后已完成完整交易日；原门槛 0.80 与 1.5 保持不变。未证明量纲的数据保留数值观察，数量门为未知/待核。 |
| 原计划调度 | 沿现有 hook、固定 loopback RPC、fully injected API service 和原 plan owner 恢复早间/盘前调用，保留真实运行类型；同一 run 的产品与封存 attempt 必须一致。幂等、有限重试、窗口拒绝及中断回执均有回归。 |
| 截止时间与重载 | 在产物和最终 journal 读回后检查截止时间；晚完成持久化为 FAILED，之后 GET 不再变成成功。历史读取支持早间计划并保留精确 run/attempt。 |
| 美股隔离 | 普通 US reader 异常不能遮住独立渠道；计划 RPC 不再同步执行可能阻塞窗口的 US 可变准备。已有 US 结果仍由原 reader 消费，缺独立调度保持 NOT_ATTEMPTED/NOT_EVALUATED。 |
| 首屏 | 三路分别展示股票、原理由、实际数据日、运行编号与状态；三个选择日期独立绑定。未知数量不填零；手工后按选定日期 GET 读回；取消/迟到响应不覆盖当前页面。 |

以上行为不新增行情 producer，不改变 Stage、BUY、Vibe8910、选股排序或研究规则。所有安全字段保持 `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。

## 验收层级

| 层级 | 本轮证据与结论 |
| --- | --- |
| 代码测试 | **123 项后端测试通过，29 项前端测试通过，涉及文件的严格 TypeScript 检查通过。** [后端日志](evidence/tests/backend_final.log)、[逐项后端结果](evidence/tests/backend_cases.json)、[前端日志](evidence/tests/frontend_final.log)。 |
| 独立审查 | 7 项 Important 问题逐项复现、修正、复核；无未关闭的候选代码重要问题。[完整审查](evidence/independent_review.md)。复核批次存在重叠，不能把批次数量相加。 |
| 交付核验 | 17 项校验工具测试通过；正反补丁逐字节往返通过。另完成 [独立交付审查](evidence/delivery_review.md)，修正报告路径问题并保留初始失败证据。 |
| 部署 | **NOT_RUN。** 未访问实际 Mac，未切换 API/scheduler，未改 binding、launchd 或正式数据。完整源码依赖闭包及当前进程加载指纹仍需现场核验。 |
| API | **合成集成 PASS；现场 NOT_RUN。** 使用原 FastAPI 路由、真实临时 ManagerResearchStore、原 service 与完整 workspace，验证导入、analysis、workspace 的相同 SHA/run；源 catalog 与时钟为明确合成注入。GET 零写入、零 refresh 已测。 |
| 页面 | **29 项 jsdom 请求/DOM 回归 PASS；真实浏览器页面 NOT_RUN。** 独立复核另验证了 5 类 Python 实际输出到 TypeScript 准入。未取得 Mac 重载截图。 |
| 完整前端构建 | **BLOCKED。** 冻结源码缺 `daily-research-command/index.html`，原 Vite 多入口构建在 0 modules 阶段失败；远端也未提供 `manager-selection/index.html`。不能称为生产构建通过。 |
| 自然运行 | **NOT_RUN。** 没有未来真实 scheduler 触发、原 heartbeat reader/reviewer、每路产物及 API/页面联合证据。手动或离线成功不替代这项。 |

测试环境为 Linux、Python 3.14.6、冻结 uv/npm lock。后端唯一 warning 是既有 Starlette/httpx 弃用提示，依赖未改。[完整环境与 lock SHA](evidence/environment.json)。

## 版本与部署边界

问题包映射的 13 个文件中，组装基线与所列 canonical SHA 有 11 个一致。另两项必须分别处理：

- `announcement_analysis.py` 沿用明确登记的 R3 兼容版，本轮未改，SHA 为 `b60b8c0c663b203d2ece5a5b451eb41ca296396b2db3630dff4a92a8566f373f`。
- `businessStatus.ts` 远端只提供较旧版本，和问题包所列当前 SHA 不同。本轮没有覆盖它；web 前像校验会要求现场保留所列当前版本，漂移须重新核对。

这 11/13 的比较是**仓库交接源码之间的比较**，不是实际进程加载版本证明。[逐项比较](evidence/source_identity_comparison.json)。

现役配置在冻结记录中指向 R3 API；scheduler 仍为 `hk-research-calendar-all-r1-20261007-scheduler`，R2 scheduler 与计划绑定未启用。现役 scheduler 已有 hook，R2 daemon 的校验/readiness 增量作为单独前置文件提供。**必须从实际现役 scheduler 的完整已核副本构建候选，保留其 launcher、runner、due.py 和 native 依赖，不能整体部署组装树。** 旧组装 launcher 丢失现役 HK panel/no-site/timeout 检查。

详见 [源码与部署闭合](docs/SCHEDULER_CLOSURE.md) 和 [部署、回滚、分层验收步骤](docs/DEPLOY_AND_ACCEPT.md)。旧 C1/final renderer 的 API 根和 SHA pin 已过时，并遗漏 `morning_plan`，不能直接运行当作本次部署。

## 尚未闭合的实质条件

1. **真实成交量单位/倍率证明。** 现有 HK02 与已接入补充源明确保留 `NOT_PROVEN`。本包没有足够权威证据把数量门提升为已确认，因而不能承诺真实严格超跌候选已可产出。
2. **原 06:30 heartbeat 的真实 reader/reviewer 任务。** 旧元数据 `automation-3` 不是可核验任务定义；自然 capture → 阅读 → 独立判断 → 注册 handoff → 原 owner 导入仍需接回原执行者。未通过重复手动导入制造闭环。
3. **Mac 当前数据与版本。** 目标日 V2、对应完整日 panel/manifest/master、当前 API/scheduler 完整依赖与实际加载模块未在本会话读取。
4. **独立 US 准备入口。** 冻结源码未提供 `us_mapping_research.py` 的实现及可验证有界自然入口。保持真实缺口；这项不再阻塞三路独立计划消费。
5. **完整 build、部署与自然时段。** 缺原入口/私有依赖和夹具必须从当前权威源码补回后验证，不得凭造文件或改 pin 通过。

## 文件与使用方式

- [`source_manifest.json`](source_manifest.json)：15 个业务源码、8 个测试文件及 1 个 scheduler 前置文件的精确前后 SHA、源路径和 profile。
- [`package_manifest.json`](package_manifest.json)：除该清单自身外，全部交付文件的大小、SHA-256 和 Git blob SHA；用于同步后的逐文件读回核对。
- [`after/`](after/)：本轮修改后的必要文件；不含完整运行树、行情、账户数据、venv、node_modules 或 dist。
- [`source_delta.patch`](source_delta.patch) / [`source_delta.reverse.patch`](source_delta.reverse.patch)：本轮 23 个文件的正向/反向补丁。
- [`scheduler_prerequisite.patch`](scheduler_prerequisite.patch) / [`scheduler_prerequisite.reverse.patch`](scheduler_prerequisite.reverse.patch)：现役冻结 daemon 到已登记 R2 daemon 的单独前置增量。
- [`tools/verify_delivery.py`](tools/verify_delivery.py)：只读核验包字节和所选源码根的精确前像/后像，不部署、不改源文件。
- [`evidence/patch_roundtrip.json`](evidence/patch_roundtrip.json)：两组补丁在隔离副本正向应用、反向恢复后，全部文件逐字节 SHA 一致。
- [`evidence/results.json`](evidence/results.json)：验收状态、已知失败和剩余条件。

核验示例，`--source-root` 必须是对应 profile 的**实际完整项目/app 根**：

```sh
python3 tools/verify_delivery.py --source-root '/实际/API/app/根' --profile api --against before
python3 tools/verify_delivery.py --source-root '/实际/前端项目/根' --profile web --against before
python3 tools/verify_delivery.py --source-root '/实际/scheduler/app/根' --profile scheduler_prerequisite --against before
```

`web` profile 使用相对于项目根的 `apps/web/...` 路径。任一前像不匹配就保留原差异，先做针对性源码对齐；不能更新 pin 或扩大覆盖范围来绕过。校验通过只证明所选文件字节，**不证明整个运行依赖、服务已切换或自然运行**。

代码测试、完整构建缺件、部署、API、页面与自然运行应分别给出真实结论。本交付分支仅供取代码和独立核验，不表示 merge 或服务切换。
