# V4 Manager R3 最终独立评审

## 结论

**REVIEWED：在下列冻结源码、交付载荷与定向合成合同范围内，没有尚未解决的、可复现的 P0/P1 缺陷。** 独立 Reviewer 没有编写或修改被评审的生产源码；本轮发现的三个 P1 问题已保留有效 RED，修复后进行了独立复验。一个交接文档的 P2 错误链接也已修正。

**真实业务验收：NOT_RUN。** 本结论不表示实际 Mac 已集成、部署、恢复输入、生成 20261008 / 20261009 真实计划、通过 live API/UI 或连续自然交易日验收。实际 owner/source、完整应用导入与 web 构建仍须按原 owner 合同继续。没有真实 owner POST、网络采集、业务 plan/state 读写、生产配置变更、服务操作或 GitHub 写入。

本报告覆盖的最终 `source_manifest.json` SHA-256 为：

`2288039fdfdc763904b943d57fb02ad16879b9fa5d7a2c4bc7e1b8b414ba4213`

共有五个 profile、32 条角色化源记录；不同 profile 是不同前像的选择，不是同一根上顺序叠加的 32 件改动。候选比较基线为 `c973cbc268c686af4492a7dfa4cef8417ca8edf4`，固定输入提交为 `b98d85c95d19780e2900dce7de9372328e67acf6`，共享父基线为 `66bb05a2e12976775ccb997191ce943bae8cc9a5`。完整身份见 [final_source_identity.json](final_source_identity.json) 和 [source_payload_identity.json](source_payload_identity.json)。

## 1. 本轮发现与关闭证据

| 编号 / 级别 | 可复现问题 | 修复与独立关闭证据 |
| --- | --- | --- |
| R3-IR-01 / P1 | 原验包器不检查文件声明的 profile 是否属于 profiles、不要求每个声明 profile 有源记录、也不要求载荷路径等于 `side/profile/logical_path`。两个变体可让已漂移的源码以 `source_checked=[]` 得到 PASS；另一变体允许被声称核验的逻辑路径与实际载荷文件名不同。 | `verifier_manifest_closure_red.log` 的三项拒绝断言在旧版本均真实失败。修复仅增加上述闭合检查与单组件 profile 名检查。原六项、独立三项及其余独立断言先得到 15 PASS，最终又纳入 33 PASS 组复验。旧验包器原字节保留于 `verifier_before_hardening.py`。 |
| R3-IR-02 / P1 | 真正 PREOPEN 调用经过继承的 `run_scheduled_preopen_plan_safe`。该 wrapper 先吞掉 TimeoutError，外层 R3 分类器看不到异常类型，最终把完成情况未知的超时报为 OWNER_FAILED；全大写 timeout 文本还会丢失其类型。 | 独立 probe 保留真实路由、dispatch、分支选择和 safe wrapper，只令原 service 方法抛出异常。普通及全大写 TimeoutError 都已真实 RED。修复在原捕获点按 `isinstance(exc, TimeoutError)` 保留 `PLAN_OWNER_EXECUTION_TIMEOUT`，最终 RPC 的 `dispatch_outcome=CANNOT_CONFIRM`。原三项异常 probe 与扩展回归在最终 86 PASS 组通过。 |
| R3-IR-03 / P1 | 同一真实 wrapper 把任意符合大写字符格式的异常消息当成稳定原因；`ValueError("SYNTHETIC_PRIVATE_UPPERCASE_DETAIL")` 的消息进入 plan/result 对外结果，绕过外层限界。 | 捕获点现在仅保留明确枚举的 24 项原 gate/readback 原因，其余异常归为稳定执行失败码；类型为 timeout 时始终优先保留超时语义。真实大写异常 probe 由 RED 转为 PASS，原合法 PARTIAL 和原 failure_reasons 列表完整保留。 |
| R3-IR-04 / P2 | HK 接续文档 S8 将未改的 `workspace_plan.py` 链到不存在的 `after/api_current/...`，该文件不属于 13 件 API 补丁。 | 链接已改为固定 b98 提交中的 Mac completion 源，独立核其 Git blob 与实际调用点 SHA `c734f3e986af81b39bf11c09d93caf7a205526c8b4df940a4beeb011f74e0ebb` 一致；没有为修链接增加运行补丁。见 `final_handoff_review.json`。 |

旧 verifier SHA 为 `53fc956f25875eac850b7dc766b9d95e95a7b8943812158d2c0da894c18fc099`，修复后为 `2ee5276989fd1b3bb523ef74b636b884a63e21d04a0d96c4602abbc0242bf234`。safe wrapper 的比较前像为 `14d168300bba42124649f56b79ae65b41359bcfa6928b59fea4a36beb2b511f5`，最终后像为 `d7b2940f1203b62d642137a6b8eecffac566d0c1bf625d514c1345c0fc1a2a34`。这些是候选比较前像；现场 API、worker 的 before 必须使用各自 profile。

异常路径原始证据是 [binding_real_owner_paths_red.log](binding_real_owner_paths_red.log)、[binding_real_owner_timeout_uppercase_red.log](binding_real_owner_timeout_uppercase_red.log)；修复后的完整命令与测试前后身份见 [binding_final_independent_receipt.json](binding_final_independent_receipt.json)。上述两个 wrapper 问题是在继承的真实调用路径上发现的合同缺口，不把原测试绕过 wrapper 的结果解释为真实路径已被验证。

## 2. Binding、API admission 与 owner 结果

最终双根合同保留顶层 `app_root/files` 对应 worker，显式 `plan_owner.app_root/files` 对应提供原 owner 的 API 根。两端使用同一原始 binding JSON 的完整 SHA；没有删去 root/enabled 来改成语义哈希。旧 same-root 方式仍严格支持，不能用缺少显式 owner 的 binding 冒充双根。

Reviewer 检查了实际 diff，并通过原路由的进程内 TestClient 验证：绑定原字节、API root、owner 身份、两份闭合 source inventory、状态根与 master 根、启用状态和窗口门禁在 owner 被调用前检查。无效门禁返回稳定、带相同日期与 binding SHA 的结构化 409。客户端仅在 schema、字段闭集、owner、日期、完整 SHA、固定 flags 和稳定 reason 都匹配时承认 `ADMISSION / OWNER_NOT_CALLED`。网络超时、其他 HTTP 错误、伪造或不完整 409、坏形状的 200 receipt 均保留 `CANNOT_CONFIRM`，不借 HTTP 状态猜测 owner 未执行。

主控另行发现并要求修正的 actual nested consumer pin 缺口也已独立复核：scanner 把**存在的** `v3_shared_data/shared_data` 纳入闭合清单；显式 API owner 必须包含 `v3_shared_data/shared_data/hk_daily_supplement.py`。原 worker 根没有这棵 API nested 树仍合法。独立测试将真实 reader 字节放入完整惰性角色 fixture，核实其实际 SHA 被 pin；在 binding JSON SHA 不变时改动 reader，scheduled/daily 两个真实 admission 入口均拒绝，owner event 为空且临时 state 没有 JSON 写入。连文件和 pin 一并删除也由原新合同测试拒绝。

canary 必须绑定真实 `owner_execution_app_root` 和该 API 根 canonical inventory SHA；旧 worker root 的 canary 或 migration 文档不能替代。历史目标日期必须使用显式 `view=dynamic` 的读回。worker 的 DISABLED 与 NOT_DUE 保持独立结果，二者不触发业务调用。

已 dispatch 后，输入不足、已知 owner 失败、超时未知、合法 owner 结果分别保留对应分类。最终测试保留真实 wrapper 路径，超时不产出伪 run/product SHA，owner readback 为 UNVERIFIED；合法 PARTIAL 的原 gap 文本和同 run attempt 仍完整读回。没有为了状态好看清空 gaps。

### 冻结的七件 R3 生产增量

| 路径 | 最终 SHA-256 |
| --- | --- |
| `apps/api/v35_api/manager_research_router.py` | `9d8d132c58e7cf1c5a5609d93261483d578268ac24c60c2fa7a6a79b87344341` |
| `infrastructure/scheduling/manager_announcement_supervisor.py` | `e9a1e6f79abf268855a88d15dc579744ec4739f3561eccc56972badd89653ffa` |
| `ops/render_manager_announcement_binding.py` | `44fba219e65a2c67bf0dc5d7d9f012e6ece757bb5a2b38a273f616dbfe7aa4db` |
| `ops/run_manager_announcement_cycle.py` | `01b93a8985bc43f8f08ae5c6d97637abc2273fb20987fb27c6a78c6fc5b59d44` |
| `v4/manager_research/plan_owner_dispatch.py` | `2b532168bfdce41080121df318cb619011b98bb76195eba39df43046a130b987` |
| `v4/manager_research/workspace_daily_channels.py` | `e5a74449f211c9e8ecfb4f886317db2263d524f0e29fa7912c9094928a5c6bab` |
| `v4/manager_research/workspace_plan_autorun.py` | `d7b2940f1203b62d642137a6b8eecffac566d0c1bf625d514c1345c0fc1a2a34` |

`git diff --name-only c973cbc` 的受版本管理生产变更恰为上面七件。HK 是另一个候选根的三件原 R1 重放。新测试文件身份另列于 `final_source_identity.json`，没有修改旧断言。

## 3. 两日产品与来源指针

daily-channel 生产改动只在 `_references`，为 +17/-5：保留原 payload/manifest/artifact/pointer 的标量路径与 SHA、source_id，并把每张 card 的直接 `source_refs` 连同 card_id/art_code 锚点投影出来。不复制正文或递归展开证据；原输入对象不变。选择、排序、原 owner 保存、时间资格和安全 flags 逻辑没有随此变更。

九项新产品测试用临时原 store/import/refresh/GET 链验证：10/8 事后保存由显式 dynamic 读回；普通 auto 仍读原合格历史 run，或保留 `HISTORY_QUALIFIED_SAVED_PLAN_MISSING`。10/9 已保存的当日产物由默认 auto 读回同日期、run、产品 SHA、input identity 与执行上下文，GET 不创建新 run。缺输入不能借其他日期回填，source capture 完成也不能伪称 daily mapping 已保存。完整合法公告/US 输入经原筛选为空可以有可追溯空结果，同时保留其他独立通道的 PARTIAL/gaps。

独立双卡 probe 核每个 native pointer 仍属于自己的 card，且正文和更深 source_refs 不进入投影。将固定前像仅加载到测试进程内时，两个原生 pointer 断言均真实失败，当前后像通过。完整说明与原始命令保留在 [first_batch_review.md](first_batch_review.md)；其第一批暂时结论已由本最终报告替代。

## 4. HK 接续、producer 缺口和测试依赖

三件 child before 与 R3 supplied `hk_child_conflict` 逐字节相同；三件 after 与原固定 R1 after 逐字节相同，见 [hk_source_identity.json](hk_source_identity.json)。最终 source payload audit 又核了一次这一来源关系。

| HK child 路径 | 最终 SHA-256 |
| --- | --- |
| `ops/macos_research_panel_daily.py` | `1963990fcde99b2681c837b8b66ea12f1ab066aba47729af5d0900073bc79ef3` |
| `ops/_macos_research_panel_daily_parts/hk_capture_gate.py` | `d07be30a40c35aee9d710fcdcc7ae66b031488cc4c5e7029824e3c76ed3fd71c` |
| `ops/ensure_hk_security_master.py` | `495ced4f0f06f170606ee576e035dafc99b540cd9fad0a28f2f2a36e5989ddb9` |
| 现存 `_namespace.py`，保留 | `45da791482883c7c371268a99056960c577f299b43a5629394b3178fbea9f8b1` |

实际 API 调用点是 `workspace_plan.py::_read_hk02_daily_supplement_witness`，实际 reader 是 nested `v3_shared_data/shared_data/hk_daily_supplement.py`，其 SHA 为 `f71d6bb8bc0d55a0205d9734562c37d249654e3e39ccc85e18dd6398aa3c3862`。独立运行的 13 项新测中，7 项经这个真实调用点读取实际 reader；其余覆盖 child 原入口、历史缺口停止、旧日 immutable 链保留与原 owner 合成发布/读回链。Fake 外部 API、惰性文件和 subprocess 替身都只用于临时输入边界；没有启动真实采集。

R3 supplied HK02 updater 仍缺 supplement producer 模块/CLI。新负例在调用 subprocess 或创建数据目录之前保留 `HK_DAILY_SUPPLEMENT_OWNER_UNAVAILABLE`。API reader 的通过不证明 updater 已恢复，单位、inherited scale、六日 finality/PIT 的真实来源仍不因此被证明。

两件 live-acquisition 测试依赖 `contracts.py` / `orchestrator.py` 的 SHA 分别为 `ea20a940814915ec1d744b7df23ea48e4287e4baa9716889a648c9210ea3b34e` / `a95fa35e17b6090f3bb196ee6bb75a456d9fb918ce64dd4cd78d7d6005d4f46d`。Reviewer 对照记录的旧源字节核验过；它们仅供合成测试导入，处于 `reference/test_dependencies`，不在任何运行 profile 中。详细 HK 范围与命令见 [hk_and_verifier_review.md](hk_and_verifier_review.md)。

## 5. 发布政策、交付来源与回放

独立政策候选 before SHA 为 `1f4afc70d7e5920b67c2b148def6b9167819664c33c92b475d919a097b9dd050`，after SHA 为 `ce74042648405a8de9aa7bd69fd0ac5cbe54e42e29db983d77d7e8519ac4cfac`。after 恰等于 before 的 POLICY 加五条 `shared[path]=["manager"]`：

- `infrastructure/_research_peripheral_store_parts/_namespace.py`
- `infrastructure/scheduling/manager_announcement_supervisor.py`
- `ops/render_manager_announcement_binding.py`
- `ops/run_manager_announcement_cycle.py`
- `v3_shared_data/shared_data/hk_daily_supplement.py`

原 modules、prefixes、其他 shared entries 和执行实现不变。独立断言检查其他模块、相邻路径、缺少 exact 声明均拒绝；旧 policy SHA 的 receipt 不会随候选政策采用而自动合法。该候选没有自动应用器，也不在业务 runtime patch 中。实际政策采用与 delta receipt 仍由原 shared/api_platform owner 在原锁内完成。

| Profile | 源记录数 | 独立核实的 before / after 来源 |
| --- | ---: | --- |
| `api_current` | 13 | R3 实际 API 角色的 12 项记录，其中 namespace 按 supplied absence 处理；另外一件 daily-channel 前像来自固定父提交 Mac completion，明确标为非本轮 live snapshot。after 是本轮七件增量与必要固定 R1/R2 after。 |
| `api_r2_increment` | 7 | 精确 `c973cbc` 已装配 R1/R2 候选前像；六件 binding/autorun 前像又与固定 R1 after 比较，product 前像与固定父源 Git blob 比较。它不是现役 API 的直接前像。 |
| `worker_current` | 5 | R3 当前 20261006 worker 独立前像；after 包含所缺累计 autorun 方法及最终异常修复，不夹入 API router/nested consumer 整棵树。 |
| `hk_child` | 3 | supplied actual child before → 原 R1 after；现存 namespace 单独 preserve。 |
| `web_cumulative` | 4 | 固定 R1 web before（包括一项须本机核 absent）→ 固定 R1/R2 after；无新增 R3 UI 代码，也不声称本轮实际 Mac 重读了这些 web before。 |

只读独立来源脚本核完每条 SHA-256、Git blob、字节数、logical/side/profile 路径、精确角色集合、patch 文件集合、原始输入及复用 after。最终五个 patch 在新临时源根逐个正向 `--check/apply`、after 核验、反向 `--check/apply`、before 核验；均 PASS，文件集合精确，反向后逐字节还原，临时根均移除。证据：[source_payload_identity.json](source_payload_identity.json)、[patch_replay.json](patch_replay.json)、[patch_replay_receipt.json](patch_replay_receipt.json)。

Issue32 三份保护身份均保持：`app.py=5d344dfe902db37f81e06d1d401e9a7e20ae910d8f7647b732ae2b3ba4f019e5`，`preselection_router.py=718d54a6c6aa8cde2871ce4dc41cbc1d825f199a57b605e4f5ec70d8c4fe19ae`，`preselection_service.py=cbed3aa4797889051eb7bebe4b8e3240b568d72b4dfb5c20f65e914d39e48044`。共享 daemon / launcher 分别保持 `19e071da0c6b6748465853c4ad86a80d6060524333e9dab21647b67adc8b49ec` / `0c577ae83b1f182dabf3b62e642a5bd5f0f8708b48e1806d8c653b691d2ec952`。原 Stage、BUY、Vibe8910、US source scheduler 和公告任务不在变更或运行补丁范围。

`HOST_HANDOFF.md` 的两段 Bash、TESTING 三段、HK 接续六段和 README 一段均仅执行 `bash -n`；renderer/验包器的文档参数与冻结源码 AST 相符。没有执行文档中的业务命令。日期、auto/dynamic、两根 canary、原 release owner、回滚与 NOT_RUN 描述和实际合同一致。文档版本 SHA 与 S8 修复核验在 [final_handoff_review.json](final_handoff_review.json)。

## 6. 独立执行结果与重现命令

环境为既有 `/workspace/scratch/a154a3323e32/test_env/bin/python`，Python 3.14.6、pytest 9.1.1、FastAPI 0.141.1、Starlette 1.6.0、httpx 0.28.1。测试输入只用临时目录；TestClient 在进程内调用原路由，没有监听或访问 8873。一项已有 TestClient deprecation warning 保留。限定原 helper/import 装配不等于完整应用的 native import closure。

| 独立执行组 | 实际结果 / exit | 原始证据 |
| --- | --- | --- |
| 最终 binding 44 新合同 + 36 原 daily dispatch/automation + 6 独立真实路径 probe | **86 PASS，exit 0** | `binding_final_independent.log`、`binding_final_independent_receipt.json`；测试前后七项 binding 源/新测试身份不变 |
| 最终 product 9 + policy 9 + verifier 6 + 独立基础 6 + closure 3 | **33 PASS，exit 0** | `final_portable_contracts.log`、`final_portable_contracts_receipt.json`；显式 `V4_R3_REVIEW_APP_ROOT` 已复验 |
| 冻结 HK 新测试 | **13 PASS，exit 0** | `hk_contracts.log`、`hk_source_identity.json` |
| 原 HK supplement 套件 | **13 PASS / 2 FAIL，exit 1** | `hk_original_contracts.log`；两项旧 screen 断言原样保留 |
| 原产品缺 archive 单例 | 当前 **1 FAIL，exit 1**；前像进程同样失败 | `current_known_failure.log`、`prechange_product_and_known_failure.log` |
| 最终角色来源审计与五组正反向回放 | **32 条记录 PASS；5 / 5 profile PASS，exit 0** | `source_payload_identity.json`、`patch_replay.json` |

分组存在历史重复执行，不把 43、15、33、86 等数相加成独立用例总数。第一组 43 PASS 和 verifier 修复后的 15 PASS 是过程记录，最终以上述冻结身份的范围结论为准。

最终 binding 的实际命令：

```bash
cd /workspace/scratch/21926b793c00/candidate
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/workspace/scratch/21926b793c00/candidate:/workspace/scratch/21926b793c00/candidate/upstreams:/workspace/scratch/21926b793c00/candidate/tests
export V4_R3_REVIEW_APP_ROOT=/workspace/scratch/21926b793c00/candidate
/workspace/scratch/a154a3323e32/test_env/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_manager_r3_binding_contract.py \
  tests/test_manager_daily_dispatch_20261008.py \
  tests/test_manager_daily_automation_20261008.py \
  ../independent_review/test_binding_real_owner_paths.py
```

最终 product / policy / verifier / portable reviewer 组实际命令：

```bash
cd /workspace/scratch/21926b793c00
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/workspace/scratch/21926b793c00/candidate:/workspace/scratch/21926b793c00/candidate/upstreams:/workspace/scratch/21926b793c00/candidate/tests:/workspace/scratch/21926b793c00/independent_review
export V4_R3_REVIEW_APP_ROOT=/workspace/scratch/21926b793c00/candidate
export V4_R3_POLICY_SOURCE=/workspace/scratch/21926b793c00/release_policy_review/after/ops/api_release_integration.py
/workspace/scratch/a154a3323e32/test_env/bin/python -m pytest -q -p no:cacheprovider \
  candidate/tests/test_manager_r3_product_contract.py \
  tests/test_manager_r3_release_policy.py tests/test_r3_delivery_verifier.py \
  independent_review/test_frozen_contracts.py \
  independent_review/test_verifier_manifest_closure.py
```

最终来源核验与临时回放实际命令，前者只适用于附带原输入与候选 Git 基线的本轮审查装配：

```bash
cd /workspace/scratch/21926b793c00
export PYTHONDONTWRITEBYTECODE=1
/workspace/scratch/a154a3323e32/test_env/bin/python independent_review/audit_source_payload.py \
  --workspace /workspace/scratch/21926b793c00 \
  --package /workspace/scratch/21926b793c00/delivery/manager-daily-r3-repair-20261009
/workspace/scratch/a154a3323e32/test_env/bin/python tools/replay_delivery.py \
  --package /workspace/scratch/21926b793c00/delivery/manager-daily-r3-repair-20261009
```

HK、基线前像进程比较及早期 verifier 命令保留于相邻两份阶段报告。完整 argv、cwd、环境和 log SHA 对应在 JSON receipts 中；日志没有重写成全绿。

## 7. 保留的失败与实际验收边界

原产品 `test_missing_original_archive_is_not_empty_connect_selection` 仍是 PARTIAL 对期望 READY；独立前后像都复现。原 HK 两项 screen 断言仍分别是 0 对期望 3、0 对期望 1；原测试、reader 和 workspace 调用点字节未改。writer 的 binding 邻接四项 `_transaction` fixture 失败及其前像复现也保留于 `evidence/binding_preexisting_confirm.log`；此四项是审阅其现成日志和未改事务边界，没有另作独立全组重跑。

Reviewer 自身装配错误同样保留：最初实际 reader inventory probe 误把不完整 candidate 当完整源码根，缺 `apps/__init__.py`，后改用原完整惰性角色 fixture 加真实 reader 字节；没有补造生产入口。异常 probe 的有效 RED 与这项装配错误分开。修复后的 86 项第一次额外预装 `r3_scoped_loader`，出现 **85 PASS / 1 FAIL**：原 monkeypatch 字符串解析找不到 `v4.manager_research` 属性。移除这次额外预装、按文档原 `-m pytest` 命令运行后 86 PASS；没有改 loader、生产实现或断言。原记录是 `binding_final_loader_attempt.log` 和其 receipt。来源脚本第一次假设父源另有 remote/ 副本而出现 FileNotFoundError，保留 `source_payload_audit_initial_error.log`；最终直接核固定候选 Git 对象与 supplied 远端树 blob，不创建缺失源文件。

已运行测试不能证明实际 HK02 producer、公告 Reader/Reviewer/import、US 04:15 owner 与当天 mapping、HK V2/master/PIT/单位来源已经恢复。没有两日真实 run/product SHA，没有实际进程加载模块证明，也没有至少两个连续适用交易日的自然 dispatch → inputs → owner → product → API → 普通页面收据。文档提供的是原 owner 接续和验收步骤；既有 gaps、缺输入未知计数和合法空结果须继续各按原合同保留。

最终状态分别为：**CODE / SOURCE / SCOPED TEST REVIEW = REVIEWED；INTEGRATED / DEPLOYED / LIVE API / LIVE UI / NATURAL BUSINESS = NOT_RUN。** 全部阶段保留 `RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false`。
