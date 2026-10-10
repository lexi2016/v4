# 给Chat的M11任务

## 必须使用用户指定的 Superpowers 插件

用户明确指定已安装的 Superpowers（plugin://superpowers@openai-curated-remote）。本会话须实际选择并使用该插件的相关技能，不能只在正文写插件名称当作已调用。先按 using-superpowers 判断应使用的流程；修复按 systematic-debugging，必要设计/计划在本模块范围内完成，再按 test-driven-development、requesting-code-review 与 verification-before-completion交代码和可核验证据。复用既有总体计划，不再发起全仓设计或仅交第二份计划。

如果本会话无法访问该插件，说明实际入口/可见限制，不声称已启用；把这一问题回传嘻嘻。仍如实区分候选、静态检查、实际测试和Mac验收，禁止伪造执行。


请交付盘中研究与研究复盘的实际最小V5代码候选。先读固定原owner与测试，再做V4 donor→V5映射；不得重新设计通用研究生成器。原算法失败就保留原拒绝并修唯一owner，不能为迁移改模型、常量或BUY门。

## 先核清

逐项列固定source SHA、完整依赖闭包、原CLI/函数、原config与state结构、原API字段、真实导航按钮。SOURCE_MAP列的是已读历史固定代码；Mac仍要核活动版本，不宣称等同现役。research_review_daily.py及私有baseline目录为拟新增，不是现有功能。

## 具体实现

1. 封装原capture_intraday与原run_generation为独立worker，读接口只读已提交结果。外部提供固定config/source manifest摘要，禁止HOME搜旧根、latest代替精确日、fallback换provider或在HTTP层接收任意路径。
2. 六slot逐一保留原聚合/覆盖率/实时池可用性/前一交易日证据与出处。原read_intraday_day只读精确committed slot，READY仍可能含missing_slots/cannot_confirm，不得把READY翻译“全天全槽完成”。
3. 原窗口规则不放宽。没有原窗口输入就错过/阻断；历史有证也须按原owner允许的观察/恢复入口，不把时钟改成过去。避免当日cache冒充盘中quote或live pool。
4. 并发同slot保留一个有效capture，成功复用需核输入/配置/产物摘要。FAILED_NO_REQUEST可原规则重试；已请求或状态不明须原owner核对，不能删marker/HTTP reset重新抓。中断未提交不能读成READY，前成功不覆盖。
5. 日总结使用原same-date锁、原source/provenance/sections/date验证。原--replace是显式再生成，不把普通刷新映射replace。按新attempt/generation保留前成功，必要替换行为交明确接口合同。
6. snapshot模式只用被绑定快照；collect模式按现有原owner与授权调用，不扩大凭据范围。材料晚于slot/cutoff必须隔离，原研究模型身份和来源缺口保留。

## 共享集成

输出INTEGRATION_REQUEST.md，给原/api/v3/review相关M11字段和DailyResearchCommand/研究复盘视图接线建议；完整挂载和V5路由由集成核。不得本Chat直接写共享review API、前端或scheduler。调度只绑定原六slot执行入口；原测试明确没有自动daily generation scheduler，日总结触发按实际合同核，不能顺手加每日生成定时器。

## 必须交付

精确patch及SHA256、基线/候选commit、每文件before/after SHA、原donor完整manifest、最小输入合同、原回归与新增失败测试、准确命令/退出码/日志、Mac独验步骤、单模块回滚、未解决项。fixture通过只能算工程候选；真实slot、日总结、页面和自然触发分别登记。不得只交分析或以未验证wrapper计完成。
