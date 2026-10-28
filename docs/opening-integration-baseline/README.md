# V4 开盘集成源码上下文（2026-10-28）

这些文件是 `/Users/lexi/Desktop/学习/v4_app` 的本地源码快照，路径保持仓库原相对路径。`SOURCE_MANIFEST.json` 为逐项允许清单、SHA-256、Git blob、采集时工作区和索引状态；`DEPENDENCIES.json` 记录静态依赖闭包、动态依赖和缺口。它不是独立可运行的完整 V4，不代表当前 API 或 Stage 部署身份，不含行情、业务运行数据、配置、凭证、服务状态、历史原始数据或测试行情 fixture。

包含 A/HK 的 stage 采集、原始存储、selection、runner、节点入口、预选服务与路由、相关合同、基础设施和六份测试源码。`app.py` 作为应用接口上下文按字节保留：其历史校验身份/哈希为源码常量；完整应用初始化的其他业务路由没有递归纳入。当前 `app.py` 自行定义 `/api/v3/preselection-pools`，没有发现它引用独立的 `preselection_router.py` 或 `preselection_service.py`；两者存在不等于已接线。

静态依赖图包括方法体内的 Python 导入及 facade `_parts` 模块；已收录 canonical 内被实际引用的 13 个 `upstreams/v3_shared_data` Python 文件，仅供说明现有代码依赖，不授权使用旧数据、旧服务或另建 producer。已收录 canonical 内被实际引用的 13 个 `upstreams/v3_shared_data` Python 文件，仅供说明现有代码依赖，不授权使用旧数据、旧服务或另建 producer。动态导入、共享数据根、外部采集 SDK、运行配置、应用其他模块和测试 fixture 有缺口，详见依赖清单。未运行测试、采集、服务、调度、API 或 UI；仅进行字节与 Python 编译检查。

`RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。
