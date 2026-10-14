# 美港因子补做回包核对 · 2026-10-14

结论：RESPONSE_CONSUMED / DIRECTION_ONLY。新增行业候选矩阵和公式，但不能作为可直接部署的因子或已验证映射权重。本轮只核对报告，未改业务代码、配置、数据生产链、选股门禁或服务。系统目标仍为V4；回包中V5称谓不构成迁移授权。

已核实的关键问题：
1. ai-stock-pool的排除理由错误。回包称“未发现美股输入”且许可证待确认；仓库的映射实现说明明确存在source_us到source字段、动态美股→A股关系，LICENSE为MIT。这证明存在可借鉴的跨市场关系表达，未证明具备港股预测模型或其当前代码已经验证。
2. 回包称美国收盘北京时间05:00–06:00。NYSE普通股票核心时段到16:00 ET；Python zoneinfo换算2026-10-13 16:00 New York为2026-10-14 04:00 Shanghai，冬令时示例2026-12-01为次日05:00。提前收市另依交易日历。
3. Diebold–Yilmaz引用错配：回包给出的10.1016/j.jempfin.2012.01.001对应Does information vault Niagara Falls? Cross-listed trading in New York and Toronto，不是其标注的溢出论文。不能作为其VAR模型论据。
4. OilFactor的0.5/0.3/0.2及EnergyFactor的0.4/0.3/0.2/0.1没有出处或训练证据。所谓“最佳”“较强”“直接可用”缺独立证据；不得导入正式排序。
5. “只能预测开盘跳空”过于绝对。可分别检验隔夜跳空与开盘后收益，但均未证实；开盘已兑现涨幅不能算开盘后可获得收益。单个行业ETF收益给同组股票相同数值，单独不能完成该组内部个股排名。
6. 关系矩阵缺逐条公司/ETF原始出处和有效时点；DASH上涨也不能直接推出外卖需求恢复。现有关系仅为待核研究假设。

原始核实来源：
- https://github.com/yaoleifly/ai-stock-pool （US/A-share scope）
- https://github.com/yaoleifly/ai-stock-pool/blob/main/线上股票池与美股A股映射实现说明.md （source_us字段及映射逻辑）
- https://github.com/yaoleifly/ai-stock-pool/blob/main/LICENSE （MIT）
- https://www.nyse.com/trade/hours-calendars （16:00 ET普通收盘）
- https://econpub.xmu.edu.cn/research/repec/upload/20122151558587055475115776.pdf （所给DOI的实际论文）
- https://www.sciencedirect.com/science/article/abs/pii/S016920701100032X （Diebold–Yilmaz 2012方向性溢出论文，非港股股票选择成品）

处置：保留XLE/FCG到油气细分、SLB到油服、DASH/UBER到本地生活、BKNG到旅游等待核候选；不采纳未经估计的权重和直接可用标签。关系强度、数据可用性、预测效果分别记录。下一工程阶段沿既有V4权威关系/产物合同补出处和覆盖，先报告候选与缺口；量化效力另需历史完整候选池和时点正确的验证。不再要求用户转发泛泛重写，不新增采集或架构。

无代码测试、回测、部署、重跑：NOT_RUN（本轮无需执行）。原始回包保留本地附件，GitHub只同步此精简核对记录。
