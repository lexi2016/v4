# 02_港股通选股 · 独立修复问题包

## 本包唯一业务目标

精确目标日会员与 D-1 canonical Top100 经原 owner 验证，原 Stage 算法实际执行并保存正式结果，再经统一 API 和页面读回；backfill 不能冒充正式或自然结果。

只负责港股通数据依赖、原 Stage 产物和接入，不处理公告分析、超跌筛选、历史扫描或全局计划身份。不能用全市场、latest、事后补采替代缺失的当时D-1池。

## 当前复现

页面 http://127.0.0.1:8873/manager-selection/?date=20261009&plan_date=20261009 。GET /api/v4/manager/research/workspace?date=20261009；本路为 HK_CONNECT。公告日为20261008、目标日20261009。完整原响应派生摘要附在evidence中；其他路字段仅作上下文，不属于本包实现范围。

### 已查明的本路问题

港股通正式结果与 backfill 混淆，会员/池输入尚未核实

10/09 正式 STAGE_0925 receipt 表示 `selected_rows=0`、`write_performed=false`，错误 `HK D1 status must be STRICT_0_2_READY`。交接材料所谓“10只”来自 backfill `c44b03fa94115911bc4aaa44d2152712` 下 `run-6e62af205e5142401ad186b0`，不能当正式结果或自然运行证据。

既有 owner 为 `v35_dispatcher.research_panel_daily_hk`；目标日 membership V2、D-1 canonical Top100、Stage 输入各自校验。检查 `connect_selection.py`、`domains/manager_research_evidence.py`、`stage_center/hk_universe_preflight.py` 及现役 binding。10/12缺件不能直接当10/09缺件；按实际日期查证。复用共享权威面板，补齐可恢复依赖后运行原 owner/Stage，并把真正保存的选股产品接回页面。不能将 backfill 路径改名、复制成正式或以全市场替代 D-1 Top100。



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
