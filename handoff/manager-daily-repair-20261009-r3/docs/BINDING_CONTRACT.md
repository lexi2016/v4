# R3 经理计划：双根绑定与 owner canary 接续合同

本说明针对固定输入 `lexi2016/v4@b98d85c95d19780e2900dce7de9372328e67acf6` 的 R1/R2 累计候选及 R3 增量。目标是在既有 scheduler、worker 和 API owner 之间传递**同一份绑定原始字节的 SHA256**，同时分别验证实际 worker 根和实际 API 根。计划仍由 `ManagerResearchJobService.refresh_workspace_plan` 创建；没有新增 scheduler、producer 或产品存储 owner。

当前 **INTEGRATED / DEPLOYED / API / UI / NATURAL 均为 `NOT_RUN`**。本轮代码和合成测试不代表 Mac 已集成、真实 owner 已执行或自然任务已运行。五项共享路径须由原 owner 完成登记并关闭原发布门，详见 [MAC_INTEGRATION_CONTRACT.md](MAC_INTEGRATION_CONTRACT.md)。本文的 JSON 和 CLI 示例全部是禁用的占位模板，不能投入 binding 环境、LaunchAgent 或真实 API，也不构成真实 canary。

## 1. 两个执行根、一份原始 binding

| 身份或字段 | 必须对应的对象 | 实际校验入口 |
|---|---|---|
| 顶层 `app_root`、`files` | 现有 announcement worker 的实际源根与完整原 inventory | `validate_binding(..., expected_app=worker_root)` |
| `plan_owner_binding.app_root`、`files` | 最终累计 API 候选的实际源根与 owner inventory | `validate_plan_owner_binding(..., expected_app=APP_ROOT)` |
| API `APP_ROOT` | 正在执行 `plan_owner_dispatch.py` 的源码位置推导出的根 | 由程序自身确定；不能用 binding 中自报的值替换 |
| `manager_state_root` | 注入 owner 的 `service.store.root` | 两个 execute 入口均核实 |
| `security_master_root` | 注入 owner 的 `_workspace_security_master_root` | 两个 execute 入口均核实 |
| 请求 `binding_sha256` | 客户端读到的整份 binding 原始字节 SHA256 | API 对配置路径的原始字节重新计算并精确比较 |

API owner 根必须是**最终 R1/R2 累计后像、必要共享依赖和 R3 增量完成后的候选根**。不能继续指向旧 R1 API 根，也不能把当前 worker 的旧 owner 实现当作最终 API 实现。本次双根接入使用两个不同且互不为祖先或后代的源根；两者都应与业务 state/master 根分离。不要把 API 放到 worker 根的子目录，或把 worker 放到 API 根的子目录。旧单根 binding 的验证方式另见第 8 节。

worker 和 API 可以使用不同的 binding 文件路径，但文件内容必须逐字节相同。API 原配置项仍为 `V4_MANAGER_PLAN_OWNER_BINDING_PATH`。复制后重新格式化 JSON、补换行、修改 `enabled`、替换任一 root 或 canary 路径，都会改变请求所用的 raw SHA，必须重新形成同一完整合同；不能只对齐某个 SHA 字符串。

两个既有 API 入口 `/workspace/scheduled-cycle` 和 `/workspace/daily-cycle` 共用 `_admit_owner_binding`：有界读取原始 binding、比对 SHA、校验两个闭包及真实 API 根、核 enabled/daily enabled、核注入 state/master、核日期。静态 admission 被拒绝时不会调用 plan owner，也不会写 dispatch 或计划存储。后续运行时锁、退避及过窗回执属于独立的执行阶段。

源码依据：[manager_announcement_supervisor.py](../after/api/infrastructure/scheduling/manager_announcement_supervisor.py) 的 `validate_binding`、`validate_plan_owner_binding`；[plan_owner_dispatch.py](../after/api/v4/manager_research/plan_owner_dispatch.py) 的 `_admit_owner_binding`、两个 `execute_bound_*` 入口。

## 2. 闭合 inventory 的范围和预算

`files` 是完整的相对路径到文件原始字节 SHA256 的映射。验证重新枚举闭包并比较整个映射；遗漏、多报、增加文件、修改已钉住文件都不能通过。只列本次修改文件不够。

### 原 worker 闭包

`binding_inventory` 保留 `REQUIRED_FILES` 全部必需项，包括 cycle、announcement 入口、router、supervisor、owned I/O、calendar、manager service/workspace/store、原 upstream security master 和 `uv.lock`，并枚举下列根中的所有 `.py`、`.json`：

| 根目录 | 覆盖范围 |
|---|---|
| `v4/manager_research` | 原经理 owner、dispatch 和 workspace 依赖 |
| `infrastructure` | 原基础设施与存储、调度依赖 |
| `contracts` | 日历及合同 |
| `domains` | 原 domain 依赖 |
| `stage_center` | 原 stage 依赖 |
| `upstreams/v3_shared_data/shared_data` | 原 worker upstream 依赖 |

遍历跳过 `__pycache__`、`.pytest_cache`、`tests` 目录；不跟随源目录 symlink，文件读取沿用 `SafeRoot` 的 no-follow I/O。根路径须为精确绝对路径，不能含 `..` 或经 symlink 指向别处。

### API owner 闭包

`plan_owner_inventory` 包含以上完整原 inventory，额外枚举实际 API 消费的 **`v3_shared_data` 整个目录**中的 `.py`、`.json`，并强制钉住以下入口：

| 额外必需路径 | 原因 |
|---|---|
| `apps/api/v35_api/app.py` | 实际 API 服务注入入口；保持 Issue32 原 SHA |
| `apps/api/v35_api/manager_workbench_router.py` | 原 workspace 页面/owner 接入 |
| `apps/api/v35_api/preselection_router.py` | Issue32 并行接入保护文件 |
| `apps/api/v35_api/preselection_service.py` | Issue32 并行服务保护文件 |
| `v3_shared_data/shared_data/hk_daily_supplement.py` | 实际 API HK consumer，不能只钉住 upstream 副本 |

每次 worker inventory 或 API inventory 的上限均为 **4096 文件、单文件 8 MiB、累计 64 MiB**。API 额外入口和额外目录与原 inventory 共用该次累计预算，不拥有另一份 64 MiB 配额。API 读取 binding 上限 1 MiB；canary 本体上限 1 MiB；每份 HTTP 证据回执和 response body 各有 2 MiB 上限；RPC response 上限 256 KiB。缺少目录或原依赖应按接入失败处理，不创建桩模块补齐。

API 的 `service.py`、`workspace.py` 等内容可以与旧 worker 不同。新合同验证 API **实际执行闭包**；worker 仍须完整保留并验证自己的原 inventory。只应用 worker 清单中具有准确 before 的增量，不能把未提供 before 的 owner 整树覆盖到 worker 来制造“源迁移一致”。源码依据：上述 supervisor 的 `REQUIRED_FILES`、`PLAN_OWNER_ENTRY_FILES`、`binding_inventory`、`plan_owner_inventory`。

## 3. 三种摘要不要混用

| 摘要 | 输入 | 用途 |
|---|---|---|
| `owner_binding_identity_sha256` | 仅 `plan_owner_binding` 对象的规范 JSON UTF-8 字节 | 证明手动 owner canary 对应选定 API 源闭包 |
| `plan_activation_receipt.sha256` | canary 文件原始字节 | 钉住实际 canary 及其证据引用 |
| 请求及响应 `binding_sha256` | 最终整份 binding 文件原始字节 | 证明 worker/API 使用同一 binding |

owner identity 对象必须恰好具有 `schema_version`、`owner`、`app_root`、`files` 四个键；schema 为 `v4.manager_research.plan_owner_identity.v1`，owner 为 `ManagerResearchJobService.refresh_workspace_plan`。未知字段会被拒绝。

`owner_binding_identity_sha256` 的规范算法固定如下。键排序递归适用，字符串不转成 ASCII 转义，分隔符不含空格，编码为 UTF-8，不附 BOM 或末尾换行，结果为小写十六进制 SHA256。源码函数为 `plan_owner_identity_sha256`。

```python
# 算法说明；identity 必须来自最终实际 API 根的完整、已审查 inventory。
# 此片段不生成 canary，不写文件，不调用 owner，也不能启用 binding。
import hashlib
import json

def owner_identity_digest(identity):
    canonical = json.dumps(
        identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
```

该摘要不包含外层 binding、canary 路径或 canary SHA，因此没有循环依赖。顺序是：固定 API 闭包 → owner identity 摘要 → 真实 owner canary → canary 原始 SHA → 完整 binding → binding 原始 SHA。API 根或任一闭包字节变化后，必须重新取得与新身份对应的真实证据；不能给旧回执补上新摘要冒充新执行。

## 4. 禁用的 binding 结构模板

下例仅说明字段位置。路径不存在、摘要不是合法 SHA、inventory 不完整、计划配置禁用、canary 未提供，因此**不是可验证 binding**。不得替换单个 `enabled` 值后使用，也不得把模板放入生产配置路径。

```json
{
  "schema_version": "v4.manager_research.announcement_binding.v1",
  "enabled": false,
  "policy_status": "PROPOSAL_ONLY",
  "policy": "BALANCED_V1",
  "research_only": true,
  "production_allowed": false,
  "buy_gate_updated": false,
  "orders_sent": false,
  "app_root": "/__R3_DISABLED_TEMPLATE__/worker/app",
  "manager_state_root": "/__R3_DISABLED_TEMPLATE__/manager-state",
  "security_master_root": "/__R3_DISABLED_TEMPLATE__/security-master",
  "python": "/__R3_DISABLED_TEMPLATE__/venv/bin/python3.14",
  "python_resolved": "/__R3_DISABLED_TEMPLATE__/runtime/python3.14",
  "python_sha256": "PLACEHOLDER_NOT_A_SHA256",
  "priority_codes": [],
  "files": {
    "ops/run_manager_announcement_cycle.py": "PLACEHOLDER_FULL_WORKER_INVENTORY_REQUIRED"
  },
  "plan_owner_binding": {
    "schema_version": "v4.manager_research.plan_owner_identity.v1",
    "owner": "ManagerResearchJobService.refresh_workspace_plan",
    "app_root": "/__R3_DISABLED_TEMPLATE__/final-cumulative-api/app",
    "files": {
      "apps/api/v35_api/app.py": "PLACEHOLDER_FULL_API_INVENTORY_REQUIRED"
    }
  },
  "plan_material_refresh_only": true,
  "announcement_collection_enabled": false,
  "preopen_plan": {"enabled": false, "lead_seconds": 180, "status": "PROPOSAL_ONLY"},
  "morning_plan": {"enabled": false, "interval_seconds": 300, "status": "PROPOSAL_ONLY"},
  "plan_material_refresh": {
    "enabled": false,
    "start_local": "16:00",
    "end_local": "23:00",
    "max_attempts_per_target_date": 3,
    "retry_backoff_seconds": 600,
    "status": "PROPOSAL_ONLY"
  },
  "daily_automation": {
    "enabled": false,
    "same_day_catchup_slots_local": ["10:00", "12:30", "15:45", "18:30", "22:30"],
    "us_mapping_budget_seconds": 5,
    "max_attempts_per_target_date": 5,
    "status": "PROPOSAL_ONLY"
  },
  "plan_activation_receipt": {
    "path": "/__R3_DISABLED_TEMPLATE__/NO_REAL_CANARY.json",
    "sha256": "PLACEHOLDER_NOT_A_SHA256"
  }
}
```

## 5. 新合同的真实 Mac owner canary

新 `plan_owner_binding` 存在时，canary 必须包含正确的 `owner_binding_identity_sha256`，且 `owner_execution_app_root` 必须等于该 API 根。缺失、错误摘要均拒绝；**不接收 `source_migration_receipt`**。顶层 `app_root` 和 `candidate_binding_app_root` 仍指 worker，以兼容既有 scheduler 对 worker 身份的读取。worker 闭包另行完整验证，无需迁移或统一两个根里的 owner 源码。

真实 canary 仍使用 `manager_daily_chain.plan_refresh_owner_evidence.v2`，并须满足原有 `PASS_OWNER_READBACK_EVIDENCE_FOR_PLAN_BINDING` 状态、manual owner、精确日期/run/product/input identity、同源持久化回读、HTTP 和安全字段。真实 `owner_attempt_state` 可以是 `SUCCEEDED` 或合法 `PARTIAL`；任一成功身份字段都不能由模板生成。

对 `HISTORICAL_MANUAL_REFRESH_WITH_HTTP_READBACK`，目标必须是香港当前日期之前、已知日历中的合法港股交易日。新双根合同的请求证据要求如下，保持原历史资格规则：

| 证据 | 请求要求 |
|---|---|
| `refresh` | `POST http://127.0.0.1:8873/api/v4/manager/research/workspace/refresh?date=YYYYMMDD` |
| `readback` | `GET http://127.0.0.1:8873/api/v4/manager/research/workspace?date=YYYYMMDD&view=dynamic` |

新历史 GET 接受 `date`、`view` 两个参数互换顺序，但每个只能出现一次，值必须精确，不能加入未知参数、空值、fragment、控制字符、其他 origin/port/path。历史 GET 缺少 `view=dynamic` 或使用 `auto` 会拒绝。下一交易日 scope 仍沿用原 exact URL 规则；不得把历史 canary 改名为下一交易日 scope 来规避实际回读语义。

每份 HTTP 证据引用须具有文件 `path` 与原始 `sha256`；回执中包含 `http_status=200`、`content_type=application/json`、请求 method/URL、响应文件 path/SHA/bytes 和解析后的 readback。验证会逐层核对证据 SHA、响应实际长度与 SHA、response body 与 readback 一致性，再核刷新与 GET 的产品日期/run/SHA、原 owner、持久化结果和安全字段。单独 HTTP 200 不足以成立。

下例是**禁用的教学封套**，不是可传给验证器的 canary 文件。`enabled` 属于教学封套；canary schema 本身没有用于替代 binding gate 的 `enabled` 开关。`TEMPLATE_ONLY_NOT_OWNER_EVIDENCE`、null run 及非法摘要确保该示例不能充当真实证据。

```json
{
  "enabled": false,
  "template_only": true,
  "canary_shape": {
    "schema_version": "manager_daily_chain.plan_refresh_owner_evidence.v2",
    "status": "TEMPLATE_ONLY_NOT_OWNER_EVIDENCE",
    "scope": "HISTORICAL_MANUAL_REFRESH_WITH_HTTP_READBACK",
    "app_root": "/__R3_DISABLED_TEMPLATE__/worker/app",
    "candidate_binding_app_root": "/__R3_DISABLED_TEMPLATE__/worker/app",
    "owner_execution_app_root": "/__R3_DISABLED_TEMPLATE__/final-cumulative-api/app",
    "owner_binding_identity_sha256": "PLACEHOLDER_NOT_A_SHA256",
    "manager_state_root": "/__R3_DISABLED_TEMPLATE__/manager-state",
    "policy_status": "PROPOSAL_ONLY",
    "plan_material_refresh_only": true,
    "execution_mode": "HISTORICAL_MANUAL_REFRESH_OWNER_HTTP_READBACK",
    "hook_executed": false,
    "announcement_collection_enabled": false,
    "announcement_network_requests": 0,
    "research_only": true,
    "production_allowed": false,
    "buy_gate_updated": false,
    "orders_sent": false,
    "target_trade_date": "PLACEHOLDER_HK_SESSION_DATE",
    "owner": "ManagerResearchJobService.refresh_workspace_plan",
    "execution_kind": "MANUAL_REFRESH",
    "owner_attempt_state": "NOT_RUN",
    "formal_recommendation_count": 0,
    "run_id": null,
    "product_sha256": "PLACEHOLDER_NOT_A_SHA256",
    "input_identity": "PLACEHOLDER_NOT_A_SHA256",
    "owner_evidence": {
      "refresh": {"path": "/__R3_DISABLED_TEMPLATE__/NO_POST_RECEIPT.json", "sha256": "PLACEHOLDER_NOT_A_SHA256"},
      "readback": {"path": "/__R3_DISABLED_TEMPLATE__/NO_GET_RECEIPT.json", "sha256": "PLACEHOLDER_NOT_A_SHA256"}
    }
  }
}
```

10/8 的事后手动计划使用显式 `view=dynamic`；这不使历史 `auto` 取得盘前资格。10/9 当日自动回读是否成立，应根据同日实际保存的 run/SHA/input identity 验收。日期/输入边界见 [INPUT_AND_DATE_CONTRACT.md](INPUT_AND_DATE_CONTRACT.md)。源码依据：supervisor 的 `_validate_plan_canary`、`_historical_owner_readback_url` 和 `_validate_historical_plan_canary_target`。

## 6. 实际 renderer CLI 与生成顺序

现有入口是 [ops/render_manager_announcement_binding.py](../after/api/ops/render_manager_announcement_binding.py)，可作为 `-m ops.render_manager_announcement_binding` 调用。参数名以代码为准：

| 参数 | 当前语义 |
|---|---|
| `--app-root`、`--manager-state-root`、`--security-master-root` | 必填，worker 与原业务依赖根 |
| `--python`、`--output` | 必填，绑定解释器调用路径与输出文件 |
| `--plan-owner-app-root` | 新增可选项，最终累计 API 根；生成四字段 owner identity |
| `--enabled` | 默认为 false；只有显式给出才渲染 enabled 文件 |
| `--plan-material-refresh-only` | 使用原计划 RPC 模式、关闭 announcement collection；当前 CLI 要求同时显式 enabled 和有效 plan canary |
| `--plan-activation-receipt` | plan-only 模式的真实 owner canary 文件 |
| `--activation-receipt` | 原 announcement 模式证据；不能用来代替 plan canary |
| `--daily-automation` | 原 daily 模式；要求 plan-only，使用原固定 catch-up slots/预算 |
| `--policy` | `BALANCED_V1` 或 `LOW_LOAD_V1`，默认前者 |
| `--priority-code` | 可重复的原优先代码参数 |
| `--preopen-lead-seconds` | 原盘前提前量，默认 180 秒，验证范围 1–300 |

没有 `--dry-run`、`--disabled` 或 `--owner-root` 参数。**当前 renderer 不支持生成通过验证的 disabled plan-only binding**：省略 `--enabled` 而传 `--plan-material-refresh-only` 会先报 `PLAN_MATERIAL_REFRESH_ONLY_REQUIRES_ENABLED_CANARY`。本文不修改该旧门，也不把禁用模板说成 renderer 的有效输出。

以下命令只展示实际参数组合；所有路径都是不可执行的 placeholder，且故意没有 `--enabled`。即使把路径替换为实际路径，当前参数组合仍会被上述门拒绝，不能用于安装或激活：

```sh
/__R3_DISABLED_TEMPLATE__/venv/bin/python3.14 -m ops.render_manager_announcement_binding \
  --app-root /__R3_DISABLED_TEMPLATE__/worker/app \
  --plan-owner-app-root /__R3_DISABLED_TEMPLATE__/final-cumulative-api/app \
  --manager-state-root /__R3_DISABLED_TEMPLATE__/manager-state \
  --security-master-root /__R3_DISABLED_TEMPLATE__/security-master \
  --python /__R3_DISABLED_TEMPLATE__/venv/bin/python3.14 \
  --output /__R3_DISABLED_TEMPLATE__/DO_NOT_INSTALL.binding.json \
  --plan-material-refresh-only \
  --daily-automation \
  --plan-activation-receipt /__R3_DISABLED_TEMPLATE__/NO_REAL_CANARY.json
```

原 owner 后续接续的顺序如下；本轮未执行其中的真实业务或部署步骤：

1. 按 Mac 接续合同核当前实际根、所有 before/after/mode、原共享入口和五项 ownership；保护 Issue32 三个文件的原 SHA。门未关闭时保持候选集成阻断。
2. 建立最终累计 API 隔离候选及保留全部原依赖的 worker 候选。二者源根不得嵌套。实际需要执行 canary 的 API 进程必须由原 owner 核实确实加载该最终 API 根，不能只修改回执中的根字符串。
3. 对最终 API 调用 `plan_owner_inventory` 取得完整 `files`，组成四字段 identity，按第 3 节算法计算摘要；独立核 worker inventory、解释器调用路径/解析路径/实际字节 SHA、state/master。
4. 在另行授权的真实 Mac owner 验收中，通过原 manual refresh 取得真实日期、run、产物、输入和 attempt 身份，并完成正确 view 的 HTTP GET 与原存储回读。输入未就绪时保存诊断，不能产出通过 canary。该步骤不是 scheduler 自然运行。
5. 保存真实 HTTP body 与回执，固定各层 bytes/SHA，并由真实执行证据生成带 owner identity 摘要的 canary；不使用 `source_migration_receipt`。按最终实际 canary 原始字节重新计算其 SHA。
6. 在原 owner 已批准该具体候选后，使用上表真实参数和有效 canary 渲染待审 binding；需要 enabled 文件时由该 owner 显式决定 `--enabled`。renderer 只写指定输出，不安装 LaunchAgent、不改变服务、不触发 owner。检查输出的 worker/API 两个闭包仍对应冻结内容，再固定最终 binding 的 raw SHA。
7. 使用原 worker 验证入口与 API-role 验证入口分别核同份 binding。若将同一字节文件复制到不同配置路径，重新计算两端 raw SHA；任一根、源码、canary、解释器或配置变化都重新准备合同。
8. 由原唯一发布/调度 owner 完成已获准的后续接入与分层验收。真实自然运行须另取原 scheduler/worker 的触发记录、原 API dispatch ledger 和同目标/同 binding/run/product/attempt 回读，不能把第 4 步手动 canary 回填成自然运行。

## 7. 六种 dispatch 结果与重试合同

结果分类位于顶层 `dispatch_outcome`；有 parent trigger 回执时同时回显于 `parent_trigger_receipt.dispatch_outcome`。原 `status` 仍保留 `SUCCEEDED`、`PARTIAL`、`FAILED` 的既有外层语义，不能单独用它判断 owner 是否执行或是否生成计划。

| `dispatch_outcome` | 可确认的事实 | 产物与后续处理 |
|---|---|---|
| `NOT_TRIGGERED` | 没有进入合法触发，或最终调用前已过窗且 owner 未调用 | 保留未触发/过窗原因；不能解释成 owner 失败或补造计划 |
| `GATE_REJECTED` | 绑定、角色、enabled、重试预算/退避等明确门禁拒绝 | 静态 admission 不调用 owner、不写计划；已有执行账本的拒绝可引用 prior receipt |
| `INPUT_NOT_READY` | owner 输入诊断为 `CANNOT_CONFIRM` 等，无可验证产物 | 保留具体 `reason`/`failure_reasons`，不造成功 run、product 或 owner attempt |
| `OWNER_FAILED` | 原 owner 执行路径返回失败或抛出可确认失败 | 保留原失败及有限重试合同，不写成功计划 |
| `OWNER_RESULT` | 日期、原 owner、执行类型、run/product/input/attempt 身份通过回读 | 可以是成功或有真实产物的合法 `PARTIAL`；不等同于自然运行证明 |
| `READBACK_UNCONFIRMED` | 传输、未知 HTTP、响应身份不一致或原回读尚未确认 | 不断言 owner 未执行，也不伪造成功；通过原账本继续核对 |

只有有限 admission code 白名单中的 **HTTP 409** 才可在 RPC 失败回执中分类为 `GATE_REJECTED`。未知 409、transport timeout、未知 HTTP，以及已知门禁文本出现在 HTTP 500，均为 `READBACK_UNCONFIRMED`。任意异常文本不进入公开 admission code；HTTP 200 仍须核同 binding/date/branch/trigger/run/product/input/attempt 和回执身份。原 cycle 明确给出的 `READBACK_UNCONFIRMED` 会保真，不被泛化为 `OWNER_FAILED`。

`COMPLETED` dispatch 只有在其成功/PARTIAL 响应含**同日期、同分支、可验证的原 owner 产物**时才作为成功终态缓存。缺输入的 `PARTIAL` 不会锁死当天 PREOPEN 或整个晚间 branch：PREOPEN 在 09:27 缺输入后，09:28 若已就绪且其他门仍通过，可以再次调用原 owner。成功后重复触发读回相同 dispatch/product 身份，不重复生成。

缺输入、失败和没有可验证产物的完成尝试**共用原每 trigger 最多 3 次尝试预算**；PREOPEN 等非晚间分支沿用 60 秒退避，EVENING_NEXT_SESSION 沿用 `plan_material_refresh.retry_backoff_seconds`（renderer 默认 600 秒）。缺输入不获得额外无限重试。SAME_DAY_CATCHUP 还受原同目标日期累计预算约束（默认最多 5 次，固定五个 slots）；锁、并发收敛、RUNNING reconciliation 与 dispatch receipt 2048 上限保持。未到退避期或达到预算，不增加 owner 调用或额外 dispatch 写入。

源码依据：dispatch 的 `_cycle_result`、`_rpc_failure_receipt`、`_verified_dispatch_owner_result`、`_execute_serialized_cycle`、`_request_bound_cycle`；[run_manager_announcement_cycle.py](../after/api/ops/run_manager_announcement_cycle.py) 的原窗口与 owner 回读分支。

## 8. legacy 兼容与验收边界

没有 `plan_owner_binding` 的旧 binding 仍调用原 `validate_binding(value, expected_app=API_APP_ROOT)`，保持原单根约束。旧 helper 调用路径未被替换，原 R1 monkeypatch/兼容测试继续使用该入口。

legacy canary 在 owner 与 worker 根相同时仍不接受迁移回执；跨根时仍必须具有原 `manager_daily_chain.plan_owner_source_migration.v1` 真实回执，且 `PLAN_OWNER_SOURCE_FILES` 在两个根的原始 SHA 完全一致。旧历史 canary 仍按原 `workspace?date=YYYYMMDD` exact URL 资格验证。新增 owner identity 不作为 legacy 缺失迁移证据的补丁；反过来，旧 canary 也不能通过补空摘要获得新合同资格。

新合同的 `hook_executed=false` 明确表示 canary 没有执行 scheduler hook。手工 POST、手工 GET、测试用 temp state、HTTP 200 和合成 fixture 都不能提升 `NATURAL`。真实自然任务须证明既有调度链以冻结 binding SHA 触发正确 source/target/slot，并由实际 API owner 返回相同 run/product/input/attempt 身份；现阶段该层为 `NOT_RUN`。

## 9. 本轮可复验的证据

CPython 3.14 原生验证，没有删除生产 Python 版本门。复核新增用例先产生 **13 failed / 78 passed**，修复后专属为 **91 passed**；与原 cycle/dispatch/daily 50 项合并为 **141 passed**。合并只出现一个现有 Starlette deprecation warning。

- [r3_binding_review_red_py314.log](../evidence/r3_binding_review_red_py314.log)：输入未就绪缓存、过窗分类、回读保真和历史 dynamic canary 的有效 RED。
- [r3_binding_review_green_py314.log](../evidence/r3_binding_review_green_py314.log)：91 项专属 GREEN。
- [r3_binding_review_regression_py314.log](../evidence/r3_binding_review_regression_py314.log)：141 项合并 GREEN，包括原并发/幂等/失败退避用例。
- [test_manager_r3_binding_identity.py](../tests/test_manager_r3_binding_identity.py)：双根真实不同源字节、raw SHA/root/enabled 拒绝、闭包预算、RPC 身份、六分类和 legacy 正反向 fixture。

在离线候选根内的回归命令是 `python3.14 -m pytest tests/test_manager_r3_binding_identity.py tests/test_manager_r3_cycle_outcomes.py tests/test_manager_daily_dispatch_20261008.py tests/test_manager_daily_automation_20261008.py -q --tb=short`。它只使用合成源根、合成时钟、临时 state 和 mock HTTP，不发真实 owner POST，不运行自然调度。

所有正式产物与回执继续要求 `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`；binding/canary 的对应字段按原 schema 使用小写 `research_only`。最终现场接续仍以原 owner 的精确 before/after、共享 ownership、同 binding 身份和分层真实回执为准。
