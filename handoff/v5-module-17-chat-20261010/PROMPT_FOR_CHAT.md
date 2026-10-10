# 给Chat的M17任务

## 必须使用用户指定的 Superpowers 插件

用户明确指定已安装的 Superpowers（plugin://superpowers@openai-curated-remote）。本会话须实际选择并使用该插件的相关技能，不能只在正文写插件名称当作已调用。先按 using-superpowers 判断应使用的流程；修复按 systematic-debugging，必要设计/计划在本模块范围内完成，再按 test-driven-development、requesting-code-review 与 verification-before-completion交代码和可核验证据。复用既有总体计划，不再发起全仓设计或仅交第二份计划。

如果本会话无法访问该插件，说明实际入口/可见限制，不声称已启用；把这一问题回传嘻嘻。仍如实区分候选、静态检查、实际测试和Mac验收，禁止伪造执行。


请给尾盘量价发现与持续跟踪一个最小具体V5代码候选。先按固定源码和Mac活动证据核唯一owner、当前capture mode和完整闭包，再列V4 donor→已有/拟新增V5路径、输入、独占输出、API和原页面映射。不要另写策略，也不要把超跌或Stage结果改名当M17。

## 先明确原两条路径

- 1530现场：prepare_universe/materialize、原universe owner、fetch_futu_snapshot、snapshot attestation、pre-capture history、catalyst/prior验证、原payload与独立readback。
- late PyTDX：recapture_close_minutes及原1555 executor连接，源交易日/下一计划日/真实capture time分开，精确D1池和原窗口绑定；不得写1530 lane。选哪条运行遵从既有Mac活动mode，不擅自切换。

原materializer内clock/fetcher注入仅用于SIMULATED测试，不暴露为生产CLI时间覆盖。半日/非Connect交易日没有1530现场，不能猜半日槽。Late合同只允许原current或previous适用session，不能扩大历史任意回填。

## 代码交付重点

1. 封装原owner至本模块私有根；读M02/M04/M06已提交输入，避免重复采同源。原默认root、APP_ROOT检查和provider闭包都要明确隔离绑定，不能只是替换目录字符串就宣称迁移完成。
2. 1530缺原窗口不重采当前行情，不造received_at/available_at。预捕获history缺失就阻断，不能用更新后的面板填补。late的received_not_historical_1530与非最终收盘、量纲未核标志原样保留。
3. 保留原币种/单位/历史完整性、重复quote冲突、PIT/催化出处验证、strict/near/unknown研究观察语义。M14可共用只读原authority但不能共用结果身份、写根或补丁owner。
4. 实现按原实际合同持续跟踪：只接完整verified prior，保留first_seen/last_seen/prior run/SHA、后续新催化及原失效条件。没有后续quote/来源不能假装失效已确认；旧event时间不能充新催化。每天适用触发是否存在须实际绑定，不凭文本创建额外collector。
5. 相同输入身份重复触发幂等；失败/中断新attempt保留前成功及当时证据。原reader要求新失败/运行不能当作当前旧卡片，历史成功只允许明确历史/过期区显示，不掩盖本次失败。
6. GET与页面刷新只读artifact/receipt，不准备universe、不抓行情、不物化跟踪。后台worker与API隔离；成功必须原计算、保存及独立reader同SHA，不只HTTP200。

## 集成请求与交付

本Chat不写前端、gateway、全局调度或M18。另给INTEGRATION_REQUEST.md：原/api/v4/manager/workbench-research的date/market/slot只读合同、1530与CLOSE_RECAPTURE分列、跟踪理由/失效条件、M18已提交引用、活动mode/真实时段绑定。原Stage失败后late仍可独立尝试，不把它的成功反向升级Stage。

交精确patch与SHA256、base/candidate commit、每文件前后SHA、原闭包manifest、原回归和新增失败测试、Mac实际步骤、回滚和缺件。代码、真实输入、页面、自动接续、完整验收分别汇报；仅旧投影/模拟通过不能关闭M17。

活动mode未知不阻挡静态适配候选：按两条固定原路径交代码及契约测试。生产入口必须显式绑定已核mode，unknown拒绝执行，不默认选择、不同时双采；实际mode由Mac部署前核实绑定。
