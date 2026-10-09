# 拆分架构交接 ownership

用户已明确要求阶段选股与经理工作台拆开相互影响的部分，独立API和发布窗口，先交拆分问题包。

- 本会话负责唯一只读architect、Stage侧既有身份/候选状态及本architecture目录文档。
- 经理会话01a11b41-3ebc-7dc3-a902-798efe90d567负责唯一问题包Writer、独立Reviewer和GitHub固定交付。
- 不双写同一包，不发布共享API，不改服务或业务数据。Stage候选Writer收束未改源码状态；经理已得候选保留。
- 设计保持8873统一页面/同域，Stage与经理各自API、版本、配置、manifest/binding、发布/回滚；共享入口和静态平台边界独立owner，模块发布不能改平台或另一模块。
- 数据层/算法/池/BUY边界不变。架构文档不代表程序已实现或发布。
