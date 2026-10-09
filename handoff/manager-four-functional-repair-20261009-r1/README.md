# Manager 四项功能缺口：R1 最小接入修复

**交付状态：四文件代码修复完成，限定离线回归及独立审查通过。Mac 现役集成、部署、真实 owner 数据、live API/UI 和自然时段验收均未执行，20261009 真实恢复仍为 `CANNOT_CONFIRM`。**

本包基于 [固定问题包 74478a0](https://github.com/lexi2016/v4/blob/74478a0e62be215c8527ccc9a14b89b51042d014/handoff/manager-four-functional-gaps-20261009/package/README.md) 内的 R2 目标源码。冻结 R2 candidate commit 为 `a7f5d09fb19de10564925757207977aadc080cc1`，release manifest SHA 为 `f6385dd23e9fda4d2169f20d6dc68b6e1e519b2b1a35e1ceb0bfd3111a079ad5`。目标日固定为 **20261009**，公告 publication / HK master session 为 **20261008**。

## 实际改了什么

[runtime.patch](runtime.patch) 只修改下列 **4 个运行文件，57 行新增、12 行删除**；完整前后文件及 SHA 见 [source_manifest.json](source_manifest.json)。另外 16 个随包 R2 目标保持原字节，见 [UNCHANGED_R2_TARGETS.json](UNCHANGED_R2_TARGETS.json)。

| 文件 | 修改及结果 |
|---|---|
| `apps/api/v35_api/app.py` | `create_app` 接受可选 `workspace_connect_binding`。省略时在构造应用时读取既有五项环境配置，并传给该应用的原 manager service。一个实例不再随之后的进程环境变化而切换 Connect authority。 |
| `v4/manager_research/service.py` | 保存实例的 binding 副本，调用方随后修改原字典不会重定向 reader。旧式直接构造 service 并省略参数的调用保留既有环境读取兼容行为。 |
| `v4/manager_research/workspace.py` | 将这个实例的 binding 传给现有 `read_scope`，接入实际 `create_app → service → workspace → 原 V2 reader`。 |
| `v4/manager_research/connect_selection.py` | 显式 binding 是完整配置：空、缺项或非法值不会借用环境补齐；拒绝含符号链接祖先的非规范 authority root。卡片身份保留 V2 已持久化的 `available_at`，仅排除每次读取变化的 `read_at`。 |

原 V2 owner/root/code SHA、精确日期、run/manifest/receipt、source SHA、cutoff、市场边界与安全校验继续执行。全量 scope 仍保留 `read_at` 诊断。输入真正发生变化时，原 `STALE_INPUTS_CHANGED` 比较继续拒绝旧计划。

## 四项问题分别得到什么结果

| 冻结问题 | 本轮实现或验证 | 真实恢复还需要什么 |
|---|---|---|
| 公告未导入 | 使用原 capture / prepare / register / import 以及实际 R2 `create_app` 消费链，验证非空 rows、证据完整的 `READY_EMPTY`、SHA 篡改、日期/cutoff/独立身份拒绝、GET 无写入。同组 8 项在原 R2 与候选均通过，未发现需要重写公告生产代码的缺陷。 | 原 owner 的真实 10/08 capture、真实且身份不同的 Reader / Reviewer 原始输出与 SHA，以及 target=10/09 的原 import receipt。合成 fixture 不能填补这项现场缺口。 |
| HK Connect 未绑定 | 补齐实例配置传递，用原 owner 构建的合成 V2 工件通过原 reader；错误 root/SHA/date/receipt/PIT 均拒绝。 | 在应用构造前提供已核对的现有 authority root、owner root/code SHA，以及目标日 10/09 的真实 V2 工件。配置注入不会自动生产数据。 |
| 超跌缺 10/08 主表 | 原 master publisher、精确日期 snapshot reader 和 HK02 panel 数值读取已在临时根联通；旧日/次日登记不能代替 10/08。未改 master/panel producer。 | 同一 authority 下真实 10/08 master index/manifest/snapshot、HK02 panel 与成交量单位/尺度来源。离线数值工件缺 volume provenance 时仍是 `PARTIAL`，未伪称完整有效空或选股成功。 |
| 计划身份变化 | 原 US mapping owner、plan owner、保存/run/product SHA 与 GET 读回连续验证；同输入 `CURRENT`，source/authority/publication/import 变化则 `STALE`，原 POST 刷新后重新 `CURRENT`。修复观察时间进入卡片 identity 的可复现误判。 | 原 owner 在真实输入齐备后刷新并核对实际运行身份。新增 clock 缺陷已离线复现，**没有证据证明它就是现场 `5df99128… → 7c5d9f18…` 的原因**。 |

`CURRENT` 表示计划身份一致，不表示所有通道已完整。原生 close、breadth/amount、archive/master、Vibe 等其他必需输入缺口继续保留。没有新增 collector、producer、分析器或研究底板；没有修改 BUY、Stage、Vibe 8910、调度绑定或前端源文件。

## 测试结果与限制

| 检查组 | 本轮结果 | 证据 |
|---|---|---|
| 新增回归 | **57 passed**：app wiring 6、公告 8、HK reader 30、plan owner/readback 13；1 条既有 Starlette 弃用警告 | [57 项日志](evidence/new_regression_57.log)、[JUnit](evidence/new_regression_57.xml) |
| 独立复跑 | 同一 57 项 **57 passed**，不与上一行重复累加 | [独立日志](review/rerun_57.log) |
| 独立边界探针 | **10 passed**：非空 dynamic GET 跨午夜、authority 篡改、真实应用 binding 隔离、公告导入后 stale/refresh | [独立审查](review/INDEPENDENT_REVIEW.md)、[10 项日志](review/edge_probes_10.log) |
| 公告原 R2 对照 | 原 R2 与候选同一组 **8 passed**；属于上述公告用例的重复对照 | [公告报告](evidence/ANNOUNCEMENT_REVIEW.md) |
| 既有 HK 相关 55 项 | 候选 **39 passed / 16 failed**；隔离原 R2 对照也是 **39 passed / 同 16 个失败 nodeid** | [失败清单与对照](evidence/hk_report.json) |
| 全项目 pytest 门禁 | 原 R2 离线 assembly 与候选均在收集时 **exit 1**：缺少 `HK_EXPECTED_MISSING_SOURCE_SHA256` 导出；**没有全项目通过结论** | [候选错误](evidence/project_gate_collection_error.log)、[原 R2 对照](evidence/project_gate_r2_baseline.log) |
| 补丁正向、包入口复跑、回滚 | 最终包入口 **57 passed**；云端隔离源码树 **1,089 文件**反向恢复原字节；独立工具 **11 项检查通过** | [补丁与工具验证](review/DELIVERY_REVIEW.md)、[包入口收据](evidence/packaged_runner_environment.json)、[回滚收据](evidence/patch_rollback_receipt.json) |
| 既往 43 / 5 / 25、完整 174 项扩展、前端构建/浏览器 | 本轮 `NOT_RUN`，不借用旧轮成绩；既有 `READY/PARTIAL` 兼容失败未被本补丁宣称修复 | [前端范围](provenance/frontend_scope.json) |

所有业务测试使用 Linux、Python 3.14.8、FastAPI 0.143.0、Starlette 1.7.0、pytest 9.1.1、httpx 0.28.1、pandas 3.0.6、pyarrow 24.0.0。实际 `create_app` 和原 HTTP 路由在进程内 `TestClient` 下执行，输入为合成临时工件，未连到 Mac 或生产 API。完整运行版本/模块路径/SHA 由包 runner 的 receipt 输出。

## 本机隔离应用入口

先阅读 [HOST_HANDOFF.md](HOST_HANDOFF.md) 和 [ACCEPTANCE_MATRIX.md](ACCEPTANCE_MATRIX.md)。`--source-root` 应是授权源码的**隔离副本**，且 4 个 before 与 16 个 unchanged SHA 均匹配。存在差异时应合并实际源码差异，不能直接用旧 before/after 整树覆盖。

```bash
python3 tools/verify_delivery.py --source-root "$V4_FOUR_REVIEW_ROOT" --side before
git -C "$V4_FOUR_REVIEW_ROOT" apply --check "$V4_FOUR_PATCH"
git -C "$V4_FOUR_REVIEW_ROOT" apply "$V4_FOUR_PATCH"
python3 tools/verify_delivery.py --source-root "$V4_FOUR_REVIEW_ROOT" --side after
python3 tools/run_regression.py --source-root "$V4_FOUR_REVIEW_ROOT" --output-dir "$V4_FOUR_ACCEPTANCE_DIR/regression"
```

在本包根目录执行；变量必须先按 handoff 指向实际包、隔离源码和新的输出目录。runner 会复制隔离源码到输出目录下的临时执行树，放入本包四份原字节测试，记录源码身份；不写传入的源码根，不应用补丁，不调用真实 owner 或部署。公告 CLI 与 US synthetic helper 为明示的测试参考依赖，见 [tests/TEST_SUPPORT_MANIFEST.json](tests/TEST_SUPPORT_MANIFEST.json)；该 CLI 不作为本次运行补丁部署。

## 源码身份与交付边界

输入包 **66 个文件 / 51 份源码快照**已按固定 Git commit 逐字节、SHA256 和 Git blob 核验，见 [输入校验](provenance/input_retrieval_verification.json)。运行四文件的 before 均是包中精确 R2 字节。为了在云端构造真实 app，复用了同一固定 Git tree 的原始支持源码，逐文件来源见 [offline_source_assembly.json](provenance/offline_source_assembly.json)。这份依赖集合**不是完整 Mac release 的重建**，也不在补丁应用范围内。

尤其是 `infrastructure/runtime_graph/service.py` 使用固定原 API 支持文件，角色明确为 `FROZEN_API_SERVICE_OFFLINE_DEPENDENCY_NOT_MAC_RELEASE_IDENTITY`；公告测试 CLI 来自既往交付的 `aee0e5c3…` 修复参考，不能冒充本包 `bfb853fb…` 原 runner 的现役部署身份。没有把旧 assembly 前端源文件加入补丁，现有 validator restoration 必须保留。

用户报告的 9/30 独立单日成功入口，在输入包限定范围内缺少完整 receipt；本轮不据此否定该运行。10/7 publication → 10/8 公告消费证据，以及范围受限的 US attention/mapping 证据，也不被扩写为完整三通道或全市场成功。

本轮同步交付只新增独立 GitHub handoff 分支和目录，不合并主线、不部署、不启停服务、不写 Mac 业务 state。包内 `CHECKSUMS.json` 固定所有交付文件字节；自身不纳入自引用清单，`LOCAL/` 留给发布读回及本机执行收据。ZIP 内 `LOCAL/GITHUB_READBACK.json` 记录固定交付 commit 与逐文件读回结果。部署及真实验收仍按 [验收矩阵](ACCEPTANCE_MATRIX.md) 逐项记录 `NOT_RUN / CANNOT_CONFIRM`。
