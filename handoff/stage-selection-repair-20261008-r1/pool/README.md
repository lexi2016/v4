# 预选池读取修复复用与新增回归

本批没有再修改池生产器或预选池读取实现。复用固定提交
`4ad7cc52257b49470b3004ebfee9649af43189dd` 中已经实现的参数转发和来源读取修复。
当前任务新增四个回归场景，并核对旧修复与必要测试依赖的精确字节。

## 复用身份

| 文件 | 既有前像 SHA256 | 复用后像 SHA256 |
| --- | --- | --- |
| apps/api/v35_api/app.py | 90a2bf6390c6c0e219aa3d9bb22bc3b3630ecb2d447df494ae69425933424ed7 | 435dcedd3beb43bf4a0ccb35ff6fc033ba536a940990c36f5f23358f5492b590 |
| domains/preselection.py | 3d35e4274c564b826c248367e5bef6f24409b742966723ebeb5f60b726b7f106 | f209ceb037515586883dc669d830fb44afcf778b67971951bde69c5eab8b67a0 |

这些身份来自原修复，不证明届时活动 API 已等于该后像。Luna Max 必须在当前经理台
R3 或更新 API 前像上适配既有小改动，保留经理台更新；不能用旧大文件直接覆盖活动 API。

## 本次新验证

Linux Python 3.14.7：**11 passed**，包含复用测试 7 项与新增测试 4 项。

新增测试验证本地 A=2、配置来源另有不同 A=1 时，只补入精确目标日的 HK=100；
价格日 20261007、资格日 20260930 分别保留。本地 A 不被替换；limit=1、重复读取
不改变完整计数与输入指纹，池 artifact/manifest/receipt 字节不变。
其余三例分别拒绝其他目标日、损坏 manifest SHA、损坏 receipt SHA 的 HK 来源，
并继续返回有效本地 A。所有行情与来源元数据都是合成 fixture。

### 可复跑的隔离命令

```bash
python -B pool/harness/run_isolated_pool_tests.py
```

需要已安装 pytest、FastAPI、httpx 及其运行依赖。本包不携带解释器或虚拟环境。
`test_support/` 仅为固定来源的测试依赖，完整清单与 SHA 在 `TEST_SUPPORT_INDEX.json`；
不能部署这些历史支持文件。运行器只禁用无关 pytest 插件自动发现，不跳过断言，
保留 warnings-as-errors 和项目已允许的 Starlette TestClient 弃用警告。

冻结源码切片缺完整应用依赖与预选池 parts 的 `_namespace.py`。测试提取原 app
中未改写的路由/helper AST，执行原 facade/parts 和真实池存储；支架只提供缺失的
全局名读取 helper、固定日期 catalog，并移除本路由不使用的 SelectionStore 导入。
**完整 create_app 启动、当前 owner 的完整 API canary、Mac、UI、自然时段均 NOT_RUN。**

### Luna Max 在完整候选中的独立命令

```bash
python -m pytest -q tests/test_preselection_source_root_20261008.py tests/test_issue28_preselection_hk_fallback.py
python -m pytest -q tests/test_preselection_pagination.py tests/test_preselection_slice.py::test_native_store_and_api_enforce_dates_statuses_limits_and_receipts
```

先完成发布 P1 审查，再生成基于当前前像的新发布计划。按工单冻结来源验收 10/8
A=178、HK=100；如果输入已改变，必须记录新输入身份，不能硬凑原计数。
真实 API、原 URL 重载与完整 Stage 输入分别读回；池中有 100 HK 不代表 HK Stage
日期来源合同已通过，手工 canary 不代表自然触发已通过。

`RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false`。
