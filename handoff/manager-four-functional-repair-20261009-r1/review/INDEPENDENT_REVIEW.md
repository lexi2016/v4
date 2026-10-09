# 四功能接入候选：独立离线审查

## 结论

**结论：限定范围内独立离线审查通过；未复现 P0/P1/P2 缺陷。** 本结论适用于下列精确源码 SHA 与离线组装环境，不构成真实 Mac 接入、部署、API/UI 或自然时段验收。

- 独立复跑指定四个文件：**57 passed，1 warning，exit 0，5.71s**。
- 独立补充实际应用边界探针：**10 passed，1 warning，exit 0，2.68s**。
- 两轮均仅出现同一 `StarletteDeprecationWarning`（TestClient 的 httpx 兼容提示）。没有失败或跳过；没有改依赖消除警告。
- 20 个 R2 patch target 的离线 Git HEAD 字节、原始包字节和 assembly SHA 全部一致；候选仅改变预期四个运行时文件。两轮执行前后及最终检查的生产源码 SHA 一致。
- `git diff --check` exit 0。审查没有改生产源码、部署、启停服务、访问市场网络、访问 Mac state 或写 GitHub。
- **全项目门禁未通过**：主控尝试的 project gate 在 `tests/test_hk_expected_missing_recovery.py` 收集时出现 `ImportError: HK_EXPECTED_MISSING_SOURCE_SHA256`，主控报告 exit 1；本审查已读取其原始日志，未重复运行或扩修。限定 67 项通过不能替代这一失败门禁。

`CURRENT` 在本报告中只表示原产品及原 owner attempt 的运行身份、SHA、日期和当前输入匹配；数据覆盖仍可为 `PARTIAL`。`READY_EMPTY` 只用于存在完整分析证据的明确零候选，不能由缺源或全零推断。

## 基线、执行身份与边界

| 项目 | 本轮可证明的值 |
|---|---|
| 冻结仓库输入 | `lexi2016/v4`，`74478a0e62be215c8527ccc9a14b89b51042d014`；由本地 assembly 的固定输入元数据及 R2 原始文件交叉检查，未进行远端写入或实时远端验证 |
| 冻结 R2 release 引用 | 包矩阵记录 `a7f5d09fb19de10564925757207977aadc080cc1`；不是本离线 Git HEAD |
| 离线组装 Git HEAD | `cbdf87c7e4c40c65cc71a93b00deaf1208a4f52b` |
| 源码根 | `/workspace/scratch/21926b793c00/four_gaps/app` |
| 实际运行环境 | Linux x86_64，Python 3.14.8，FastAPI 0.143.0，Starlette 1.7.0，pytest 9.1.1，pyarrow 24.0.0 |
| 解释器入口 | `/workspace/scratch/21926b793c00/four_gaps/test_env/bin/python` |
| 实际日志中的依赖根 | `/workspace/scratch/6168fe203da9/r3-venv314`；这不是 Mac 运行身份 |
| 临时工件 | 每轮独立 `--basetemp`；股票、日历、capture、Reader/Reviewer、relation、publication 均为有标记的离线合成输入 |
| 保留的真实实现 | create_app 私有 manager 包注入、原 reader/validator、原 owner register/import/refresh、原 store、原 HTTP routes |

assembly 本轮记录 1089 项：20 个 R2 原始目标、940 个冻结仓库测试依赖、123 个与先前 Mac baseline SHA 相同的冻结依赖、4 个附包原 owner 测试依赖、1 个固定 API service 支持依赖、1 个 native package init 支持依赖。该组装方式**不能证明完整 R2 release 已重建**；`runtime_graph/service` 的固定原 API 支持文件身份以及已交付公告 runner after-image 保持 assembly 中的区分。

## 生产差异审查

| 文件 | 审查结论 |
|---|---|
| `apps/api/v35_api/app.py:3916,5247-5278` | 新增可选 `workspace_connect_binding`，未传时把五个既有环境键在 create_app 构造期间取快照，随后传给该应用的 manager service。显式空字典仍然为空；没有新增配置来源、collector、producer 或 HTTP 请求入口。 |
| `v4/manager_research/service.py:330,354-360` | 为该实例保存 mapping 的独立浅拷贝；合同中的有效字段为不可变字符串或 Path。调用者随后更新原字典不会改变已经创建的 app。旧直接 service/read_scope 的 None 兼容保留。 |
| `v4/manager_research/workspace.py:698` | 只把该 service 的 binding 传到原 `read_scope`。原源码的 source/run/SHA、saved context、日期比较和 stale guard 未改。GET 仍重新读取原 owner 输入。 |
| `v4/manager_research/connect_selection.py:73-164,213-218` | 明确 mapping 不借用环境；坏整体类型、坏根、坏 owner pin 可解释地 fail closed；universe root 的祖先符号链接也被拒绝。原 V2 owner/source-pin、精确日期、market、acquired/available cutoff、非空规范代码检查保持。卡片仅去掉易变 `read_at`，保留持久化 `available_at`。 |

这组变更集中在实例配置传递和输入稳定性。未增加业务放行，未改变 BUY 或四个安全标志，未修改公告和 oversold 的 owner/消费者逻辑。保留 None 兼容意味着旧的直接调用方仍可按既有方式读取环境；实际 create_app 实例不会随构造后的环境变化而改绑。

### 精确前后字节

| R2 目标 | 原始 SHA-256 | 候选 SHA-256 |
|---|---|---|
| `apps/api/v35_api/app.py` | `5d344dfe902db37f81e06d1d401e9a7e20ae910d8f7647b732ae2b3ba4f019e5` | `e9888d03208124b978fb19a7147682ed65cb79f9d465d58a48191c3330f687f2` |
| `v4/manager_research/connect_selection.py` | `eaa01a13d8065b11cc8397a12edaad8b892f183158aa1f9475d29645dee09d83` | `45f33a4531e1f72120155a4cfba92cb7866d1d9c8ee9f5e00c174bb081104553` |
| `v4/manager_research/service.py` | `d7798b66cd8d1691c7b9f081380ce702c7e840b5fb137f4d72aeef56e4bef8a4` | `fead5098a4bf05bd88c41a61296e06029e3153dd6d5add9ebb101a3339f56431` |
| `v4/manager_research/workspace.py` | `a6225ef5583a73c066a5c31400f84e237aaceb63abefcf199cfb8c9b8af7dcdc` | `eb3e8481397dde084daad39c86b8d4b0cb8b152a1fb1e2cc32278c7430e10e6f` |

另 16 个 R2 patch target 保持原字节。完整 20 项核对见 `r2_target_hash_review.json`，差异原文见 `production_diff.rawlog`。

## 四项逐项判定

| 冻结问题 | 独立离线结果 | 本轮证据与限制 | 真实 owner / Mac 状态 |
|---|---|---|---|
| Announcement 未导入 | **OFFLINE_PASS** | 8 项既有新增回归独立通过：精确 target/publication、三次合成 transport、原 capture/register/import、不同 Reader/Reviewer 身份、SHA 和 available cutoff 均由原验证器检查。独立探针补全“先有计划→原合成公告导入→旧计划 STALE→原 POST 刷新→GET CURRENT”的 product/run/import receipt SHA 链。明确 NOT_SELECTED 的完整分析能产生 `READY_EMPTY`；缺输入和被篡改输出保持 `CANNOT_CONFIRM`。 | **CANNOT_CONFIRM**：没有 10/09 实际 capture/Reader/Reviewer、没有 Mac owner run。本轮不推翻用户报告的 09/30 独立入口成功。 |
| HK Connect authority 未绑定 | **OFFLINE_PASS** | 真实 create_app 读到原 V2 builder 产物和 exact-date run/SHA；两个 app 不互相改绑、调用者字典改变不生效、显式空/坏配置不回落环境；owner SHA、日期、manifest/publication、PIT、符号链接坏源均拒绝。补充覆盖启动后才出现环境绑定及六种坏配置，HTTP 200 中返回 `CANNOT_CONFIRM` 诊断，候选数量为 null。 | **CANNOT_CONFIRM**：实际 authority root、原 owner SHA、10/09 成员和 cutoff 均未在 Mac 核验。 |
| Oversold 缺精确日期 master | **OFFLINE_CONTRACT_PASS / EXPECTED_PARTIAL** | 原 master producer→index/manifest/receipt/artifact witness 和 exact-date reader 被验证；精确 10/08 panel 不取 latest 10/09；缺 entry、篡改、迟于 cutoff 均拒绝。完整数值历史的合成 panel/master 因没有已证明的成交量单位/尺度 provenance，仍为 `READY_WITH_GAPS`，daily channel `PARTIAL`，pending 1、candidate null，没有被改成 VALID_EMPTY。 | **CANNOT_CONFIRM**：真实 10/08 master、HK02 和成交量 provenance 仍需原 owner 提供。没有对筛选规则作新改动。 |
| Plan identity stale | **OFFLINE_PASS** | 原 US owner→确切 daily run/artifact→同一 manager store 原 plan owner→product/attempt SHA→GET 回读完整验证。原源变化、authority 变化、日期绑定变化与坏 product/attempt 不消费旧计划。非空卡片只移动 V2 read_at 时 CURRENT；改变持久化 available_at 时 STALE。独立真实 create_app 探针在 10/10 00:05 显式 dynamic GET 保持同一非空 plan/input/run/SHA；篡改 authority 字节后旧非空计划变 STALE、HK 变 CANNOT_CONFIRM。 | **CANNOT_CONFIRM**：真实输入补齐后仍需原 owner 重建并由实际应用 GET；本轮 CURRENT 不代表完整研究计划 READY。 |

四个安全标志在既有回归和新 HTTP 探针中均检查：`RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。GET 工件快照前后相同；独立跨午夜探针还把四个 owner refresh 方法设为禁止调用，未触发。

## 独立新增 10 项的明确范围

1. app 在环境未配置时创建，后续环境变为有效；老 app 仍未绑定，新 app 读到有效 exact-date authority。
2. 六种显式坏配置：False、字符串、owner-root 错类型、owner-SHA 错类型、NUL 根、坏 D-1 receipt-root 类型。全部没有借用有效环境，没有未处理异常，没有变 VALID_EMPTY。
3. 真实 create_app + 原 archive/master + V2 authority 得到非空股票 `HK.01234`；跨午夜只改变观察时钟，`view=dynamic` 的 GET 保留原 context 和输入身份，同一原 plan 产品持续 CURRENT，所有 GET 均只读。
4. 真实 create_app 已有非空 CURRENT 后篡改原 authority artifact 字节；GET 返回新失败诊断，旧产品不再消费，仍保留旧 run 引用供追溯。
5. 原公告 register/import 合成产物进入已存在计划的输入身份；先 STALE，再由原 HTTP POST 刷新获得新 plan，GET 验证原 import/product/run SHA 链，未新增 transport。

跨午夜探针明确使用 `view=dynamic`。默认 `auto` 进入历史视图、完整历史 reader gate、真实浏览器跨日行为本轮没有额外测试，保持 **NOT_RUN**；不能把该动态回读证据扩写成历史 UI 验收。

## 前端合同与其它门禁

本 diff 没有更改 route、response 顶层 schema、daily-channel 日期字段或安全字段；唯一卡片来源字段变化为从业务 identity 材料中移除诊断性 read_at、保留真实可用时间。read_at 仍存在于 membership 诊断和 plan run readback。本轮静态审阅未发现四个 diff 引入与既有开放 JSON 来源对象的字段冲突。

没有在本离线组装目录复写或重新运行旧前端来替代上轮固定仓库的 45 项 validator 修复。**前端完整验收：本轮 NOT_RUN**，既有修复由主控保持原提交和证据。全项目门禁由主控集中尝试，原始日志 `../evidence/project_gate.log` 显示 `tests/test_hk_expected_missing_recovery.py:14` 从 `infrastructure.preselection_pool_store` 导入 `HK_EXPECTED_MISSING_SOURCE_SHA256` 时失败：`1 warning, 1 error in 0.85s`；主控报告 exit 1。独立审查读过该日志，但没有独立执行全仓 gate，也没有以修改冻结源码补全这个缺口。门禁状态记录为 **BLOCKED_AT_COLLECTION / NOT_PASSED**。旧 HK 55 项的 candidate/baseline 39p/16f 是主控提供的历史对照，本轮不把它改写成独立通过。

## 可行动缺陷与交付建议

- **P0/P1/P2：本轮没有复现项。** 无需根据本审查扩大生产补丁。
- 将四个 runtime after-image、必要新测试和精简证据按路径/SHA 应用；本轮文件 SHA 是审查有效性的边界。应用与回滚工具尚未在本审查阶段检验，状态 **PENDING_FOLLOWUP**。
- 真实验收时仍应由既有 owner 按冻结日期提供公告 handoff、HK authority、10/08 master/panel/provenance，在实际 app 构造时绑定配置，刷新原 plan，再只读 GET 核 run/product/input SHA。证据缺失时继续保留 CANNOT_CONFIRM/PARTIAL/STALE；这些是未完成的实际验收，不能作为“离线失败”或“已实际修复”处理。
- 不打包临时测试 state 目录。精简复核文件包括本报告、总 receipt、两个执行 receipt 与 rawlog、原始 production diff、20 目标 hash 清单、静态检查日志，以及独立边界探针源码。

## 可重现命令

工作目录：`/workspace/scratch/21926b793c00/four_gaps/app`。

```sh
/workspace/scratch/21926b793c00/four_gaps/test_env/bin/python -m pytest -q -ra -p no:cacheprovider --basetemp /workspace/scratch/21926b793c00/four_gaps/independent_review/review57_rwfzkk6p tests/test_manager_four_app_wiring.py tests/test_manager_four_announcement_integration.py tests/test_manager_four_hk_readers.py tests/test_manager_four_plan_owner_readback.py
```

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/workspace/scratch/21926b793c00/four_gaps/app:/workspace/scratch/21926b793c00/four_gaps/app/tests /workspace/scratch/21926b793c00/four_gaps/test_env/bin/python -m pytest -vv -ra -p no:cacheprovider --basetemp /workspace/scratch/21926b793c00/four_gaps/independent_review/edge_probes_eo0bd4b7 /workspace/scratch/21926b793c00/four_gaps/independent_review/test_independent_edges.py
```

命令、解释器/平台版本、实际唯一 tmp 路径、时间和前后 SHA 均在对应执行 receipt 中记录；再次运行时使用新的 basetemp 名，保留本轮证据。
