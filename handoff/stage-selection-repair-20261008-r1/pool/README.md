# A 预选池：复用已有修复，补精确日期 fallback 回归

## 本批结论

复用冻结提交 `4ad7cc52257b49470b3004ebfee9649af43189dd` 下
`handoff/a-preselection-source-20261008` 的已实现源码，不再制造第二份池读取实现。
本批只新增 4 个测试场景，业务源码没有增量修改。

| 复用文件 | 已有后像 SHA256 |
| --- | --- |
| apps/api/v35_api/app.py | 435dcedd3beb43bf4a0ccb35ff6fc033ba536a940990c36f5f23358f5492b590 |
| domains/preselection.py | f209ceb037515586883dc669d830fb44afcf778b67971951bde69c5eab8b67a0 |
| tests/test_preselection_source_root_20261008.py | 46330d42709005822e381c5566d7097cc54cc841193bee738fca151b9a8af5ff |

这些是已有冻结源码身份，不证明当前 API 活动文件等于上述字节。Luna Max
仍需以届时经理台 R3 或更新活动前像适配那两处传参，保留经理台修改。

## 新测试

`tests/test_issue28_preselection_hk_fallback.py` 使用真实临时池存储和 API 请求：

1. 本地 A=2，配置来源另有不同 A=1；补充目标日 10/8、价格日 10/7、
   资格日 9/30 的 HK=100，仍只保留本地 A=2。分页 limit=1 不改变完整计数，
   重复读取保持输入指纹，artifact/manifest/receipt 原字节不变。
2. 配置 HK 属于另一个目标日时拒绝补入，仍展示有效本地 A。
3. 配置 HK manifest SHA 被破坏时拒绝补入，仍展示有效本地 A。
4. 配置 HK receipt SHA 被破坏时拒绝补入，仍展示有效本地 A。

资格和行情来源均为明确标记的合成 fixture，不是 10/8 真实来源证明。

## 本轮实际执行范围

Linux Python 3.14.7：4 passed。原始输出见 `logs/route_storage_regression.log`。
采用与项目一致的 warnings-as-errors；保留项目已允许的 Starlette TestClient
弃用警告 1 条，没有更换客户端依赖来掩盖它。

冻结包缺完整应用依赖及 `domains/_preselection_parts/_namespace.py`。
本轮执行了原 app 中未改写的路由与 helper AST、原预选池 facade/parts、
真实 `PreselectionPoolStore` 写入及读回。测试支架仅提供遗漏的全局名查询
helper 与固定日期 catalog，未运行原 `create_app` 完整启动。

因此本轮状态是 **隔离路由／存储回归 PASS**；完整 API canary、Mac、重载 UI、
自然时段全部 **NOT_RUN**。工单记载的原 7 项新测试、3 项回归及 178 A / 100 HK
隔离 canary 保留为既有证据，本轮不将它们计入新增测试数。

包内附可重现的 `isolated/run_route_tests.py`、冻结引用及最小测试依赖。
`isolated/` 整体只用于测试，不能覆盖或部署到任何实际 app。

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python pool/isolated/run_route_tests.py
```

该打包版本同样实跑为 4 passed，见 `logs/packaged_route_storage_regression.log`。

## Luna Max 命令与验收

将新测试放进完整候选 app 的 `tests/`，保留原测试与源码后执行：

```bash
python -m pytest -q tests/test_preselection_source_root_20261008.py tests/test_issue28_preselection_hk_fallback.py
python -m pytest -q tests/test_preselection_pagination.py tests/test_preselection_slice.py::test_native_store_and_api_enforce_dates_statuses_limits_and_receipts
```

上述完整应用命令本轮 NOT_RUN。发布 P1 通过独立审查后，按新候选前像生成新计划；
不得重用原失败 finalplan。实际发布后另核 API 的 A=178 / HK=100、原 URL 重载、
分页与全量 Stage 输入；这不等于 HK Stage 合格，也不等于自然运行验收。
