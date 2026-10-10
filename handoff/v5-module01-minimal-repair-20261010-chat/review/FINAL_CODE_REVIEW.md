# V5 module01 独立代码终审

审查日期：2026-10-10。方法：Superpowers requesting-code-review 的独立差异审查、Critical / Important / Minor 分级，并用针对性反例核实发现。

## 身份与范围

- 需求来自 `lexi2016/v4@9cac0fffe12fda6ec06e106206e0c647b427913f:handoff/v5-chat-module01-20261010/PROMPT_FOR_CHAT.md`。
- 唯一产品目标是 `lexi2016/v4@f7cb731c384ee6890a87d16c19a5b5a621779477` 的 V5 树。V4 文件只作语义 donor。
- 审查目录是 `work/`，逐字节基线是 `baseline/`。本地 `fa98c20` 是源码拼装的本地 Git 基点，不是该远端目标 commit。
- 已读 `work/AGENTS.md`、任务 PROMPT / START_HERE、最小修复计划、exact-run / announcement / frontend 说明，随后检查实际 diff、原 owner 验证器和新增测试。
- 本 reviewer 不修改生产代码，不批准部署；记录的问题由相应实现者修正后复核。

## 最终结论

**本次终审发现的两项 Important 均已修正并复核；当前没有未关闭的 Critical / Important。所审字节满足“基于固定 V5 目标交付第一模块最小代码候选”的受限要求。** 可进入精确文件包、补丁和远端分支的交付流程。

这一结论只覆盖下面记录的代码 / 测试字节；交付打包、远端读回须由主控据实另验。它不表示 Mac、现役 API / UI、真实公告数据、完整工程或自然时段验收，也不是部署批准。

## Critical

未发现。

## Important

### I1 — POST 成功门控接受不完整的 manager 终态记录

状态：**已修正并独立复核关闭**。

- 文件 / 函数：`V5/ui/manager-workbench/source/apps/web/src/api/managerWorkspace.ts::refreshManagerWorkspace`。
- 冻结初稿在完整 DTO validator 后，仅比对 attempt 的 `state/run_id/target_trade_date/input_identity/execution_kind/owner` 和四个安全字段；没有要求原 `workspace_attempt.v1` schema、终态 SHA 标识、显式起止时间及时间顺序。
- `validateManagerWorkspace` 没有替它验证 manager attempt；`dailyChannels.ts::validatePlanRun` 只验证投影间身份关系。两者都不能补齐该缺口。
- 初稿 `managerWorkspace.module01.spec.ts` 和 panel spec 的 `savedWorkspace()` 本身缺 `schema_version`、`sha256`、`started_at`、`failure_reasons`，却被当作成功终态。错误字段因此不会阻止面板设置 `generationState=VERIFIED`。
- 对照：原 `workspace.py::validate_attempt` 验证 schema、封印、安全、kind、开始 / 结束时间；`workspace_plan_autorun.py::owner_plan_readback` 还要求 `started_at <= product.generated_at <= finished_at` 及 PARTIAL 与失败原因一致。
- 最小建议：保留后端原封印权威，在前端 POST 准入补齐原终态的身份 / 时间 / 状态关系，添加缺字段、非法时间、错误顺序、错误 schema / SHA 的负例；测试正常结果使用完整终态形状。不要把前端 SHA 格式检查描述为后端封印重算。
- 已向 root 即时报送；frontend 实现者独立核对后确认这是实质缺口。
- 最终修正要求原 schema、64hex SHA 标识、已知 kind、failure_reasons / PARTIAL 一致性、显式起止时间及 `started <= generated <= finished`；原 run / date / input / owner / safety 关系保留。注释准确区分前端序列化准入与后端封印权威。
- 15 新负例在旧 gate 上得到 15 FAIL / 12 PASS 的真实 RED；新 gate 后本 reviewer 独立执行 `npm test -- src/api/managerWorkspace.module01.spec.ts`，27 / 27 PASS，见 `logs/final-review-post-terminal-green.log`。同时核对组装树被测 API 字节等于 `work` 最终 API SHA。

### I2 — 分离的 refresh 写路由仍会让 gateway 误宣称 workspace 只读

状态：**已修正并独立复核关闭**。

- 文件 / 函数：`V5/src/v5_shadow/api_gateway.py::create_gateway.Handler.dispatch`，初稿发送响应标头的条件。
- 初稿只检查当前 workspace 路由 `methods == ['GET']`。真实前端生成路径却是独立的 `/api/v4/manager/research/workspace/refresh`，不是对 GET workspace 路径直接 POST。
- 有效配置 `GET /workspace` 加 `POST /workspace/refresh` 时，真实 gateway 返回 GET 200 + `X-V5-Workspace-Access: READ_ONLY`，同时确实能转发 POST /refresh 并返回 200。新前端因该标头关闭合法旧写入入口。
- 新 HTTP 测试只覆盖同一路径 `['GET','POST']`，因此没有抓到上述实际路由形状。
- 独立复现脚本：`notes/gateway_split_write_repro.py`。执行命令（`work/V5`）：`.venv/bin/python -B ../../notes/gateway_split_write_repro.py`。原始结果：`logs/final-review-gateway-split-red.log`。
- 复现仅使用临时 loopback 合成 owner 与真实 gateway；POST 只返回内存 JSON，未触及业务 owner。临时 server 已关闭。
- 最小建议：gateway 的 manager 只读能力推断必须同时排除其可写路由，尤其真实 `/workspace/refresh`；保留固定 V5 的真只读标头。添加实际 GET / POST 分离路由回归。
- 最终实现从全部 manager 路由计算 `manager_read_only`，任一 manager 路由允许 POST 就不宣称 READ_ONLY。原 module 自身确实只读，标头保持。
- 原独立脚本在新字节上得到 GET 200 / 无 READ_ONLY，POST /refresh 200，见 `logs/final-review-gateway-split-green.log`。主控新增的真实分离路由负例 RED 及 54 项新 / 原 gateway、module、artifact GREEN 亦已核对。

## Minor

没有另行提出代码修改要求。安装测试覆盖完整校验后的当前候选重应用、漂移拒绝；本 reviewer 另外比对了 manifest 的全部 23 项源 SHA，并确认所有已有固定 V5 baseline 文件 hash 都在原安装器允许的前像集合内。完整 before → after / reverse 的交付补丁验收由 root 的打包步骤另行提供；这些证据不等于真实 Mac 前像安装已验收。

## 已审查且保持的约束

### Exact product / same-run terminal / latest

`manager_plan.py::_assemble` 的 `plan_store(run_id=...)` 仅将本目标日期 `workspace_plans/<date>/latest.json` 读取改路到已验证的 32 位小写 hex `<run>.json`；其余来源、journal 和 SafeRoot 路径保持原实现。新 `exact_plan_readback` 继续调用原 `_read_plan` 和 `verified_plan_attempt`，再次比对返回 run、产品 SHA、input identity，不以自己的简化 validator 替代原 owner。

`latest_observation` 单列。即使 latest 缺失、损坏、被 B 推进或 B 缺同 run terminal，已完成 A 的 exact 读回不会因此失败；B 也不会仅凭 latest 指针被宣称完成。该 `VERIFIED` 仅是存储 owner 合同的验证，不能说明 B 的业务来源 / 自然资格已独立验收。

普通非历史读取先走原来源重放，再把 consumed A 绑定到 A 的 exact terminal。若返回的 latest journal 是 B，重新运行原 `build_daily_channels` 使 manager 执行引用与 A 一致；B 留在清楚标注的观察字段中。未改保存产品的原始字节。

同日 MANUAL_REFRESH 的 exact terminal 缺失时，不再按旧兼容把它宣称 consumed：保留 run / SHA 的未验证引用，使用原 `include_saved=False` 的只读新鲜预览，`workspace_plan_attempt=None`。修改的旧 CURRENT_RECOVERY 测试正是“新建产品后删除终态仍应 consumed”的被新用户合同取代的断言；不是删减当前恢复的准入规则。

显式 `HISTORICAL_AS_OF` 分支没有进入这次非历史重新绑定；原 `workspace_history` 的 exact 文件、PIT、来源 / cutoff 验证没有改。CURRENT_RECOVERY 的独立目录、真实执行时点和原 terminal 要求保留。

### 单次读取后发布

`publish_read.py` 取消第一次 `run_manager_plan` 后又隐式读第二次的模式，调用 `publish_workspace_read(... expected_run_id=...)` 一次。期望 run 验证发生在 `publish_generation` 之前；发布使用已经读到的同一 `result['payload']`。错误 expected run 不会产生 active 或 generation 文件。目标 run 检查为可选参数的公开 helper 保持原调用兼容，而 CLI 的 `--expected-run` 仍必填。

### 前端请求与日期边界

POST 的显式 selection / announcement bindings 进入 URL 和完整 `validateManagerWorkspace`；期待显式 bindings 时缺 date_bindings 会失败。成功 POST 直接消费一次，不再无条件 GET latest 替换它。

生成入口初始禁用，按钮事件也独立检查：完整当前读上下文、当前目标日 / view、历史默认只读、READ_ONLY 标头均参与准入。取消、切日、切 view 后的迟到 POST 受 sequence 和 abort 检查约束，不渲染旧结果。

传输错误 / HTTP 错误 / 超时 / 取消都保留“生成结果未知”，不把它等同 owner FAILED，也不自动重复 POST。一次未知生成后，重新 GET 不清除待核状态。当前 DTO 没有在响应丢失前提供 request 的 run 标识，所以 UI 不能自动找回未知 run；这仍需原 owner 核验，属于明确的接口边界。固定 V5 本批入口本身只读。

### Overlay manifest

两份变更 TS 的 `after_sha256` 已按最终修正重新计算；`previous_candidate_sha256` 对应固定 V5 目标内上一候选字节。两项获主控授权适配新合同的原前端测试也保留固定 baseline 的 previous hash；新增测试以 `before_sha256=null` 加入原 guarded installer。

删除 `unchanged` 中重复列出的 `dailyChannels.ts` 是正确的：同文件已在 `changes` 中列出经过 hash 校验的 V5 overlay，重复 unchanged 指向更旧字节会让合法当前候选无法重应用。删除重复项并没有移除它在 changes 中的 SHA / 前像 / 源像校验。真正 `dailyChannels.ts` 和 helper 生产字节保持不变。

## 真实合成 owner → HTTP → 完整前端 validator 的证据边界

已检查 `module01_owner_fixture.py`、announcement contract tests、`module01_export_http.py` 和 HTTP frontend spec：

- 合成 transport 提供四条公告，原 PrivateOwner capture / catalog / body persistence、register-handoff、import、原 reader 与 manager save / read 执行；不是仅手写一个工作台 DTO。
- 1 selected、1 watch、1 not selected、1 not assessed，用于证明决定数不等于入选股票数，以及缺 US / HK_CONNECT / OVERSOLD 不清空健康公告。
- exporter 用实际 module server 和 gateway HTTP GET，再将实际响应体交给原完整前端 validator；原 schema、安全、daily source / run 和日期检查实际执行，没有用简化 validator 补绿。
- exporter 在两个 GET 前后检查所列输入 / manager output / module roots 的字节，并关闭临时 server。frontend 第二项测试重放这个真实 HTTP body / headers 经过实际客户端解析路径，fetch 传输被拦截；它不是浏览器直接访问当时 Python server 的端到端测试。
- fixture request 通过已导入的 manager / materials 输入接入；没有绑定 Mac `announcement_offline_owner` 原根，也没有证明现场 `read_owner` happy path。真实 392 原件、完整体量、历史原件、业务语义分类、Mac API / 静态资源 / 内置浏览器、自然时段、完整三策略均 NOT_RUN。
- HTTP frontend spec 的 expected-run / SHA 来自明确合成 export receipt，不能替代 START_HERE 记录的 Mac run 和 SHA。

## 已核对的执行证据（本次修正前）

| 日志 | 实际范围与结果 |
| --- | --- |
| `exact_run-green-terminal-gaps.log` | 14 exact-run 定向用例通过；包括原 owner 保存 A/B、实际进程间普通读 race、缺 / 借 terminal、错误 exact SHA / 日期、latest 损坏和同日缺终态 |
| `exact_run-regression-plan.log` | 8 原 manager-plan / date gate 用例通过 |
| `exact_run-regression-recovery.log` | 紧缩同日合同之前的 16 原 CURRENT_RECOVERY 用例通过；后续旧断言失败另存，获授权改为新合同 |
| `exact_run-green-new-manual-contract.log` | 改后的同日缺 journal 预览 / 不消费用例通过 |
| `announcement-contract-final.log` | 9 个明确合成原 owner / 源码、材料、正文、receipt、handoff、日期验证通过 |
| `publish-read-green.log` | 2 用例通过：单读后真实 B 保存不改变发布 A；错误期望 run 不发布 |
| `http-readonly-green.log` | 初稿 5 用例通过，但没有覆盖 I2 的独立 refresh 路径 |
| `frontend-green-01.log` | 初稿 26 用例通过；I1 证明初稿成功 fixture 的终态形状不完整，不能以此排除该缺陷 |
| `http-full-frontend-validator-green.log` | 3 个真实合成 HTTP DTO / 完整 validator 用例通过 |
| `ui-overlay-green.log` | 4 个原 installer 定向用例通过 |
| `frontend-full-suite-complete.log` | **9 files failed / 31 passed；23 tests failed / 442 passed**，原日志保留。缺真实原件及旧合同差异正由主控分类，不能称完整工程通过 |
| `frontend-typecheck-complete.log` / `frontend-product-typecheck.log` | 当时组装树标准类型检查及原产品配置类型检查退出 0；最终修正后需记录新结果 |
| `frontend-build.log` | 当时原 Vite build 退出 0；最终修正后需记录新结果 |
| `final-review-gateway-split-red.log` | 本 reviewer 独立运行的 I2 反例，确认 GET 错发 READ_ONLY 且独立 refresh POST 200 |

解释器为项目原锁依赖的 Python 3.14.6（`work/V5/.venv/bin/python`）；测试使用 unittest，没有把 pytest 不存在的原失败涂掉。审查未重复执行完整工程 suite。本 reviewer 额外执行的 `git diff --check` 当时通过。

## 最终修正的复核证据

| 日志 / 检查 | 实际结果 |
| --- | --- |
| `frontend-terminal-envelope-red-complete.log` | 15 项新负例在初稿 gate 上 FAIL；原有 12 项 PASS。是行为 RED，不是缺依赖错误 |
| `final-review-post-terminal-green.log` | reviewer 独立执行完整 module01 API spec：27 / 27 PASS；所测 API SHA 与 work 相同 |
| `frontend-final-affected-suite.log` | 五个受影响前端文件合计 **85 PASS / 2 FAIL**；两项是缺原手动观察绑定文件、缺原 Eastmoney workspace 文件。不能称五文件 suite 全绿 |
| `frontend-final-typecheck.log` | 最终前端标准 `npm run typecheck` 退出 0 |
| `http-readonly-review-red.log` | 新分离 refresh 路由负例在初稿 gateway 上失败，原始日志保留 |
| `http-readonly-review-green.log` | 新 capability 6 项与原 gateway / module / artifact 合计 54 / 54 PASS |
| `final-review-gateway-split-green.log` | reviewer 独立复现 GET / refresh 分离路由：两个 200，GET 不再错误标只读 |
| `ui-overlay-final.log` | 最终 manifest 下原安装器 4 / 4 PASS |
| manifest 逐项 hash 核对 | 23 个 after SHA 全部等于源文件；全部存在的 baseline 文件均在对应 before / after / previous 允许集内 |
| `python-affected-final.log` | 原受影响入口记录 `Ran 222 tests; FAILED(errors=6, skipped=6)`。其中一个 setup 需要 Mac 请求原件，六个原 skip 需要固定原 fixture，五个 error 来自本地缺固定 archive manifest 依赖；保留原失败日志 |
| `python-archive-dependency-green.log` | 从固定远端目标补齐原依赖 blob、保持原源码后，archive 定向 8 / 8 PASS。并未重跑 / 宣称 222 全部通过 |

两项旧前端合成测试仅调整了与本次新合同冲突的预期：先显式 dynamic 后生成，提供完整 POST 终态，成功路径仅 GET → POST。没有为缺失的真实 fixture 构造替身或删掉测试。

### 审查时的最终生产字节

| 路径（相对 work） | SHA256 |
| --- | --- |
| `V5/src/v5_shadow/manager_plan.py` | `c9a95dabbdacd6a0028974132ac80a6836cd7801910dd945575a0cfcd8622e81` |
| `V5/src/v5_shadow/module_api.py` | `9a0fc23a18b7499961fa14d57fb097dc293f64f27c6f87b5bc0354921784e510` |
| `V5/src/v5_shadow/api_gateway.py` | `21f90aed9fb73d18874d3ec41a153c1a6dcab3189e5ee3a8c2afa4f3f8baa5ee` |
| `V5/tools/cloud_preview/publish_read.py` | `0035098a54ade400239a88f751bb53d8cb94b174d6ec5ce09023a6e4524a7020` |
| `V5/ui/manager-workbench/source/apps/web/src/api/managerWorkspace.ts` | `478611369d9ee2e82874810def1aaf6618da7fbd337d4709199cc872f5a9c0b8` |
| `V5/ui/manager-workbench/source/apps/web/src/manager-selection/catalystObservationPanel.ts` | `c7de6cfdaa38f7721d20d00ddbf9eb35a729c7eadc6b17058c6dbf744ddabb74` |
| `V5/ui/manager-workbench/overlay-manifest.json` | `b1d109a0c7342bd98053f8cc508d95645d69e3a680b3771d980f8f3a5799eab8` |

后续若这些字节改变，应针对改变再复核。真实 392 原件、现场安装 / API / 静态资源 / 内置浏览器 / 自然运行仍为 NOT_RUN；当前运行身份与 Mac 现场没有混同。
