# C｜经理工作台页面与复盘展示重写

## GOAL与唯一交付

在现有V4经理入口提供新的Vue工作台，让用户先看到股票、依据、待确认条件和变化，再进入研究详情、执行进度、历史与复盘；只消费B API，不复用旧经理页面逻辑。

WRITER：本块唯一Luna Max；REVIEWER：不同identity的独立Luna Max。ALLOWED_PATHS：`apps/web/src/manager-workbench/**`（含Vue组件、composable、API client、JSON类型、样式和spec）；`apps/web/src/manager-selection/main.ts`与`apps/web/manager-selection/index.html`仅用于改挂载/标题；`apps/web/src/manager-workbench/__tests__/fixtures/**`仅合成规范样例。FORBIDDEN_PATHS：A/B后端、旧ManagerSelectionView.vue及其分块、旧全局样式/协议、App.vue和其他页面、构建/发布/服务配置、业务数据、BUY与Vibe8910。

PASS_SIGNAL：共同合同的实际/模拟响应均正确呈现，五个视图和日期/版本/失败流程定向测试独立通过；构建、必要类型检查通过；实际Mac API和刷新后页面由主控另验。STOP_RULE：API合同缺字段按共同合同报B/主控，不从旧API补值、不在前端构造策略结果、不跨块改代码。

## 页面需求

1. 保留`/manager-selection/`入口，在现有构建入口挂载新Vue根组件；不得另起独立前端、长期端口或第二正式面板。主导航与A股入口保持原样。
2. 顶部统一目标港股日、计划阶段/版本、cutoff、实际更新时间、读取模式。URL保存date/phase/run_id；旧date深链接可读取，旧plan_date有值时解释为目标日，不能沿用旧source-date歧义；公告日期/来源日期放详情，不改变目标日。
3. 今日名单默认主视图：代码名称、总研究分类、公告/美股/超跌独立判定、一句话理由、待确认条件、变化和时间。Stage与尾盘显示独立观察标记，资格未知标明待核；完整计数与分页总数分开。
4. 个股详情展示各路径事实/数值/原文、确认条件、失效条件、风险、时间及资格；证据ID/run/SHA等收起到详情，不占主视图。前端不计算量比、评分或港股通资格。
5. 研究进度按lane显示未运行、运行中、完成、有效空集、部分完成、输入缺失、失败、不适用；未知计数显示未知，不是0。读取更新只GET；生成计划POST并跟随job；恢复失败只调用B retry。取消浏览器读取不取消后台任务。
6. 计划历史显示新旧来源/版本、原run、记录时间和验证缺口；当时记录与事后回看明确分开，后续消息不能变成早盘依据。
7. 收盘复盘通过GET reviews展示完整Top20逐股对照、严格/扩展覆盖、实际名单分母、各策略新增贡献与漏选原因。缺榜单/零分母显示不适用或缺口，不前端计算替代A统计，不将观察贡献算严格入选。
8. 换日/换版本隔离旧行与旧计数；用AbortController和请求序号防迟到覆盖。相同日期更新失败可显示明确标注的上次成功版，绝不改标签称当前。单lane失败不遮蔽其他有效结果。
9. 主名单按服务端分类/证据排序，不新增前端重排评分；支持分类/来源筛选、代码名称搜索及分页，不改变完整counts。表格有列标题、键盘可用详情、状态不只靠颜色；窄屏保留代码、判定、理由，长证据移入详情。

## 接口与技术边界

复用项目现有Vue3/TypeScript/Vite/Vitest，不新增状态框架或UI库。用Vue组件与组合式状态，不手工拼接DOM、不在浏览器解析整个业务payload后再自建研究合同。唯一API前缀及字段见COMMON_CONTRACT.md；规范样例引用B固定commit，C只维护对应TypeScript读入类型，不成为合同owner。

## 必须覆盖的测试

所有lane状态/null/安全字段；有效空集与未知分开；单lane失败仍有有效行；多来源同股一行；大于200行计数/分页；URL深链接、无效日期、date/plan_date兼容；快速换日/换版、迟到响应、重读失败旧结果标识；POST任务进度及retry冲突；旧历史与RETROSPECTIVE标签；Top20完整20行、缺榜单、零分母；键盘与窄屏基本流程。定向Vitest、vue-tsc及Vite构建；无关原有失败单列，不借机清理全仓。

## 交接与Mac分工

交固定commit/PR或patch、文件前后SHA、B合同commit、规范样例与必要测试、实际命令/结果、独立Reviewer receipt。挂载改动作为候选交付，主控在A/B真实API通过后统一集成并验证刷新后的股票、数量、分类、版本与时间；C不能用fixture页面宣称UI_VERIFIED或NATURAL_VERIFIED。Mac反馈后只返修本块允许路径。
