# 四功能接入修复：Mac 执行交接

## 1. 本次交付做了什么

本次提供 **4 个运行文件的最小补丁和 57 项离线回归**，复用现有 owner、store、reader 和计划保存入口。修复 Connect 配置在实际 `create_app → service → workspace → read_scope` 链路中的传递，并使 V2 reader 的观察时间 `read_at` 不再污染非空材料卡片的计划输入身份；持久化 `available_at`、日期、原始 SHA 与 stale 校验继续生效。[S1][S2]

本文件是 Mac 操作说明。Chat 未执行真实 owner、Mac 集成、部署、live API/UI 或自然时段验收；以下命令须由 Mac 执行者在已有授权范围内，使用已确认的源码、根目录、工件和服务。本文不提供猜测路径，也不启停服务。

| 运行文件 | 本次修改 |
|---|---|
| `apps/api/v35_api/app.py` | `create_app` 接收 `workspace_connect_binding`；省略时在构造期快照旧五个环境键。 |
| `v4/manager_research/service.py` | 保存独立的 binding 字典副本，与该实例的 store/readers 一起绑定。 |
| `v4/manager_research/workspace.py` | 向原 `read_scope` 转发 service binding。 |
| `v4/manager_research/connect_selection.py` | 消费显式 binding；空/错 binding 不借用环境；拒绝非规范根及 symlink ancestor；卡片仅排除 `read_at`，保留真实 `available_at`。 |

公告 consumer、原公告 CLI、US mapping 算法、security-master/HK02 reader、计划保存和 `STALE_INPUTS_CHANGED` 比较没有被替换。57 项新测试的分组、旧回归与验收状态见 [ACCEPTANCE_MATRIX.md](ACCEPTANCE_MATRIX.md)。

## 2. 先核源码，再在隔离 review 树落补丁

输入仓库固定为 `lexi2016/v4@74478a0e62be215c8527ccc9a14b89b51042d014`；运行目标来自该 commit 内 `handoff/manager-four-functional-gaps-20261009/package/code/r2_chat_patch_target/`。这不是对当前 Mac 进程源码身份的推断。R1、R3、10/09 actual-owner runner 是独立参考组，不能混版覆盖 R2。[S1][S3]

由执行者设置下列变量，值取自实际交付记录和已批准的隔离源码树：

| 变量 | 必须指向 |
|---|---|
| `V4_FOUR_PACKAGE_ROOT` | 本次交付包根目录，包含 `tools/`。 |
| `V4_FOUR_REVIEW_ROOT` | 已核对完整依赖、未覆盖现役进程的 review 源码根。 |
| `V4_FOUR_PATCH` | 交付 manifest 指定的补丁文件绝对路径。 |
| `V4_FOUR_API_BASE` | 已获准验收、实际由目标 `create_app` 建立的 V4 loopback API base。不要猜端口或指向其他面板。 |
| `V4_FOUR_ACCEPTANCE_DIR` | 本次新建、与 owner state 分离的本地验收记录目录。 |

在已核对的项目 Python 环境中执行；`python` 应指向该环境。本轮 Linux 回归使用 Python 3.14.8，完整版本清单见验收矩阵。以下是交付工具的调用合同，具体补丁文件及校验清单以交付 manifest 为准：

```bash
cd "$V4_FOUR_PACKAGE_ROOT"
python tools/verify_delivery.py --source-root "$V4_FOUR_REVIEW_ROOT" --side before
git -C "$V4_FOUR_REVIEW_ROOT" apply --check "$V4_FOUR_PATCH"
git -C "$V4_FOUR_REVIEW_ROOT" apply "$V4_FOUR_PATCH"
python tools/verify_delivery.py --source-root "$V4_FOUR_REVIEW_ROOT" --side after
git -C "$V4_FOUR_REVIEW_ROOT" apply -R --check "$V4_FOUR_PATCH"
python tools/run_regression.py --source-root "$V4_FOUR_REVIEW_ROOT" \
  --output-dir "$V4_FOUR_ACCEPTANCE_DIR/regression"
```

`run_regression.py` 将 `--source-root` 视为只读输入，自建临时 execution copy，向 `--output-dir` 输出本轮记录；不在实际源码树或 owner store 中创建测试状态。

`before` 不匹配表示源码并非补丁预期字节。保留差异并交给源码 owner 协调，不强贴补丁、不借旧快照凑依赖。`after`、测试及反向检查结果都写入独立记录。全工程旧门禁须与新 57 项分开报告：本轮候选树 `python -m pytest -q --maxfail=1` 为 `COLLECTION_BLOCKED`，首个错误是原支持模块缺少 `HK_EXPECTED_MISSING_SOURCE_SHA256` 导出。校验四文件 before SHA 的原 R2 离线组装树也遇到同一首个收集错误；未修改该范围外源码，不能报告全工程通过或推断真实 Mac 的完整工程状态。具体命令与日志见验收矩阵。

需要撤回本补丁时，在确认没有后续交叉修改的 review 树执行 `git apply -R --check` 后再 `git apply -R`。该操作只处理代码；不删除或回滚 owner 数据、历史计划、原 run、receipt 或旧 SHA。

## 3. 在既有 create_app 配置中绑定唯一来源

保持实际启动入口及其已有参数，由 Mac 配置 owner 将以下值接入**同一个 `create_app`**。不能用裸 `ManagerResearchJobService(...)` 或旧 minimal runner 代替进程接入验收。

| `create_app` 参数 / 原配置 | 输入和优先级 |
|---|---|
| `data_root` | 已有 native data / US peripheral 输入根。实际 `ResearchPeripheralUsMarketReader` 从该 root 的 exact-session payload、receipt、manifest 读取。不要误传 manager state 或 archive root。 |
| `manager_research_state_root` | 唯一 manager store；公告 capture/import、US mapping、plan product、attempt 和 HTTP reader 必须共用它。 |
| `shared_data_root` | 已有共享数据根；在没有专用环境配置时供精确日 master 与 screen 使用。 |
| `V4_MANAGER_SECURITY_MASTER_ROOT` | 若已配置，优先于 `shared_data_root`，用于 material discovery/native identity 等原 reader。 |
| `V4_MANAGER_SCREEN_AUTHORITY_ROOT` | screen 优先使用此值；未配置则使用 `V4_MANAGER_SECURITY_MASTER_ROOT`，再回到 `shared_data_root`。 |
| `research_data_root` | 保留现有 archive 根。既有后备配置是 `V35_RESEARCH_DATA_ROOT`，再到 native data root；本批不为接 US 而搬动 archive。 |
| 既有 `V4_MANAGER_NEWS_DATA_ROOT` / `V4_MANAGER_NEWS_OWNER_ROOT` | 保留原 catalyst/news 配置；不要与 US、archive 或 authority root 随意互换。 |
| `workspace_connect_binding` | 下表的实例级 Connect 配置，读取原精确目标日 V2 authority。 |

### Connect 五键合同

| binding 键 | `create_app(..., workspace_connect_binding=None)` 时读取的旧环境键 | 用途 |
|---|---|---|
| `universe_root` | `V4_MANAGER_UNIVERSE_ROOT` | 原精确目标日 HK_CONNECT V2 authority root。 |
| `authority_owner_root` | `V4_MANAGER_UNIVERSE_OWNER_ROOT` | 已确认、含原 `stage_center/hk_universe_preflight.py` 的 owner 源码根。 |
| `authority_owner_sha256` | `V4_MANAGER_UNIVERSE_OWNER_SHA256` | 该 owner 源码的真实 SHA-256；不是产品或 manifest SHA。 |
| `capture_receipt_root` | `V4_MANAGER_HK_CAPTURE_RECEIPT_ROOT` | 原 D-1 capture receipt 根；仅原诊断支链使用。 |
| `dispatch_receipt_root` | `V4_MANAGER_HK_DISPATCH_RECEIPT_ROOT` | 原 D-1 dispatch receipt 根；不能替代目标日 V2 membership。 |

`None` 的兼容路径在 **app 构造时**读取五个环境值，随后 service 复制字典。显式字典完整决定此实例的绑定；`{}` 保持未绑定，空/错字段不会向环境借值。构造 app 后修改环境变量或原参数字典，不应改变这个实例。若需更换来源，按既有进程配置流程处理，并重新验收实际实例；本文不发起重启。[S2]

根目录使用已确认的规范绝对路径，拒绝 symlink ancestor、越界路径及错误 owner SHA。末两键缺失不授予 membership，也不应补造 receipt。

在**既有 factory**中的接入形式如下。`actual_existing_create_app_kwargs` 和各值须来自现场已核对配置，本段不是新启动器：

```python
app_kwargs = dict(actual_existing_create_app_kwargs)
app_kwargs.update(
    data_root=actual_us_native_data_root,
    manager_research_state_root=actual_manager_state_root,
    shared_data_root=actual_shared_data_root,
    research_data_root=actual_archive_root,
    workspace_connect_binding={
        "universe_root": actual_target_v2_root,
        "authority_owner_root": actual_hk_owner_source_root,
        "authority_owner_sha256": actual_hk_owner_source_sha256,
        "capture_receipt_root": actual_capture_receipt_root_or_none,
        "dispatch_receipt_root": actual_dispatch_receipt_root_or_none,
    },
)
app = create_app(**app_kwargs)
```

## 4. 按固定日期 pair 核对原工件

本问题包的目标 pair 为 `target/selection=20261009`、`announcement publication=20261008`；原现场 screen 要求 `verified_session=20261008`。其他日期必须由原 calendar/owner 推导，不能将 latest 重新标成 D-1。[S1]

| 原 owner 输出 | 进入 reader 前必须可追溯的证据 | 进入 workspace 的字段 |
|---|---|---|
| Announcement | exact pair catalog、captured body corpus、实际 Reader 输出、身份不同的实际 Reviewer 输出、注册 handoff、import receipt；逐件原始字节 SHA 和 run。 | `announcement_reviewed_analysis`、ANNOUNCEMENT daily channel、公告 input identity。 |
| HK Connect V2 | 目标日双板 capture、artifact、manifest、receipt、current、publication、owner source pin；market/role/date 正确，持久化 acquired/available 不晚于实际 cutoff。 | `selection_diagnostics.membership`、scope identity、HK_CONNECT channel；观察 `read_at` 仅诊断。 |
| Oversold | 同一权威 root 下精确日 master index entry、snapshot/manifest/receipt、原 HK02 panel 与所需历史、成交量单位和尺度 provenance。 | `market_screen`、`market_screen_evidence`、OVERSOLD channel。 |
| US mapping | 原 exact-session peripheral payload、独立 receipt、manifest；原 mapping run/product、artifact SHA、source identity、覆盖计数与实际可用时间。 | `us_mapping_research.daily_run`、`owner_chain.us_mapping_daily_plan_reference`，继而 plan identity。 |

已有合法 exact-date master 的离线读取消费已验证；**volume provenance 为 `NOT_PROVEN` 时仍是 pending / `READY_WITH_GAPS` / `PARTIAL`**。缺 master entry 不回退日期，缺 authority 或 source 不用空 rows 冒充 `VALID_EMPTY`。四问题以外的 close/breadth/archive/Vibe 等原依赖缺口继续如实显示。[S1][S4]

## 5. 复用现有公告单日 owner

下面模板依据前轮已交付 CLI 支持版本：`ops/run_manager_daily_announcement.py`，SHA-256 **`aee0e5c31f30b296864a7ad81263fbc748b65cb9b4d443f83a756019cbc94a38`**。它是本次离线验证的独立支持依赖，**不在本轮 4 个运行文件补丁内**。包中 `actual_owner_runner_20261009` 的旧 `bfb853fb…` runner 只作接口参考，不能重贴覆盖现役 CLI。[S3][S5]

执行者先核对现役 CLI 身份及 `--help`。若不一致，保留版本差异，由原 owner 协调；不自动覆盖。下列变量分别绑定真实 app root、唯一 manager state、capture 返回的 evidence run/路径、实际 Reader/Reviewer 文件及原调度 task/身份。不要把测试 fixture 或本说明中的占位值作为业务证据。

```bash
python "$V4_FOUR_APP_ROOT/ops/run_manager_daily_announcement.py" --help
python "$V4_FOUR_APP_ROOT/ops/run_manager_daily_announcement.py" capture --help
python "$V4_FOUR_APP_ROOT/ops/run_manager_daily_announcement.py" register-handoff --help
```

**A. 复用已有 exact-pair capture；确有缺口且 Mac 已有授权允许补采时，才由原 owner 执行 capture：**

```bash
python "$V4_FOUR_APP_ROOT/ops/run_manager_daily_announcement.py" capture \
  --target-date "$V4_FOUR_TARGET_DATE" \
  --publication-date "$V4_FOUR_PUBLICATION_DATE" \
  --api-base "$V4_FOUR_API_BASE" \
  --research-state-root "$V4_FOUR_MANAGER_STATE_ROOT"
```

使用该结果的真实 `evidence_run_id`、catalog/body/evidence 路径。已有 exact run 需续跑时，按其合同使用 `--resume-evidence-run-id`，不新抓同源代替已有 receipt。capture 只提供原文本，不替代实际 Reader 或独立 Reviewer。

**B. 实际 Reader、Reviewer 完成后校验，再注册原输出：**

```bash
python "$V4_FOUR_APP_ROOT/ops/run_manager_daily_announcement.py" prepare \
  --target-date "$V4_FOUR_TARGET_DATE" \
  --publication-date "$V4_FOUR_PUBLICATION_DATE" \
  --catalog-read "$V4_FOUR_CATALOG_READ" \
  --semantic-catalog "$V4_FOUR_READER_OUTPUT" \
  --body-corpus "$V4_FOUR_BODY_CORPUS" \
  --body-capture-evidence-root "$V4_FOUR_CAPTURE_EVIDENCE_ROOT"

python "$V4_FOUR_APP_ROOT/ops/run_manager_daily_announcement.py" register-handoff \
  --target-date "$V4_FOUR_TARGET_DATE" \
  --publication-date "$V4_FOUR_PUBLICATION_DATE" \
  --evidence-run-id "$V4_FOUR_EVIDENCE_RUN_ID" \
  --research-state-root "$V4_FOUR_MANAGER_STATE_ROOT" \
  --semantic-catalog "$V4_FOUR_READER_OUTPUT" \
  --reviewer-output "$V4_FOUR_REVIEWER_OUTPUT" \
  --decisions "$V4_FOUR_REVIEWED_DECISIONS" \
  --parent-task-id "$V4_FOUR_PARENT_TASK_ID" \
  --reader-identity "$V4_FOUR_READER_IDENTITY" \
  --reviewer-identity "$V4_FOUR_REVIEWER_IDENTITY"
```

`--decisions` 对应实际审阅的显式 dispositions；不存在该原文件时删除模板中的这一参数行，并按原 CLI 合同保留 `NOT_ASSESSED`，不要补造文件。Reviewer 必须独立、身份不同，且输出所声明的日期、run 和 SHA 真实对应 Reader/body/catalog。`prepare` 或 `build-reviewed` 本身不等于已 import。

**C. 用原 API import，再核 exact pair：**

```bash
python "$V4_FOUR_APP_ROOT/ops/run_manager_daily_announcement.py" import \
  --evidence-run-id "$V4_FOUR_EVIDENCE_RUN_ID" \
  --research-state-root "$V4_FOUR_MANAGER_STATE_ROOT" \
  --api-base "$V4_FOUR_API_BASE"

python "$V4_FOUR_APP_ROOT/ops/run_manager_daily_announcement.py" readback \
  --target-date "$V4_FOUR_TARGET_DATE" \
  --publication-date "$V4_FOUR_PUBLICATION_DATE" \
  --api-base "$V4_FOUR_API_BASE"
```

缺 capture、原始输出或 import receipt 时保留 `CANNOT_CONFIRM` / `NOT_RUN`。本轮公告 8 项测试在原 R2 与 after 均通过，证明原消费合同可用，并不证明现场缺失输入已经补齐。

## 6. 经实际 app 的原刷新入口保存，再 GET 回读

确认第 3 节的实际进程身份及同一 store/readers 后，由现有 API 调用原 owner。该既有 POST 先准备独立 US mapping owner，再用**其完成后的实际时间**调用原计划 owner，避免以早于 mapping publication 的 click 时间作为计划 cutoff；GET 只读取和校验。[S2]

设定本次日期变量；问题包复核值为 `20261009 / 20261009 / 20261008`。验收输出写入本次新目录，保留先前目录和 owner 原文件。

```bash
curl -fSs -X POST -H "Origin: $V4_FOUR_API_BASE" --data-binary '' \
  "$V4_FOUR_API_BASE/api/v4/manager/research/workspace/refresh?date=$V4_FOUR_TARGET_DATE&selection_date=$V4_FOUR_SELECTION_DATE&announcement_date=$V4_FOUR_PUBLICATION_DATE" \
  -o "$V4_FOUR_ACCEPTANCE_DIR/workspace-refresh.json"

curl -fSs \
  "$V4_FOUR_API_BASE/api/v4/manager/research/workspace?date=$V4_FOUR_TARGET_DATE&selection_date=$V4_FOUR_SELECTION_DATE&announcement_date=$V4_FOUR_PUBLICATION_DATE&view=dynamic" \
  -o "$V4_FOUR_ACCEPTANCE_DIR/workspace-get.json"
```

确认 HTTP 响应来自目标实际 app；不能只靠 200 状态验收。逐项核对：

1. `date_bindings` 精确匹配；各 channel 保留自己的 publication / source session。
2. 公告产品为已消费的原 import，真实 selected/watch/pending counts 可追溯；HK membership 经目标日 V2 验证；screen 的 exact master/panel/provenance 完整性如实显示。
3. US `daily_run` 的 run/artifact SHA 与 `owner_chain.us_mapping_daily_plan_reference` 一致，并且在 plan cutoff 前已可用。按 configured/available/reviewed counts 解释范围，`full_market_coverage=false` 不能宣称全市场有效空。
4. `plan_product.status=CURRENT`、`consumed=true`，且 `plan_product.run_readback.status=VERIFIED`。`plan_product.run_id/sha256` 分别匹配 readback 的 `run_id/artifact_sha256`；readback 的 `input_identity` 匹配返回的当前输入身份。readback 的 `owner_attempt_run_id/owner_attempt_sha256` 必须匹配该产品的 exact sealed attempt；不要将 product SHA 与 attempt SHA 当成相同哈希，也不要只核最新 attempt。
5. 原 owner `PARTIAL` 及每个 gap 保留。`CURRENT` 只表示该研究计划当前可验证，不表示所有功能完成、BUY 许可或自然运行成功。
6. `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`；不改 Stage、BUY 或 Vibe 8910。

再次只读 GET，确认稳定工件下 input/run 不因 `read_at` 前进而变化。真实 source/binding/日期变化时应继续 stale；经原 owner 对当前有效输入重建后才恢复 `CURRENT`。不要在真实 state 中为了做反例而篡改文件；损坏/错日等反例由离线回归覆盖。

若当前日已晚于目标日，手动刷新必须保留实际执行时间与 retrospective 标识；不可伪造旧 cutoff 或自然时段。此处 `view=dynamic` 核验新建的实际 as-of 计划，不把它冒充历史 preopen 产品。历史产品、旧 attempt、原 SHA 和历史 reader 拒绝记录均保留。

## 7. 交回最小验收记录

记录实际源码根、提交/文件 SHA、入口及进程/release 身份、配置 root 和 owner source pin、日期 pair、cutoff、原 source/manifest/run/SHA、import receipt、mapping product、plan product 与 exact attempt、GET readback、原 gap 与安全标志。**文件字节 SHA 与产品内 canonical SHA 分列**，不要混为一个值。

只回传必要 metadata 和精简差异；完整原输出/行情/计划仍留在原 owner store。对 MAC、INTEGRATED、DEPLOYED、API、UI、NATURAL 分别填写真实状态。不能用 Linux TestClient、手动晚补或历史回看替代 live UI/自然时段证据。

历史解释继续遵循原交接：用户所指 9/30 独立成功入口/receipt 本次未定位，不能据此否定其成功；10/7 publication → 10/8 readback 只证明公告子链可消费且仍 partial；本次 `read_at` 离线根因不能直接解释真实 `5df99128… → 7c5d9f18…` 现场变化。[S1][S3]

## 来源

- [S1：固定四问题矩阵](https://github.com/lexi2016/v4/blob/74478a0e62be215c8527ccc9a14b89b51042d014/handoff/manager-four-functional-gaps-20261009/package/FOUR_ISSUE_MATRIX.md)。
- [S2：固定 R2 app/service/workspace/router 源码目录](https://github.com/lexi2016/v4/tree/74478a0e62be215c8527ccc9a14b89b51042d014/handoff/manager-four-functional-gaps-20261009/package/code/r2_chat_patch_target)；本轮 `runtime.patch`、`source_manifest.json`、`evidence/new_regression_57.log`、`evidence/app_wiring_green.log`、`evidence/plan_result.json`。
- [S3：单日 owner 复用、日期与历史证据边界](https://github.com/lexi2016/v4/blob/74478a0e62be215c8527ccc9a14b89b51042d014/handoff/manager-four-functional-gaps-20261009/package/DAY_RUN_REUSE_AND_INTEGRATION.md)；[原 source manifest](https://github.com/lexi2016/v4/blob/74478a0e62be215c8527ccc9a14b89b51042d014/handoff/manager-four-functional-gaps-20261009/package/SOURCE_SNAPSHOT_MANIFEST.json)。
- S4：本轮 `evidence/hk_report.json`、`evidence/hk_red_v2_card_clock.log`、`evidence/plan_r2_clock_counterfactual.log`、`evidence/PLAN_INVESTIGATION.md`、`evidence/announcement_test_summary.json`。
- [S5：前轮已交付 CLI 支持版本](https://github.com/lexi2016/v4/blob/74478a0e62be215c8527ccc9a14b89b51042d014/handoff/manager-three-channel-repair-20261009/after/api_r3_candidate/ops/run_manager_daily_announcement.py)，本轮角色与 SHA 记录于 `provenance/offline_source_assembly.json`。
