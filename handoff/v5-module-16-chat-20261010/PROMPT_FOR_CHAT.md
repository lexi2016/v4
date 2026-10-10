# 给Chat的M16任务

## 必须使用用户指定的 Superpowers 插件

用户明确指定已安装的 Superpowers（plugin://superpowers@openai-curated-remote）。本会话须实际选择并使用该插件的相关技能，不能只在正文写插件名称当作已调用。先按 using-superpowers 判断应使用的流程；修复按 systematic-debugging，必要设计/计划在本模块范围内完成，再按 test-driven-development、requesting-code-review 与 verification-before-completion交代码和可核验证据。复用既有总体计划，不再发起全仓设计或仅交第二份计划。

如果本会话无法访问该插件，说明实际入口/可见限制，不声称已启用；把这一问题回传嘻嘻。仍如实区分候选、静态检查、实际测试和Mac验收，禁止伪造执行。


请把原经理候选公开资料job生命周期接入V5，交付实际可应用最小代码。以固定源码为事实，首先给原owner/完整依赖SHA→V5已有或拟新增路径→任务/产物/API/页面映射。不要把M18 workspace只读投影当job执行，也不扩成新研究平台。

## 实现要求

1. 复用原ManagerResearchJobService、原provider/缓存/内容合同/资格规则与store fencing。完整service依赖未在V5冻结，建立本Chat私有闭包manifest并核真实Mac活动版本；不可整文件替换M18的manager_plan/vendor。
2. 固定候选由server-owned原观察输入读取。保留target_trade_date、stage_id、market、cutoff、input_identity、source SHA、job_id、generation和attempt。API拒绝任意股票/URL/命令/正文参数，不新增客户端自定义采集。
3. GET/status/jobs只读已提交结果与真实任务状态，不能触发ensure、迁移发布、provider、目录创建或journal恢复。worker初始化写操作与只读server分离；缺store返回明确缺失。
4. ensure重复点击同身份只允许一个有效job；队列容量/超时/关闭有原状态。失败、未知、PARTIAL_WITH_ROWS、有效空、READY分开。新输入新身份，不把前日缓存当今日。
5. retry沿原force语义另attempt/generation，旧成功与失败证据保留。原进程已失去的RUNNING/QUEUED保持owner-unowned阻断，按原owner核对后恢复，不能删lock/job marker强行重跑。
6. cancel只影响指定job/date/generation；发布前后竞态均受原store屏障。撤回页面读取/取消轮询与取消后台job分开。底层native调用不可抢占时保留真实状态，不承诺已终止外部调用。
7. 事件更新必须保留财务facts与来源receipt，不重抓PDF；事件来源全坏保持CANNOT_CONFIRM，旧财务仍可读。事件merge基于锁内最新财务产品，晚到旧attempt不得覆盖新结果。
8. 长任务独立worker，普通经理读可及时返回。错误只回非秘密reason code，完整诊断留已授权本机；不能将token/credential路径或SDK异常原样放进UI。

## 路由和前端只交接口请求

原/api/v4/manager/research提供GET、/status、POST /ensure、/retry、/events、GET /jobs/{job_id}、POST /jobs/{job_id}/cancel。原route的同源、精确date、无客户端body约束保留。V5实际挂载由集成者核，其他/workspace、/announcements等不是M16写入范围。

INTEGRATION_REQUEST.md须列普通只读进入页、显式生成/重试/取消/事件更新、轮询、终态产品identity、不自动POST ensure、关闭/返回仍保留后台状态。Chat不跨写共享前端、gateway、调度或M18。

## 交付

固定候选commit、精确patch SHA256、逐文件before/after SHA与donor manifest；原回归/新增失败测试及命令退出码；真实Mac步骤、回滚、未解决绑定。至少给可执行代码，不仅建议。只有真实任务全生命周期和页面/恢复通过才可关闭M16；不以公告某子路径或合成provider通过代替。
