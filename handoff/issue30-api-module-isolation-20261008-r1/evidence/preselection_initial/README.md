# Issue #30：预选池模块与最小恢复候选

本目录只交付预选池 consumer 与共享装配入口的代码候选、精确补丁和隔离测试。没有运行服务、真实网络 API、producer 或真实业务数据；没有 GitHub 写入。完整 R2 集成、部署、真实 API/UI、自然时段均未验收。

## 已完成的结果

在仓库旧 HK 快照中找到了与 Issue #30 晚间 R2 记录**逐字节相同**的 `app.py`，因此可以生成受精确前像约束的补丁，不需要把旧 canonical 大文件覆盖到经理版本。

| 文件 | 前像 SHA256 | 本候选后像 SHA256 |
| --- | --- | --- |
| `apps/api/v35_api/app.py` | `90a2bf6390c6c0e219aa3d9bb22bc3b3630ecb2d447df494ae69425933424ed7` | `5d344dfe902db37f81e06d1d401e9a7e20ae910d8f7647b732ae2b3ba4f019e5` |
| `apps/api/v35_api/preselection_router.py` | 集成时必须确认不存在 | `718d54a6c6aa8cde2871ce4dc41cbc1d825f199a57b605e4f5ec70d8c4fe19ae` |
| `apps/api/v35_api/preselection_service.py` | 集成时必须确认不存在 | `ecf1c410e5c4671297d2054e695abe41fd32edd44caa24b2276e8c714108500f` |

原有两 hunk 修复先应用后，其临时后像精确等于既有 `435dcedd3beb43bf4a0ccb35ff6fc033ba536a940990c36f5f23358f5492b590`。在该基础上机械抽取 HTTP 路由与服务，并增加本文单列的旧 consumer SHA 错误兼容处理。不能把最终 service 描述为仅有两 hunk 或完全机械搬移。

完整差异为 `patches/preselection_module.patch`。`patches/consumer_sha_quarantine_delta.patch` 专门供 Reviewer 查看机械拆分之后新增的 consumer 语义。`patches/preselection_two_hunk_reference.patch` 只记录既有两 hunk，不是第二条发布入口。

## 当前模块边界

| Owner | 文件与职责 | 本次处理 |
| --- | --- | --- |
| 预选池 HTTP | `preselection_router.py`；原 `/api/v3/preselection-pools`、日期选择、limit/offset/page、请求元信息 | 从 `create_app` 抽出；契约保留 |
| 预选池 consumer | `preselection_service.py`；调用既有域、严格 HK 补充、投影/分页、受约束的坏 SHA 子池隔离 | 抽出并增加限定兼容处理 |
| 预选池 domain | `domains/preselection.py` 及既有 parts；汇总、来源、日期与市场合同 | 本次未改；属于依赖验收边界 |
| 共享存储 | `PreselectionPoolStore`、`PreselectionSourceResolver`、严格 snapshot 和锁 | 本次未改；原校验、pending 与 lease 不得替换或弱化 |
| 共享 API 装配 | `app.py`；解析依赖根、已有 `_strict_date`/`_catalog`、注册各模块 | 本次只替换预选池专用 imports/helpers/inline route；注册显式传入 service 和日期依赖 |
| 经理 | 既有 `manager_research_router.py`、`manager_workbench_router.py`、`v4/manager_research/service.py`/workspace 模块 | 不属于本批写入路径；保留现有边界 |

经理已使用 `create_manager_research_router(service)` 与 `create_manager_workbench_router(state_root)`。其 service 构造、`app.state.manager_research_service` 和 router 注册均留在原共享入口。本次无第二 API 进程、公开端口或新 producer。

`evidence/PRESERVATION_PROOF.json` 证明：去除明确声明的预选池改动后，整个 app AST 相同；`create_app` 其余 54 个 statement 的源码文本逐字节相同。经理 service 构造到 app 返回的完整后缀逐字节相同，SHA256 为 `022417f603c182a870e8e64f3f7efcbad649c6a2b3a2d78825008c84d6b5b0db`。这证明代码保留，不等于实际经理业务功能已经重新运行验收。

## 两处既有业务修复

1. 向既有 `preselection(...)` 转发 `preselection_source_root=resolved_pool_source`，让接口消费已经配置的来源。
2. 只有非空 `local_pools` 才进入“保留本地池并补 HK”的分支。空列表不再把来源中有效 A 的完整汇总替换成 HK-only 投影。

精确 R2 原路由在合成 fixture 上复现 A=0、HK=100；修复后相同场景为 A=2、HK=100，分页只影响展示，全量计数和输入 fingerprint 保留。这个测试重验既有修复，不重复计作 Issue #28 的新实现。

## 新增 consumer 兼容处理及限制

直接导入完整、未改写的历史 API domain 与已有真实存储依赖后，旧 7 项测试中的四个坏 A manifest/receipt SHA 场景失败。相同历史依赖下，未拆分的旧 `435d...` 路由也产生四个相同失败。源码原因是历史 resolver 的 `read_all` 只隔离 `FileNotFoundError`，逐池 SHA `ValueError` 冒泡到 monolithic domain 后变成全局 `DATA_BLOCKED_EMPTY`。本报告不把“对已隔离占位二次读回”写成已证实原因。

既有 canonical 修复 `f209ceb037515586883dc669d830fb44afcf778b67971951bde69c5eab8b67a0` 已明确采用逐子池读取和隔离 DTO。新 service 沿这一 consumer 合同增加了严格限定的恢复路径：

- 只匹配已复现的唯一旧错误：`V3.5 independent pool receipt cannot be confirmed: preselection-pool manifest or receipt SHA mismatch`。其他域阻断原因不被重解释。
- 使用原 resolver 的精确日期 owner 与 `source_read_lease`，再在同一根的既有 import lease 下调用严格 `read_pool_snapshot`；继续核验 artifact/manifest/receipt 的 canonical 字节和 SHA。
- 每个 pool 在严格 snapshot 前检查 pending；有 pending 的池只保留隔离原因，不交给能够 reconcile 的 reader，也不改写 pending。
- SHA 坏池保留逻辑来源路径和隔离原因；通过的池记录物理根、trio 路径、三个 raw SHA 与上游 source 身份。A 行的市场/代码、显式日期和 pool 身份再次核对；HK 仍调用原严格 100 行、来源及分日期 provenance 检查。
- 必须再次观察到上述 SHA 坏池，并在投影后仍有至少一个有效 A 行，才返回部分结果。只有坏池、错请求日、未释放/漂移的 lease、未知 reader 错误均不能变成成功。
- 原 domain 的其他阻断直接保留；恢复时遇到未知校验或 owner 错误则保留原阻断并显式写出恢复被拒绝的原因。未知运行异常不被 blanket catch。

这个兼容增量只消费已有存储，不写 domain/producer 或修造来源。它不宣称能恢复任意 `CANNOT_CONFIRM`，也不以局部通过解除 HK Stage/PIT/真实来源缺口。

## 测试、历史失败与验收层级

最后实际执行：**26 passed，1 条项目已接受的 Starlette TestClient 弃用警告**。旧 Issue #28 的 11 个场景仅重验；新增测试文件中的 15 个场景包含一个既有两 hunk 契约重验，以及 14 个模块/兼容门禁场景。不能把旧 11 个测试再算本轮新成果。

保留了三类失败证据：最初纯机械拆分对历史 domain 的 12 pass/4 fail；旧未拆分 `435d...` 同依赖的四个相同失败；新增恢复路径的 RED，以及显式行日期保护补充时的两个 RED。对应文件见 `evidence/candidate_all_tests.log`、`evidence/unmodified_two_hunk_old_domain_comparison.log`、`evidence/quarantine_red.log`、`evidence/row_identity_red.log`。最终日志为 `evidence/final_scoped_tests.log`。

测试直接导入完整新 router/service 与 21 个未修改的历史支持文件，使用真实临时池存储及 FastAPI TestClient。共享 app 只执行其精确 router 注册 statement；原 R2 `create_app` 的完整依赖图没有启动。没有 `sys.modules` 替换、删去 domain import、伪造 namespace 或真实网络调用。历史支持闭包混合了已固定的 API/domain 与 canonical 存储来源，全部有独立 SHA；它不是完整 R2 运行目录。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
ISSUE30_ROUTE_MODE=candidate PYTHONPATH=after:test_support \
python -B -m pytest -q -p no:cacheprovider -W error \
  -W default::starlette.exceptions.StarletteDeprecationWarning \
  --basetemp evidence/pytest-recheck tests
```

| 验收项 | 状态 |
| --- | --- |
| 当前交付的三个源码文件及完整 patch 正反往返 | PASS，前后 SHA 精确一致 |
| 新模块 + 实际 app 注册语句 + 历史真实存储/域依赖 | 26 PASS，范围如上 |
| 经理 app 装配与所有非预选 AST/statement 字节保留 | PASS |
| 当前 R2 完整 domain/store 逐文件身份 | CANNOT_CONFIRM |
| 当前 R2 完整 create_app / 全应用测试 | NOT_RUN |
| 当前 R2 实际 A=178/HK=100 来源 canary | NOT_RUN |
| 独立 Reviewer、集成、部署、API/UI、自然时段 | 由主任务分别记录；本子任务未建立 |

## 来源身份与未取得的材料

精确 app 前像来自固定 [a0a0b88d 的 HK API 快照](https://github.com/lexi2016/v4/blob/a0a0b88dc133d14ee5763569272c174bcd7cc445/handoff/hk-close-hk-calendar-20261007/api/apps/api/v35_api/app.py)，Git blob `c602a4cd8cf8182183ae3697dea25b39a7b048fb`，342147 bytes。文件目录是历史来源；SHA 与 Issue #30 晚间 app 记载一致只能证明单文件同像。

原修复与 canonical consumer 合同来自 [4ad7cc52 固定交付](https://github.com/lexi2016/v4/tree/4ad7cc52257b49470b3004ebfee9649af43189dd/handoff/a-preselection-source-20261008)。测试历史 monolithic domain 来自 [固定 20261005 API 源码](https://github.com/lexi2016/v4/blob/a0a0b88dc133d14ee5763569272c174bcd7cc445/handoff/v4-running-source-20261005/api/domains/preselection.py)，不能用其 SHA 冒充晚间 R2 domain。

另外核查了 `b22836ef...`、`02c2acf9...`、`66339d57...`、`281f2f39...` 四个经理固定 tree。最新 [Mac completion status](https://github.com/lexi2016/v4/blob/b22836ef3f8fcc6b9218f3422a9bcd7aa61152e9/handoff/manager-workbench-mac-completion-20261008/evidence/status.json) 只给 R2 整体 manifest/inventory 的 SHA 和条目数。其 `file_map.json` 引用 `receipts/api_candidate_inventory_final.json` 的 SHA `e99ec8bc...`，该 inventory 正文不在包内，按所引路径只读请求返回 404。因此当前 R2 domain 的精确 SHA、1016 项完整依赖库存及晚间真实来源不能从这些材料证明。

`evidence/SOURCE_DOWNLOADS.json`、`SOURCE_SEARCH_EVIDENCE.json` 和 `TEST_SUPPORT_INDEX.json` 保留来源与排查范围。集成时必须在完整、当时已接受的 R2 或更新基线上核对新增文件不存在、所有依赖身份及非 delta 文件保留，再执行经理公告/日期/workspace与预选池联合回归。本候选本身不构成部署授权。

`RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false`。
