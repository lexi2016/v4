# 独立模块 API 与 V4 前端兼容入口

用户要求：沿用V4前端，后端及API按模块拆分，不在一个业务API进程里混装所有职责。

本候选 api_gateway.py 只分发已配置的原相对URL，不包含选股、研究、采集业务。每个module绑定唯一loopback端口、release声明、独立timeout和并发名额；配置未列出的路由404，不回退V4。GET/POST必须按路由明确允许，POST非空体仅接受application/json。路径和query原样转发，旧预选分页字段不能丢。

## 故障与资源边界

- 上游统一硬截止时间覆盖连接/请求/headers/正文，超时关实际socket，504/CANNOT_CONFIRM
- 模块忙429，不占用别的模块名额；入口最多64连接，收包5秒绝对期限
- 请求1MiB、响应16MiB；Content-Length不完整返回502，合法JSON也不能冒充完整响应
- UTF-8 JSON在对象分配前做64层/20万节点预检，拒绝非有限数；后置懒遍历复核
- Host/Origin限制本机；拒绝redirect，不转发cookie/Authorization/调用者Host或hop headers
- 原模块HTTP状态和完整JSON字节保留；网关错误明确原因，不生成空股票列表

## 真实边界

这是分发代码，不是所有模块HTTP服务已经运行。release_id目前是配置声明，health标注GATEWAY_ONLY、NOT_PROBED，不能当实际release校验。独立进程/依赖、服务启动、发布回滚、原V4前端完整接口适配及真实数据接线仍需落实。

原V4前端的预选/阶段/收盘/经理外壳和状态字段不能由网关擅自重写；各模块compat facade须复用原投影并兼容原query。混合A/H响应的组合逻辑也不在网关内造假。

12项测试定义，包括URL/query、并发隔离、MODULE_BUSY、超时后名额释放、headers滴流、截断JSON、POST原字节/header过滤、Origin、JSON资源限制。root仅AST与静态审查；等待现有Mac任务实测。未启动、部署网关或业务API，未占用8873。
