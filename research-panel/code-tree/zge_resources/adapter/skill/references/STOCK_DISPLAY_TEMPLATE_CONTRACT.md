# 固定选股展示模板合同

模板 ID：`stock-structure-history18-v1`。用户于2026-10-27指定基准：[history18 单股工作台](https://stock18-structure-workflow.sunlitcloud6.chatgpt.site/history18#300770.SZ)。文件 SHA 见同目录 [机器清单](STOCK_DISPLAY_TEMPLATE_MANIFEST.json)，包括 `history18.html`、`app.js`、`styles.css`；这些 SHA 标识本次设计基准，不代表未来数据版本，也不代表线上版本已核验。

## 1. 固定的是查看顺序，不是筛选策略

日常只更换已验证的股票映射、数据包及对应分析日；不每批重造布局。布局、主要交互顺序的变更先取得用户明确同意；纠错、数据更新仍在原授权范围内。此条是本看板的产品约定，不改变平台审批、权限或其他任务。

保持 history18 的 DOM/信息层级：
1. 左栏 `.sidebar`：研究范围 → 金额门与排除项 → `search` → 分组 → `stockList`。
2. 右栏 `identity`：名称/完整代码/研究批次/数据时点；`selectionNotice` 明示过期或不在当前集合。
3. `decision-grid`：`why` 为何关注 → `wait` 现在等什么 → `invalidate` 什么情况放弃；紧随最强 `counter`。
4. `levels` 与 `signals/coverage`：关键K最高、实体底、最低分别，白/黄/BBI分开；原式标签与研究判断分开。
5. `.chart-card`：默认直接显示大图，不藏在弹窗或“打开原图”链接。60/120/全已加载图、日期选择、信号筛选；主K线/量柱/KDJ同一交易bar横轴；缩放、拖动、逐日提示、前后移与滚动条。
6. `.research-grid`：历史买点表现 → 价格位置 → 行业与催化 → 股东与筹码；随后证据/缺口和研究边界。

保留原图入口查证完整51变量/22绘图；当前85轻交互包仅投影部分原字段，不冒完整51/22交互复刻。中塑只有19根，不填充180根。空指标断线/UNKNOWN，不补零。

## 2. 模板与股票报告包分离

每份报告逻辑身份键为 `(symbol, analysis_asof, data_version)`，六位代码仅通过已核 manifest 唯一映射为完整 `xxxxxx.SH/SZ/BJ`；不凭首位猜交易所。未知代码、不唯一、缺包、错日期、坏SHA必须清空当前图与报告，显示明确缺口，不能落回示例、第一只或上一只。

概念报告 schema（模块未齐可以 PARTIAL，不可伪造）：

| 字段/模块 | 合同 |
|---|---|
| template_id | 固定 `stock-structure-history18-v1`，独立于股票与数据版本 |
| symbol/name | 身份与每个模块一一匹配；name未知不从别股借用 |
| analysis_asof | 分析信息截止日期/时刻；精确历史日期不得就近替代 |
| daily_cutoff | 实际日线最后交易日，独立于分析日；本包为20261026 |
| quote | source_at、received_at、价格口径、金额单位、原始来源/hash；缺失 null，不用日线收盘冒当前价 |
| chart | `symbol, chartRows[], source`；每bar原OHLC/volume/previousClose/values/priceFacts，详见投影schema |
| decision/levels | 本股票本时点支持、等待、失效、反证、多锚；坐标资格未知不能称确定可执行raw价带 |
| history | scope/分母/成熟窗/来源/hash；原式历史统计不是本次形态胜率；无当前原信号时同组合N/A |
| events/holders | 披露时间与事件/统计时间分别；历史asof只能用当时已公开证据 |
| evidence/missing | 逐模块状态与来源；UNKNOWN不是0、false或空样本成功率 |

模块状态使用 VERIFIED/PARTIAL/UNKNOWN（仅表述该模块证据，不是整股买点认证）。模块数据和来源均需按symbol/date核对，不得仅改页面标题。切股请求带序列token，旧请求后返回不得覆盖新股；加载/失败期间隐藏旧图旧结论。日期切换同样适用。

## 3. 当前可复用范围

- 85轻图来源 `research_outputs/live85_chart_projection_20261027/source_manifest.json` 与 `schema.json`；逐股SHA、源快照和receipt绑定。原值保留，不重算公式、不抓行情、不自算复权比例。
- 24股历史来源 `research_outputs/live24_cached_history_20261027/DASHBOARD_HISTORY24_COMPLETE.json` 与同目录 `AUDIT_ACCEPTANCE.json`；其他股该模块UNKNOWN，不能借用24股或旧18/捷顺示例。
- `sites/stock18-workflow/dist/live85_data.json` 是展示投影，不作为原计算/准入签发者。各quote overlay保留自己的source时间，不能声称全85同一新时点或自动实时刷新。
- 旧18是独立历史批次；`history18`不换成当前85的标题/含义。股池、筛选门和原公式完全不由此模板改变。
- 历史asof若没有冻结报告包，先报 DATE_NOT_PACKAGED；不得把D27判断/新闻/quote倒灌D26。允许显示事后走势的复盘模式必须明确标注，不把事后走势用于当时判断。

## 4. 小型本地入口与验收

从项目根运行：

```bash
python -B zge_resources/adapter/skill/scripts/stock_display_bundle.py --symbol 301686 --asof 20261027
```

该入口仅验证并返回冻结**图包**，不自动取得完整报告，不网络抓取、调用reader、重算原式或发布。`--asof`为精确分析日期，**不是把D26图尾伪装D27 K线**。输出quote/research_report保持null；完整看板由独立UI消费已绑定模块。输入契约由机器清单绑定当前85 manifest，未知ticker不能端到端自动研究。

相关测试/备份/diff在 `research_outputs/stock_display_template_contract_20261027/`。本地测试证明选择器输入保真与失败隔离，不证明真实浏览器交互或线上发布。实际UI验收由UI工作项独立记录。Skill宿主自动发现/注册仍 **NOT_RUN**。
