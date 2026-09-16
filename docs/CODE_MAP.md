# V4 源码结构与阅读入口

这是完整来源包的结构说明，**不是当前分支已上传全部源码的声明**。当前状态见 `IMPORT_STATUS.md`。

| 目录 | 完整来源包文件数 | 职责 |
|---|---:|---|
| apps | 85 | FastAPI接口、Vue页面及前端契约 |
| domains | 66 | 研究、复盘、预选池与阶段业务投影 |
| infrastructure | 60 | 原数据存储、证据校验、路径、锁与调度组件 |
| ops | 80 | 原owner的受控执行和同步入口 |
| stage_center | 22 | A/HK分市场阶段采集、选择、存储和消费 |
| v4 | 75 | 经理研究及本次已携带的vendor |
| upstreams | 83 | 已导出的共享代码，不等于外部数据/服务 |
| contracts | 38 | 冻结接口、运行图、迁移及来源契约 |
| tests | 167 | 后端和历史契约测试 |
| docs | 33 | 原项目文档和工程化证据索引 |
| tools | 6 | 核验、离线检查、建库辅助和工具测试 |
| verification | 6 | 有界回归与前端逻辑验证 |
| .github | 8 | CI、模板、归属和预期仓库设置 |
| .tours | 1 | 代码导览 |
| 根文件 | 15 | README、依赖、清单及工程规则 |

## 当前可直接阅读的真实代码

- `../apps/api/v35_api/run.py`：API启动入口，显式绑定数据、ledger、阶段和白毛observations根。
- `../apps/api/v35_api/baimao_router.py`：白毛只读路由与明确的缺源/坏证据原因码。
- `../infrastructure/preselection_pool_store.py`：原预选池三件套、规范化字节核验及同输入中断恢复。
- `../stage_center/contracts.py`：8个阶段、窗口、输出字段和交易安全标志。
- `../stage_center/input_contracts.py`：A股来源池的精确status/producer/source-role契约。
- `../stage_center/calendar.py`：现有冻结日历实现；本次只复制字节，没有重新认证日历业务正确性。
- `../apps/web/src/api/runtime.ts`、`selection.ts`、`review.ts`：原前端HTTP读取和受控生成请求。

## 审查链路

页面请求 → API/router → 原业务投影 → 原owned store → 受日期、来源和哈希约束的artifact/manifest/receipt。

阶段执行另走候选输入绑定 → 固定代码采集 → 原选择builder → raw/bundle/selection/receipt；页面分页不等于后台候选域截断。完整runner、选择器及其依赖本分支尚未导入。

## 已有审查指出、仍需关闭的发布门

依赖声明和uv.lock不同步；缺少原经理proof模块；部分测试导入旧Mac绝对路径；前端原生构建/浏览器未验收；Mac API、scheduler、Stage现役根和源码尚未绑定。历史有界回归不能替代这些发布门。本轮上传没有改业务逻辑。
