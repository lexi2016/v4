# A/H 收盘模块候选

两市场复用不同的原业务，不能把普通盘中选股改名当收盘复盘。

## 港股

复用 build_native_close_review：以声明全港股通收盘行重建涨幅Top20，比较0.2 Top100及七个阶段的覆盖率和归因。七阶段不包括Stage8。固定源14文件含日历，业务源码原字节保留。

原数据至少600个唯一代码，全声明集合必须100%覆盖、同日、close/pre_close正数；常规日采集>=16:10，半日>=12:10且不能带下午阶段非空数据。原调度16:08节点会等待16:10，不把该等待流程误报为故障。

V5只读回放明确status=CANNOT_CONFIRM，原状态保存在legacy_status；未提供权威来源时不能升级成MODEL_REVIEW_READY。模型或阶段证据缺失，对应hit为None、分类CANNOT_CONFIRM；[]只表示DECLARED_EMPTY，None表示MISSING。sidecar不伪造原receipt或PIT证明。14项测试定义，待Mac执行。

## A股

复用 build_close_model 单一原核心及交易日历，输入为完整声明当日panel，不能用阶段Top10替代。原模型输出市场广度、板块与角色观察，不是HK Top20命中率。

收盘panel显式字段、全声明codes、同日、有限数值和>=15:30采集门槛；不把原硬编码15:30 as_of当实际采集时间，实际available_at单独保留。原场景概率是冻结常量，不是新校准模型。原公式和业务字段保留，status=CANNOT_CONFIRM、legacy_status保留原状态；严格15:00 PIT、来源及全市场资格未验证。9项测试定义，待Mac执行。

## 接入与运行

当前仅SYNTHETIC/RECORDED_INPUT_REPLAY。日期与SHA声明不等于权威owner验证。后续复用Mac已有V4原产物和采集器时，必须绑定原始manifest/receipt/raw SHA/availability及资格日期，保留缺口，不改旧日期造新结果。

原collector源码已定位，但本候选不调用SDK、不采集、不写V4、不发布原store、不发订单。独立worker使用Python审计限制，OS隔离未验证。root只做AST/摘要检查；测试只由既有Mac任务执行。
