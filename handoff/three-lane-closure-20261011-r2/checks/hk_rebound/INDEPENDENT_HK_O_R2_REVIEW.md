# H / O R2 独立只读复核

## 结论与证据边界

2026-10-11 09:14:18 UTC 完成主要矩阵复跑，5 个独立命令均退出 0，所有独立断言通过。随后仅补跑同次运行 trace 的 Stage 与 O 原应用 owner 保存两项，最终均通过，见下文。候选源码 SHA 在各次验证前后保持一致。复核者未修改 candidate 源码、candidate 测试或真实数据，也未访问、启动或执行实际 Mac owner。

本次证明 R2 的成交量恢复、精确归档绑定和 H 原消费者读取在隔离输入下符合预期；不证明真实 D-1 / 会员 / 60 日输入已齐、生产依赖已经安装、实机 API/UI 已读回，或自然日常链路已经完成。所有临时 Stage stores 和本轮 sidecar fixtures 已自动清理。

主要矩阵总账为 `independent_hk_o_r2_results.json`，保存真实运行命令、退出码、结果文件及 SHA、23 个完整源码 SHA、当时 6 个脚本 SHA 和输入边界。追加 trace 的命令与一次记录 checksum 口径错误后修正的真实执行过程保存在 `traceability/execution_log.json`；交付的 7 个脚本、原依赖和两个新 trace 结果由 `traceability/source_and_script_manifest.json` 绑定。初始矩阵不伪装成后加 trace 代码的运行结果。

## 冻结源码身份

| 文件（相对 candidate） | SHA-256 |
|---|---|
| `v4/manager_research/workspace_plan.py` | `3f22ef4393168afe4a7c7252d2dfbe1456da557194f18645f967caa9107f5c91` |
| `v4/manager_research/workspace_daily_channels.py` | `5a436a362710c8bb39cef72da6b99cfebef63f7e5ff98ea7741334e2f2c7928b` |
| `v4/manager_research/workspace.py` | `9dc87e10bf9f648bbbe43fe9cf368d7a71101730115e40b844568406db57efd1` |
| `stage_center/consumer.py` | `cbc91d835c94e88b5065c6e95711017f9e97fd4d5bd7c230b7e88acab54f1557` |
| `stage_center/selection.py` | `31e80e068890be03957920870719030463262c78911953541be3074f8650d4c9` |
| `stage_center/contracts.py` | `6880f6a82c7f4fb0fde5c0661bd5a8bb12b590661a4b8552bcb3d6be969ae83d` |
| `infrastructure/owned_io.py` | `9a74731287ca7c9667643557d4ae42f63453a025665ba28f5b65fdbff7d54ee0` |
| `v4/manager_research/research_attention.py` | `4073ad6f0c36de045017dc8fa18433438cf63371c13588777117108945aad1bb` |

其中 workspace 的最终实测 SHA 是 `9dc87e…`，不是先前冻结消息中的 `472212…`。本报告已针对新字节复跑归档探针。

## O：复核的根因与修复结果

原陷阱是把“panel 数值完整”视作无需修复，忽略 volume provenance 未核实。这样会使一个已有合法六日 sidecar 的代码在 panel 新增数值后反而失去 sidecar 恢复机会。R2 将两种状态分开：只要同源成交量证明仍不足，仍调用原六日 reader；不能仅因数值非空就接受 volume。

3 条原症状回归全部通过：当前 panel volume 缺失与数值完整但 provenance `NOT_PROVEN` 两种输入，均读取 sidecar 一次、得到 1 strict / 0 pending；较早 prior60 日期存在但 high 为空时，仍为 pending，并列出 `invalid_prior60_high_dates`。该旧诊断 fixture 的日期序列是显式 synthetic；原生日历证明由下面 14 条真实 reader fixture 提供。

真实 reader 测试保持原 sidecar adapter、原 `read_verified_daily_supplement`、原生日历及 SHA/日期/请求/来源/时限验证。仅 panel/master witness 边界使用明示 synthetic 输入；未替换 sidecar 校验门禁，未调用采集或发布 owner。

有效 case 使用原生日历六日 `20261002, 20261005, 20261006, 20261007, 20261008, 20261009`。panel 的数值 volume 使比率为 1；sidecar 六个 trade 使比率为 2。结果使用完整同一 sidecar 的六日成交量，ratio=2、strict=1；panel close=8、prior60 high=10 不变，尽管 sidecar OHLC 刻意设为 panel 的 10 倍。绝对 volume unit 仍是 `NOT_PROVEN`。所有其他 case 均保持原价格，不混拼 panel 与不完整 sidecar 的成交量。

### Sidecar 统计：14 个 case，不能写成 15 个

**1 个完整有效 READY + 12 个无效输入拒绝 + 1 个合法 PARTIAL_WITH_PENDING。** 后两类共 13 个非 READY 情形；合法 partial 被 reader 接受为有缺口，但 screen 必须 pending，不能称作 reader 拒绝。

| Case | 原 reader 的真实结果 | Screen 结果 |
|---|---|---|
| valid | READY | strict=1, pending=0, ratio=2 |
| wrong_pointer_date | POINTER_IDENTITY_INVALID | pending |
| wrong_manifest_sessions | MANIFEST_CONTRACT_INVALID | pending |
| future_bar | BAR_DATE_INVALID | pending |
| duplicate_bar | BAR_DATE_INVALID | pending |
| manifest_sha | CHECKSUM_MISMATCH | pending |
| raw_sha | CHECKSUM_MISMATCH | pending |
| response_sha | REQUEST_OR_RESPONSE_INVALID | pending |
| missing_session_claimed_ready | MISSING_SESSION_STATUS_INVALID | pending |
| partial_pending | PARTIAL_WITH_PENDING | pending；不混源补齐 |
| late_pointer | POINTER_AFTER_CUTOFF | pending |
| wrong_panel_sha | POINTER_IDENTITY_INVALID | pending |
| normalized_trade_changed | NORMALIZED_ROWS_MISMATCH | pending |
| absolute_unit_promoted | BAR_UNIT_INVALID | pending |

表内拒绝码均省略共同前缀 `HK_DAILY_SUPPLEMENT_`。最终断言同时要求具体拒绝码保留在 `screen.gaps` 与 diagnostics gaps，覆盖 Writer 最新的 `supplement_gaps` 修复，且逐 case 核对读取前后的 fixture SHA 不变。详见 `sidecar_owner_gate_results_r2.json`。

### 原六日 reader 的来源边界

候选两份 `hk_daily_supplement.py` 完整文件 SHA 均为 `f71d6bb8bc0d55a0205d9734562c37d249654e3e39ccc85e18dd6398aa3c3862`。此前 final_20261010 原 reference 的完整 SHA 为 `5528a6b44bfb5b79265732b85beb1fb89860355b48a852da07264fb34231c79c`。

完整文件并非逐字节相同。已核对差异位于 capture 的 READY 缓存复用和 published_at 返回；`read_verified_daily_supplement` 函数文本一致。上述 14 个 fixture 分别通过两个模块的真实 reader，结果逐项一致。因此本复核支持“原读取门禁保持一致”，不支持“整个采集 owner 与该 reference 字节一致”。复跑脚本对 reference 的完整 SHA 固定校验。

## O：归档与保存后读回

原问题有两处：未归档的全 excluded ledger 可显示 READY_EMPTY/0；已保存产品 A 的 exact attempt 被校验后，展示层却拿后来失败的 latest attempt B 来绑定，使 A 的 run/SHA 消失。

R2 的 `OVERSOLD_RESULT_NOT_ARCHIVED` 只进入 channel 层，不进入 screen、原 decision ledger、plan input identity 或保存状态计算，因而不制造“必须先有归档才能保存”的循环。原 owner 的顺序仍为保存产品 → 原 `_read_plan` 验证 → sealed terminal attempt → `_readback_plan` → 重建 daily channels。`_readback_plan` 在同产品读回时也重建 channel。

独立归档探针 2 条通过：A 仍为最新成功 attempt 时为 CURRENT / consumed / READY_EMPTY / 0；之后存在 FAILED B 时，仍用 `workspace_plan_product_attempt` 绑定 A 的 run/SHA，B 继续作为最新 attempt 显示。产品 sealed bytes 的 SHA 保持 `22ac54cff2eef961174c38601773f8d4673fd9f29839581a8710889b0d457f4b`。该探针使用原 `_readback_plan` 与原 SHA/attempt 检查，store I/O 为明示内存 fixture，不能说是实际 owner 保存。

另有 7 条 O projection 回归断言通过：未归档非空结果为 PARTIAL；错 target、未来 source session 为 CANNOT_CONFIRM；缺 source refs、规则矛盾、重复代码均保持未决；未归档全 excluded 为 PARTIAL 且 candidate_count=null。已保存且合法的空结果才可显示 READY_EMPTY/0。详见 `archive_binding_results_r2.json` 与 `daily_projection_results_r2.json`。后者额外保留一条不完整 H fixture 的观察，不计入这 7 条 O 回归。

## H：恢复原依赖后的完整消费者验证

恢复文件 `execution_evidence.py` 的 Git blob 为 `3af4fb13f7da60e0822827fb834c671cef16a372`，SHA-256 为 `1be96e736fda2863f6f8ff2315e8879a98499bbd30f5a911b46423c4dc6f094b`。固定来源 commit 为 `87853ef6c177f0243667b12b9eae8110c1be0f12`，路径为 `handoff/stage-research-recovery-20261009-r2/after/api/stage_center/execution_evidence.py`。

仅以 review-only import finder 为缺失单文件提供此原文，完整导入 candidate `stage_center` 正常入口，并调用未替换的原 selector、SelectionStore、StageSelectionConsumer 和 recovered execution reader。原 selector 与 store 的发布仅用于隔离的 synthetic trio；D-1 和 membership 声明为 fixture，不能作为市场权威证据。

9 条全部 PASS：

1. 完整导入及空 store 读取，不产生文件。
2. 原 store trio 无 execution receipt：10 行仍可见，H 为 PARTIAL。
3. 原 store trio 与匹配 synthetic receipt：10 行和原 rank/order 保留、selection binding 为 BOUND，natural_verified=false。
4. receipt 的 wrong run：拒绝绑定，保留真实 trio 的 10 行及 PARTIAL。
5. artifact 篡改：CANNOT_CONFIRM，0 行。
6. selection receipt 篡改：CANNOT_CONFIRM，0 行。
7. selection manifest 篡改：CANNOT_CONFIRM，0 行。
8. latest pointer artifact SHA 冲突：完整 consumer 拒绝。
9. 已验证的 recovery/backfill trio：不纳入 ordinary H channel。

各次 consumer 读取前后 fixture 文件集合及 SHA 不变；临时 store 已删除。详见 `full_stage_consumer_results_r2.json`。测试时 candidate 的 `stage_center/execution_evidence.py` 仍不存在，故当前 candidate 原样导入闭包不能从本测试推导。Writer 可按此已验证的恢复配对收回原依赖。

## 同一次原应用运行的精确追溯

### H：原 SelectionStore 的 trio 与 Stage execution receipt

追加的 `traceability/full_stage_consumer_results_r2.json` 仍为 9 PASS，并在首次匹配成功的同一 synthetic run 采样 `same_run_traceability` 后再执行破坏性 fixture case、最后清理临时 store。目标日为 20261009，阶段 STAGE_0935_0940，100 条 synthetic 输入，经原 selector 得 10 行，run 为 `run-62c8e702d45d86b78c3baf12`。

| 身份 | 本次精确值 |
|---|---|
| 输入 rows canonical SHA | `e7abe5ef073457117f9786547335c97db066c534859b303689bf96ecb7d7dc0d` |
| Membership fixture identity | `d7576071d7e2e92fc731365edf68b12719e2a2376fbd46ecf7a6a7f18ef08650` |
| D-1 引用 | 20261008、`STRICT_0_2_READY`、exact_date_top100、SHA `2222222222222222222222222222222222222222222222222222222222222222`；均为明示 synthetic assertion，没有提供真实 D-1 artifact |
| Algorithm SHA | `fa010779e194b06ee9a77799d6b41a8d76a641a047b05b96c4594766e4497506` |
| Artifact CSV raw / owner SHA | `6cf08b5cd74d02f21edcf31bdf0371b6bba09f2932b8a42ba1cfa880113a4587` |
| Manifest owner canonical SHA | `8045647c86cd40d54717646c0d8f94405090ee7269a27beefdaf5017cb4d470c` |
| Manifest raw file SHA | `37e2e457ceaf3e7702c003ca3c9f7050cbd7ea391efe7407b372be3dc47e0335` |
| Selection receipt owner canonical SHA | `b307a24d33e4234439a14e1db114080368c50f986182c06d303e51b1ed4e3978` |
| Selection receipt raw file SHA | `085170be1d489829024037d1a7e5c66053bfe49e285a4e2ee99f1b8cfc9410dc` |
| Stage execution receipt raw / observed SHA | `e8f0e65ab59f6a6de34c601d86459d02204942712b33c78e2034bcd0447cf255` |

原 SelectionStore 对 manifest/selection receipt 使用 canonical JSON 对象 SHA；落盘 JSON 的物理文件 SHA 是另一口径。首个新增 trace 断言将两者当成相同而失败；只修正了 reviewer 脚本，使其分别记录并分别核对两个口径，后续完整 9 case 重跑通过。此处没有修改或绕过原消费者检查。JSON 同时保存相对路径、字节数、原 source_evidence、membership fixture、D-1 引用、code/rank/原列表顺序及被绑定的投影身份。

### O：原 refresh owner → 原 store → service GET → HTTP GET

新增 `traceability/original_o_owner_save_trace_r2.json` 使用真实 `ManagerResearchJobService.refresh_workspace_plan`、`ManagerResearchStore`、原 decision ledger、plan/attempt seal 与 readback 检查和 FastAPI route，保存到隔离临时目录。仅时钟、screen source 输入和不存在的 announcement catalog 为明示 fixture；未调用真实数据采集。

同一次运行先得到未归档 PARTIAL/null，再由原 owner 保存并得到 O READY_EMPTY/0；service GET 与 HTTP GET 200 均读到相同 run、product SHA 和 decision_identity。GET 前后 store 文件集合及 SHA 不变。整体 owner attempt 为 `PARTIAL`，因为其他 lane 仍缺输入；该记录仅证明 O 合法空 ledger 的归档读回，不代表整体三路 ready。

| 身份 | 本次精确值 |
|---|---|
| 计划日 / 来源日 / cutoff | 20261008 / 20261007 / 2026-10-08T09:00:00+08:00 |
| 原 owner run | `7b38d5fbca6c4619ad0bc4e6397d1d91` |
| Synthetic screen raw file SHA | `dcf6a386f32b9c01d261982609155712234f1944ebe6370bd9e88c1b85a94502` |
| 原 product semantic SHA | `d20975fc39ec46babae60b089bcbadf6b880a282cbae1d978e2236975f1aa786` |
| 持久化 product raw file SHA | `2b71c92cf0931a3180805c3219ded3c48bb0fa6f4d96906abee3f72569311e9a` |
| 原 attempt seal SHA | `48999771c8119c92006d7187e0c6693dce0a10fddabcac9cc57741b97f2aa3c5` |
| 持久化 attempt raw file SHA | `11036a39b2e373c14777d74aefd68df41f5ca1df1b6021aa09fa5b59afe85179` |
| 原 decision_identity | `96ff2799de202b620265866ba4245f1437d20c1ec66b89ad0de31d88674f0274` |

screen 中 aaaa… 输入标识及来源引用属于 synthetic 上游 fixture。该 fixture SHA 是测试输入文件的字节证据，不能称为已核实市场 panel。HTTP 为隔离 TestClient，没有实机进程、页面截图或自然 scheduler 证据。临时目录已经删除，仅保留紧凑追溯记录。

## 尚未闭合的真实输入与运行边界

上传 `evidence/DATA_GAPS_必须解决.md` 记录，20261009 的 exact D-1 Top100 对应 20261008 authority 尚未核实；10/09 晚间 693 行 master 不能代替 10/08，10/09 事后发布的 panel 也不能跨回早间 cutoff。精确逐 symbol 的 60 个完整交易日与成交量来源未核实，不能据此宣称不存在，也不能拿 strict214 代替完整原选股台账。

History reviewer 已找回两个不同角色的带 `--verified-source-store-root` 原 ensure owner：actual_pool blob `9a538be003e018c9bff1140510ecc34e9bfd9ba3` 和 canonical blob `c24157c7a0185e2bed31b36fdfd9e0d1346ec79a`。本次检查 candidate/ops 的旧版本仍无此参数，复核者没有部署或执行它们。恢复时应保留角色，不用旧 supporting checkout 顶层文件替换现有完整 SelectionStore；原依赖来源核验见 history reviewer 的 dependency recovery 证据。

后续具体门槛仍是：恢复可核验的目标日 authority / 原始缓存；由既有原 owner 按原交易日历和 cutoff 消费，缺口保持显式；核对原 selection 与 plan 的持久化 run/SHA/receipt；再取得实际进程 identity、scheduler trigger、API 与页面对同一产品的读回。事后恢复保留回看属性，历史 backfill 不转成 formal/natural。H 的原阶段为 STAGE_0935_0940，早于阶段截止的计划不能冒充该阶段完成结果。没有上述实机证据，本次整体实际日常验收仍未通过。

## 通用复跑

交付 `scripts/` 中的 7 个 Python 文件保持在同一目录；在安装 pandas 和 pyarrow 的 Python 环境运行主矩阵。路径全部可传，不需要修改 candidate：

```sh
python run_independent_hk_o_r2_review.py \
  --candidate /path/to/candidate \
  --execution-source /path/to/verified/execution_evidence.py \
  --reference-sidecar /path/to/verified/hk_daily_supplement.py \
  --output-dir /path/to/review-output
```

execution 与 reference 均按上述完整 SHA 固定检查。输出目录必须在 candidate 之外。该命令运行 5 个独立 probe、核对关键源与脚本前后 SHA、写入紧凑 JSON，并清理临时 stores。具体本次命令与环境路径已保存在总账，不要求交付包包含临时 stores 或本机虚拟环境。

原 O owner 保存追溯可独立复跑，应用依赖以 candidate 的现有测试环境为准（本次 Python 3.14.6，已运行真实 FastAPI TestClient）：

```sh
python repro_original_o_owner_save_trace_r2.py /path/to/candidate \
  --execution-source /path/to/verified/execution_evidence.py \
  --output-dir /path/to/review-output
```

`verified_references/` 只包含本测试固定 SHA 的 execution 原文和此前 final_20261010 sidecar 对照原文；其来源与角色写入 trace manifest，不是部署 baseline。交付目录不包含临时 stores。
