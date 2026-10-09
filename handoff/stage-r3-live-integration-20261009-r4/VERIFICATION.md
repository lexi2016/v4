# R4 验证范围与证据

**冻结源码的完整交付包：作者 479/479，通过；独立复制包 479/479，通过。** 两次均为本轮 R4 新执行，零 failure/error/skip；UI 同时零 todo/cancelled。独立检查由另一检查代理在同一 Linux 环境、独立输出目录执行，不冒充 Mac 验收。

## 最终整包结果

| 套件 | 作者 | 独立复制包 | 覆盖 |
| --- | --- | --- | --- |
| API | 129/129 | 129/129 | 新读取绑定/历史 47 + 原 R3 reader 回归 82 |
| Vue UI | 70/70 | 70/70 | 当前完整 App、原交互、研究展示与冲突隔离 |
| Release core | 152/152 | 152/152 | 原回归 112 + Stage 所有权、完整差异/静态约束 40 |
| Integration | 86/86 | 86/86 | 发布候选准备 18、UI 构建 10、包完整性 18、发布/恢复 40 |
| 验收 runner | 42/42 | 42/42 | 五套件完整性、固定用例 ID、JUnit/TAP 计数与零跳过 |
| **合计** | **479/479** | **479/479** | 同一套 479 个用例的两次执行，不合并称为 958 个不同用例 |

作者运行 UTC：`2026-10-09T15:03:55.032444+00:00` 至 `15:06:31.591952+00:00`，156.56 秒。
独立运行 UTC：`2026-10-09T15:04:25.774333+00:00` 至 `15:07:13.117159+00:00`，167.34 秒。

- [作者完整 RESULTS.json](evidence/full_package_author/RESULTS.json)
- [独立完整 RESULTS.json](evidence/full_package_independent/RESULTS.json)
- 同目录保留每个进程原始 JUnit、stdout/stderr 和新生成 fixture 的明确范围回执。
- [三份最小补丁及固定前像复核](evidence/PATCH_PREIMAGE_PROBES.json)：`git apply --check`、实际应用到新前像夹具、逐文件 after SHA 均通过；此项不是实际 Mac 完整 App/ACL 验收。

两次整包执行的 `SOURCE_MAP.json` SHA 均为：

`8773920e5d09da693b42d453bc4638e0cc1358d10da8c53fb12fe115eb0e6ab9`

`TEST_EXPECTATIONS.json` SHA 均为：

`4a7e7ecb44e98eb58469e0d310e19d3dc49ad1c8d89c17a2d12152ebca488b58`

运行时交付清单为 213 文件、manifest SHA `439056ef8f1a342fcf5e04af491e61a4c52bde5bc66795101209ac08e11bfb81`。测试完成后只增加最终证据和更新交接文档、重新生成交付清单；被测源码、补丁、测试定义、SOURCE_MAP 和 TEST_EXPECTATIONS 保持原 SHA。最终包全部字节再次由 `verify_package.py` 校验。

## 已有 Mac 证据

固定来源：`137431f5de3917ff4526784351f5638e115061e5/handoff/stage-r3-mac-acceptance-20261009`。

- R3 独立源码测试 352/352 通过。
- 真实 PyTDX 研究 canary：A/HK 各 10，A 206/216，HK 695/695。
- 隔离 18873 HTTP/浏览器 24 项断言通过，console error/warning 为 0；临时进程已关闭。
- 上述是 R3 Mac 回执，不是本轮 R4 Chat 或现役 8873 的新测试。

## 本轮测试合同

`TEST_EXPECTATIONS.json` 固定五个必需套件、每一项用例身份和所有测试定义的 SHA。`SOURCE_MAP.json` 绑定这个文件的 SHA。验收 runner 要求所有 suite、JUnit/TAP 实际用例与固定清单一致，零 failure/error/skip/xfail/todo/cancelled；进程 exit 0 但跳过测试也不能通过。

API 套件由分开执行的 R4 47 项和原 R3 reader 82 项组成，保留两个原始 JUnit，再用 `r4/`、`r3/` 前缀合并，避免 conftest 和同名用例互相覆盖。Release 测试在新的 `ops/tests` 副本布局中执行，源码和测试复制前后都校验 SHA/权限，保留 112 个原回归用例。

每次完整复跑都生成新的合成研究产物，经原 SelectionStore/owner receipt writer、R4 binding、原 API 投影后，送入编译后的完整现役 App 与 panel。date/stage/两市场 run/artifact/SHA/安全字段在此链上核对。FastAPI 异常与 query wrapper、无关 UI 页面及 HTTP client、测试用 launchd/HTTP/npm/环境发现分别是显式 fixture 边界。

这不是完整 Mac API 进程启动、真实网络行情采集或真实浏览器验收。UI 使用真实 Vue compiler/setup/template/SSR；SSR 不执行 browser mount hooks。UI build 工具测试使用标注的 npm 输出夹具；全量现役 Vite 构建需执行 Mac 命令产生新的 BUILD_RECEIPT。

## 已修复的独立审查反例

- HTML 入口引用的脚本缺失：构建现在核验所有本地引用，不能只因任意一个 JS 文件存在而通过。
- 构建中 prepared source manifest 改变：现在比较前后 manifest 的 SHA 与文件身份。
- 原 selection envelope 没有 `RESEARCH_ONLY` 字段：遵守原三项 false 字段合同，同时严格要求 owner/manifest/响应 `RESEARCH_ONLY=true`；没有向历史 envelope 伪造字段。
- API reader 的 HK 研究行与 formal selected count 不同：已计算研究行仍正确保留 `PARTIAL_WITH_ROWS` 状态，单市场失败不抹掉另一市场。
- 通用 cutover plan 的经理根隔离：保留原 builder 证据，Stage 发布明确使用保持当前根的独立计划。
- 发布后 API 尚未就绪：限时等待已知候选身份与 HTTP 就绪，未知身份仍拒绝。
- 身份字段相同但 plist 其他字节变化：切换前后、HTTP 回读后都核验完整指针 SHA。
- 历史响应金融标志被改动、统一列表被清空、执行证据算法 SHA 改动、A 输入数被改为 200：四个独立反例最初可误通过；最终均拒绝并调用原恢复流程回到精确前像。历史已有的自然/执行证据保留原语义，目标研究回放不能标 NATURAL。

上述发布反例的初始和修复后结果分别见 [初始反例](evidence/independent/publication_http_probes/RESULTS.json)、[修复后反例](evidence/independent/publication_http_probes_fixed/RESULTS.json)。发布工具的 40 项还覆盖共享锁争用、所有显式 SHA 参数、bootstrap 失败、启动超时、prepared/backup/receipt 篡改、候选损坏后恢复、指针缺失和未完成回滚续跑。其 launchd 与 HTTP 边界明确模拟，原锁、guard、CAS、回执与恢复函数实际执行。事务审查见 [PUBLICATION_TRANSACTION_REVIEW.json](evidence/independent/PUBLICATION_TRANSACTION_REVIEW.json)。

初始 FAIL、修复后的 PASS、权限探测失败分别保留，不能只挑选成功输出。

## 本轮未执行项

| 项目 | 状态 |
| --- | --- |
| R4 在实际 Mac 完整源码/依赖图上的准备和构建 | `NOT_RUN_IN_CHAT` |
| R4 Mac 独立复跑、隔离 18873 HTTP/浏览器 | `NOT_RUN_IN_CHAT` |
| R4 接入/切换现役 8873 | `NOT_RUN_IN_CHAT` |
| R4 8873 API/浏览器同 run 回读 | `NOT_RUN_IN_CHAT` |
| Mac ACL、扩展属性与真实 launchd 恢复 | `NOT_RUN_IN_CHAT` |
| Linux 非 root 权限补验 | `NOT_RUN`；UID/GID demotion 与 user namespace 均在测试启动前被环境拒绝 |
| 正式 HK D1/成员资格/PIT | `CANNOT_CONFIRM` |
| 自动流程、自然时段验收 | `CANNOT_CONFIRM` / `natural_verified=false` |

本轮 Python 3.12.14、Linux、EUID 0；Vue/compiler/server-renderer 3.5.40、Node 24.19.0。Mac 运行时由命令记录实际版本，不把 Chat 版本当作 Mac 版本。

保持 `RESEARCH_ONLY=true`，其余三项金融标志为 false。
