# 387条共同漏选：技术诊断范围

诊断universe是旧独立PASS绑定的COMMON_MISS_CONFIRMED.csv，SHA `7d30cff95d01fdaa8654cb3fa1d43faad727a2ddad786b54c8abcc31106bf9c6`。10/16、19、20、21、22依次92、76、64、65、90条，总387条；日期映射及主因映射在DIAGNOSIS_CONTRACT_R2.json冻结。不是重新选择全A股、改榜单、调阈值或评价新模型。

A原255赋值不变；B原十路OR不变。A/B的BBI、白线、黄线、J分别取各自源表达式；B1严格 `BBI>白线 AND 白线>黄线 AND J<=13`。依赖图、各赋值表达式和终值、比较左右值、条件结果保存在DETAILS.jsonl的a_assignments/b_assignments/b_rules。父节点保留AND/OR结构；OR子句某个false并不独立构成阻断，不能只数false原子推断因果。CSV中文解释是阅读索引，机器明细的完整逻辑树为准。B的BRICK_FANBAO取冻结上游函数，严格大于2/3阈值。

逐事件由旧engine.reconstruct重建原RAW六字段，再按各自D-1截取原前缀及事件，执行原project复权；输入SHA必须与旧账本一致。终值A255、B10状态、两个candidate与旧封存账本逐387比较。每个股票的所有原始源文件hash按旧绑定读回；大RAW selector和archive沿用原完整SHA加inode/size/mtime FAST_BIND。不是重新认证历史全A、跨商数据单位或历史available_at。

Reference共享原parser AST，但没有调用原数字计算helper；用NumPy滑窗和独立scalar递推复算所有A255赋值、B所有源赋值，并另算砖值/反包条件。A的MA/HHV/LLV/SUM允许部分历史、SMA/EMA跳过非有限点保留内部状态、比较NaN转false、BARSLAST从未触发为i+1；B滚动要求完整窗口、Kleene三值逻辑、EMA遇NaN可毒化、BARSLAST未触发NaN。二者差异保留，非自动视为bug。数值差异容差rtol=1e-10/atol=1e-8，布尔与candidate为严格一致。

同AST数值一致只支持这份离线实现的有限解释，不证明parser无误，也不证明通达信/富途原引擎一致。源文本逐赋值与AST映射可供Reviewer查。历史资格、名称时点、publication/revision/available_at、完整跨商amount/volume单位、无限历史EMA初值、停牌日历与真实上市日均保留CANNOT_CONFIRM。原始name为空单列；正量不证明没有历史停牌。

主因按冻结顺序：局部无效或未知数据 → 实现/封存差异 → ENTRYPOOL假 → RISK0>=45 → 角色分数/路由假。多标签另列真实false条件及局部问题。主因先看入口，并不表示角色门一定能过；A全255值与所有多标签保留。

上涨当天D复用同一原公式在D自己的输入重锚，只标后验时点是否才触发，D与D-1分列；不能据此称可预测、改模型或改善召回。新闻/公告为catalyst独立owner的另一证据轴，不作为公式技术原因。

执行：先prepare冻结/登记真实RUN_STARTED，再canary --workers 2，成功后full --workers 4。342代码各一checkpoint，可复用同合同已有checkpoint；不重跑已通过canary。诊断源码不含私有公式/原行情副本，外部同步仅经ROOT逐项allowlist。
