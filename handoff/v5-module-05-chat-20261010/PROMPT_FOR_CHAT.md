# M05编码任务 · 从现有六lane/七来源到原池发布与阶段消费

你只做原M05。已完成research接线及历史29/29+3项独审，不重新实现hourly，也不要停留在再加wrapper数测试数。先读SOURCE_MAP和历史证据，直接交基于f7cb最小候选。

## 最小分批
1. 对一套真实已存在各来源列target/signal/来源日期、取得时间/cutoff、角色文件及SHA、原owner状态。保留A日历上一session，与HK独立。M09/M12到翌日池是跨日依赖，不建立同日死循环。
2. 原六lane保持完整artifact、行/顺序/分数/理由/拒绝码；原research小时优先，只有FileNotFoundError且两份SHA-bound preview/selector齐备才fallback。错日/receipt错/坏schema不回退，五健康lane不被坏research清空，未知程序/guard错误仍fatal。
3. V192非空已验直接复用；verified-empty现有LEGACY_EMPTY_STATUS_CONTRACT_MISMATCH若阻断本批，先读原reader与validator精确合同给最小修复，不伪造producer/bundle或换成随便VALID_EMPTY。若不阻断则独立列缺口，不能声称全七来源合格。
4. 新a_preselection_daily封装原writer与原consumer，写V5私有正式池/产物并独立读回。先核writer完整闭包，沿原PreselectionPoolStore事务与不可变键语义，EXPECTED_MISSING只记DEFERRED，不占成功键；旧成功不得失败覆盖。
5. 聚合、去重、分数与排序调用原consumer，完整合法集合交M07。若跨市场公用入口只收窄A，不写HK池。共享contract/publisher/UI/gateway/调度接线给统一集成请求，不直接改。
6. 先验真实已有池读回，再新适用日原owner生产/保存；历史周五152行不能当完整周一，合成preview不能当真实fallback，自然/PIT标志不得强置true。

## 修改边界与测试
仅M05自有逻辑及新daily/定向测试。a_preselection中guard/loader/path/请求等共享函数有其他模块依赖，改它们必须统一集成；不为了M05放开所有读写或网络。vendor原字节不改，复用原算法。
新增测试涵盖正式保存/重复/冲突/失败旧成功、七来源状态映射、原consumer集合等价、有效空与未知、周末跨日窗口、强制错日不fallback、output readback和M07身份。只跑受影响必要测试，历史通过引用；无真实原件标NOT_RUN。

## 必须交付
1. 唯一固定candidate commit或完整候选包、base ref、donor→现有V5目标映射；已等价实现不改。
2. before/after完整修改文件、runtime.patch、reverse.patch；每文件Git blob SHA、before SHA256、after SHA256，新增文件before=ABSENT，删除说明用途；不编造未来after值。
3. 依赖/私有输出/输入manifest清单，原算法等价用例与失败用例源码，原始测试命令/环境/退出码/日志；没有真实数据时标NOT_RUN。
4. 共享变更单INTEGRATION_REQUEST：共享目标路径、before SHA、调用方、接口与日期/cutoff/失败语义、向后兼容、验收方法；统一集成者实施，Chat不附共享文件覆盖补丁。
5. MAC_APPLY_AND_ACCEPTANCE：前像检查、隔离应用、必要回归、真实输入/独立读回、API/页面、唯一发布窗口及单模块回滚。部署路径/端口未知时列现场核实项，不猜命令。
6. 五层分别报告代码候选、Mac工程测试、真实业务生产/保存/独立读回、API/原页面、自然接续与回滚。历史测试不相加，不冒称本轮运行。
缺当前Mac active前像不阻挡固定f7cb静态候选；嘻嘻安装前核active SHA。不要要求Chat连Mac，也不要向用户索取已有GitHub材料/整库/凭据。保留V4、8910与BUY门，不交易，不扩大安全权限或凭据。

