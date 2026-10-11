# 01_公告选股 · 独立修复问题包

## 本包唯一业务目标

公告原 owner 按正确公告日生成或合法导入研究判定，保存可追溯逐股结果，再由三路公告卡片及详情读回同一 run/SHA；必须区分入选、观察、未入选和未评估。

只负责公告，不处理港股通会员/Top100、超跌行情/算法、历史扫描或全局计划身份。历史页面无法展示时提交已核公告 API/产物与接入补丁，由03包解决共用读取问题后做最终页面复验。

## 当前复现

页面 http://127.0.0.1:8873/manager-selection/?date=20261009&plan_date=20261009 。GET /api/v4/manager/research/workspace?date=20261009；本路为 ANNOUNCEMENT。公告日为20261008、目标日20261009。完整原响应派生摘要附在evidence中；其他路字段仅作上下文，不属于本包实现范围。

### 已查明的本路问题

公告已有事后分析结果，但三路摘要没有合法读回

10/09 页面下方已有 10/08 Eastmoney 日期目录：392 条、281 个来源代码；研究入选 55、条件观察 32、未入选 121、未评估 73。catalog run `4b69fa03fbfc4c48b1c410239332505e`；catalog SHA `db1335417ba434016b3c4c23b2bcd13813c54af2d262598cda6fc668e086a798`；基础分析 SHA `d7c3feeaa675382f5007b98e55ff8f7e483471060ba1045be942612dc05e9f5b`；选股判定 SHA `66429d73649fd09478a1c4ac243a69f235cbd546a84ac5e0c412161fdf7671b2`。

上述数量、run 和 SHA 是本轮浏览器可访问性树中显示的观察值，最小转录见 `evidence/announcement-ui-observation.json`；包内未附公告原 owner receipt，未独立核实对应产品，Chat 必须按原 owner 复核，不能单凭这些显示值验收。

这些是已显示的事后研究成果，并非 10/09 盘前 PIT，也非 HKEX 官方全量、港股通资格或 BUY 输入。部分入选属于风险/退市事件，不能直接升格为可买入名单。

检查 `workspace_daily_channels.py` 的 publication_date + target_trade_date + CONSUMED 绑定，以及 `ManagerResearchJobService.import_announcement_analysis` / `refresh_announcements` 的原 owner 产物/运行合同。让合法的研究选股结果在匹配日期和显式口径中显示，不按标题重新猜股票，也不把已有55固定写入代码。历史无 PIT 回执继续明确缺口。对未来日常运行，必须实际验证 owner 生成、导入/注册、归档、API与页面同一 run/SHA。



## 源码与协作边界

源码根 /Users/lexi/Desktop/学习/v4_app，统一入口8873，Vibe8910不动。source/为前一问题包配置指向源码的静态摘录；shared_reference/为只读共用接口参考。两者不是完整可部署release。SOURCE_MANIFEST.json保留原配置根、canonical与配置文件SHA；实际加载进程身份仍CANNOT_CONFIRM。配置所指manifest含NOT_ACTIVATED/base旧状态，不能单凭该字段或LaunchAgent配置决定现役基线；实施前核实际进程/部署回执，保留既有HK/US修复和用户修改。

01和02只修改各自业务owner文件；需要改shared_reference内文件时，只交最小接入补丁和合同给03集成，不直接并行覆盖共用文件。03为共用文件唯一Writer。非所列文件发现必须修改时先明确新增ownership，不能悄悄扩展。按01、02各自交付后03串行集成；三包都不单独覆盖式发布整个旧快照。

## 本包验收（不可降级）

1. 原 owner 的合法日期/来源输入经过实际选股，产物有运行编号、输入与产品SHA、逐股理由；选股规则和BUY边界不变。
2. 保存后重新读取API，重载页面，结果/日期/run/SHA一致。01/02依赖03共用修复未集成时，只能报本路实现/待集成，不能提前报页面闭环。
3. 缺数据明确日期、字段、owner与恢复办法；一路缺件不能遮住其他有效路。输入完整且算法实际执行后0只允许；未知/未运行/缺数据不能写为0。
4. 当时历史、现在回看、未来自然运行分别验收；事后资料不能冒充20261009 09:30之前可得。历史无法恢复不等于可以放弃日常链路修复。
5. 下一实际交易日的自动owner生成、归档、API与页面读回必须验证；未到自然时段标NATURAL_SLOT_UNVERIFIED，手动不能代替自然。
6. Luna Max唯一Writer与不同身份独立Reviewer。提交实际diff、前后SHA、针对性测试独立复跑、真实产物与UI证据及缺口。映射、初筛、HTTP200、测试或报告均不能替代选股完成。

## 全局结案

各包只裁定自己的状态。只有三路均通过，且03的历史读取、计划身份及最终页面集成通过，整体才可结案。03还须验证无关global manifest变化不误失效，而相关输入/date/cutoff变化继续拒绝旧计划。

RESEARCH_ONLY=true；production_allowed=false；buy_gate_updated=false；orders_sent=false。复用既有权威数据和TDX缓存/补采链，不建producer、不伪造历史PIT。没有数据必须报告，不能造股票填名单。

本次是拆包交接，未实施新修复、未测试业务、未部署。原整包审查PASS不自动等于三个新包业务验收PASS。
