# Mac 接续：先核源，再对隔离候选应用和验收

以下是交给原主控的操作说明，**本轮没有执行其中的 Mac 写入、owner 业务任务、服务或部署动作**。本包权限范围不包含 merge、部署或启停服务。补丁验证工具只读实际目标；正反向应用测试仅在临时目录执行。

## 1. 身份核对

唯一 canonical 源码仍是 `/Users/lexi/Desktop/学习/v4_app`，用户入口 8873。经理和阶段选股共用 API/页面发布入口；不能把 manager 模块拆分理解为独立部署。Vibe 8910 保持原样。

请求包固定候选为：

`/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_THREE_CHANNEL_DEPLOY_20261009/candidate/three_channel_release_r2/app`

这不是现役确认。实际操作前由原主控记录 canonical、API、Stage、候选各自源码根、release/config manifest SHA、解释器路径/版本、运行 PID、启动入口与端口；保留未知项 CANNOT_CONFIRM。不要用本包 Linux 测试根或旧 R3/R1 快照补写实际运行身份。

保留上述冻结候选及并行工作，将已确认的完整候选复制到一个新的隔离修复根，例如：

`/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_OWNER_INPUT_INTEGRATION_20261009_R1/candidate/app`

若目标已存在，使用新独立路径。不要清理、覆盖其它未提交修改或写入任何运行中的 app root。下文变量指向该新副本。

## 2. 先用完整前像核对

| 文件 | before SHA-256 | after SHA-256 |
|---|---|---|
| `v4/manager_research/connect_selection.py` | `eaa01a13d8065b11cc8397a12edaad8b892f183158aa1f9475d29645dee09d83` | `238f608d8b130aaed6ecfeaea6a66550bf918045c82adeb9aa3ce4f7000ea291` |
| `v4/manager_research/workspace.py` | `a6225ef5583a73c066a5c31400f84e237aaceb63abefcf199cfb8c9b8af7dcdc` | `7a4875f1ab5ba46ac6c18bdaffe2c103a136734fda276fbee918163332844bb0` |

设置下面两个变量为实际解压包和新候选根。`verify_delivery.py` 会校验包内 manifest、两个目标 SHA，以及临时目录中 patch 正反向结果；`--check-r2-context` 还核对附件中非测试 R2 文件的预期身份。

```bash
MAC_REPAIR_PACKAGE="/实际解压目录/manager-owner-input-integration-20261009-r1"
MAC_REPAIR_APP="/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_OWNER_INPUT_INTEGRATION_20261009_R1/candidate/app"

python3.14 "$MAC_REPAIR_PACKAGE/tools/verify_delivery.py" \
  --source-root "$MAC_REPAIR_APP" --expect before --check-r2-context
```

任一 SHA 不同就保留该差异、查明正确 owner/版本，不能按相近内容强制套补丁。`--check-r2-context` 是附件已知范围的检查，不是完整发布闭包认证；前端 validator 的上一轮修复、完整 Stage 依赖和实际启动身份仍需独立确认。

## 3. 只向已核对的新副本应用

```bash
git -C "$MAC_REPAIR_APP" apply --check "$MAC_REPAIR_PACKAGE/runtime.patch"
git -C "$MAC_REPAIR_APP" apply "$MAC_REPAIR_PACKAGE/runtime.patch"
python3.14 "$MAC_REPAIR_PACKAGE/tools/verify_delivery.py" \
  --source-root "$MAC_REPAIR_APP" --expect after --check-r2-context
```

本 patch 不修改 API 路由、schema、安全 flags、前端、Stage、BUY 或服务配置。读取器 fingerprint 可能随真实源码合同变化而变化，旧保存产品仍应接受原 history/stale gate；不要改旧产品的 read-contract SHA、input identity、run id 或日期。需要当前产品时调用原 owner 重新生成。

包内 `tests/tests/` 含三个新增回归文件和本次用到的原测试/fixture。新增文件为：

- `test_manager_app_announcement_chain_20261009.py`
- `test_manager_hk_authority_app_wiring_20261009.py`
- `test_manager_app_plan_identity_20261009.py`

将新增文件放到新副本的 `tests/`。已存在同名文件时先比较 SHA；不要覆盖并行修改。原 fixture 应先与包内字节比较，不把整份 `tests/` 无条件覆盖进源码。依赖和运行命令见 `TESTS_AND_ENVIRONMENT.md`。完整 Mac Python 3.14 结果仍须原主控记录，不能将本包 Linux 结果补成 Mac PASS。

## 4. 原 owner 输入接续

### 公告

先核已有 exact pair：`target=20261009`、`publication=20261008`，同一 manager state/MaterialStore 的 catalog、body corpus、capture receipt、真实 Reader 原输出、真实独立 Reviewer 原输出、不同身份、run 和 SHA。

复用原 CLI 的 `prepare → register-handoff → import → readback`。缺 capture 或实际审阅时由原 owner 与原独立角色完成；本包不生成替代评审、不触发采集。不把 `announcement_review=NOT_RUN` 与已导入 analysis 消费状态混成一个门禁。

实际 CLI 字节应核 `aee0e5c31f30b296864a7ad81263fbc748b65cb9b4d443f83a756019cbc94a38` 对应的支持合同；上传的旧 reference runner `bfb853fb…` 的薄 product readback 与新四字段 receipt 不兼容。这里要求确认实际版本，不是授权用历史/测试支撑直接覆盖 Mac CLI。

### HK Connect

显式确认以下现有配置，不从 master/shared root 猜测 universe root：

| 配置名 | 原 owner 必须确认的内容 |
|---|---|
| `V4_MANAGER_UNIVERSE_ROOT` | 原目标日 20261009 V2 authority 根 |
| `V4_MANAGER_UNIVERSE_OWNER_ROOT` | 原纯合同 owner 源码根 |
| `V4_MANAGER_UNIVERSE_OWNER_SHA256` | 该根 `stage_center/hk_universe_preflight.py` 的已核 SHA |

artifact、manifest、receipt、current、capture、publication 六工件同根、同日期、同 run 链，可逐字节验证。acquired/available 时间须真实并不晚于研究 cutoff。上一完整 session capture 只作诊断，不能升格为目标资格。

### 超跌

screen root 的既有优先级为：`V4_MANAGER_SCREEN_AUTHORITY_ROOT → V4_MANAGER_SECURITY_MASTER_ROOT → create_app(shared_data_root)`。在实际选中的同一 root 核 20261008 master index entry、snapshot/manifest/receipt、精确 HK02 panel 与 60/5 session 边界。较新的 20261009 master 不能替代；`latest.json` 是索引文件名，不是日期回退授权。

成交量须另外核原 owner 可证明的全六日单位/scale。当前原 reader 仍不接受任意新增字段作为证明，缺正式合同就保留 NOT_PROVEN/pending。需要能力升级时交原主控协调，不在本补丁中放宽 strict 规则。

### 计划

原 owner 应使用实际 `create_app` 已绑定的 manager service，保留它的 archive、close、US、master、screen、universe、state 等 reader 配置。不要临时构造少参数 `ManagerResearchJobService(...)` 来代替实际 app 实例，再拿它的保存产品同完整 app 比身份。

已有 `POST /api/v4/manager/research/workspace/refresh` 会调用原刷新路径。由 Mac 原 owner 在获准执行真实任务时，以以下相同页面绑定调用：

`date=20261009&selection_date=20261009&announcement_date=20261008`

或者在原 owner 的既有进程/入口中调用同一个 service 的 `refresh_workspace_plan` 并传入上述 `workspace_date_bindings`。保持真实当前时间及原手动/补跑/回看标记；不能为了通过盘前 cutoff 把晚到的采集、导入或分析时间改成过去，也不能把手动补跑记为自然运行。相同日期不等于相同研究 cutoff；跨 cutoff 创建新 run 的现有语义本包未改变。

## 5. 实际 API/UI 回读接受条件

输入与 owner product 准备好后，通过已确认实际 8873 入口只读回读：

`GET /api/v4/manager/research/workspace?date=20261009&selection_date=20261009&announcement_date=20261008`

同时核公告 analysis 的 exact target/publication GET。需保留这些最小字段：完整 date_bindings、channel status/count_known/coverage/pending/gaps、run id、source/product/manifest/input SHA、plan_product.status/consumed、run_readback.status 与 owner attempt identity、真实读取时间、安全 flags。不要把未评估行、partial coverage 或 0 stocks 改写成 VALID_EMPTY。

期望相同保存输入为 CURRENT、同 run/product/input/owner journal 校验一致；变化输入应 STALE_INPUTS_CHANGED、不消费旧产品。一次 GET 前后不应产生新 capture/import/plan 文件。实际 UI 在同一个共享入口核对应日期、状态和安全显示，经理与阶段入口都需要原发布验收。

源码候选、独立回归、集成、部署、API/UI、自然时段分别记录。没有真实窗口证据就继续 `natural_run_verified=false`；没有完整工件或 owner 身份就保留 CANNOT_CONFIRM/PARTIAL。服务切换不属于本包已执行或已授权动作。

## 6. 隔离源码回滚

仅对仍匹配本包 after SHA、没有后续并行更改的隔离副本执行：

```bash
python3.14 "$MAC_REPAIR_PACKAGE/tools/verify_delivery.py" \
  --source-root "$MAC_REPAIR_APP" --expect after --check-r2-context
git -C "$MAC_REPAIR_APP" apply --reverse --check "$MAC_REPAIR_PACKAGE/runtime.patch"
git -C "$MAC_REPAIR_APP" apply --reverse "$MAC_REPAIR_PACKAGE/runtime.patch"
python3.14 "$MAC_REPAIR_PACKAGE/tools/verify_delivery.py" \
  --source-root "$MAC_REPAIR_APP" --expect before --check-r2-context
```

这只撤销两个源码差异，不改 manager 业务状态、不删 immutable history、不切换运行服务。真实发布后的回滚需原发布流程另行处理。
