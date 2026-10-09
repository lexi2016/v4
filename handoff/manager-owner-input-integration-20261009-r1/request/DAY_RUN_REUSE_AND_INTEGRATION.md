# 单日 owner 链路复用与 workbench 集成说明

## 先分清三组日期证据

用户报告 2026-09-30 曾通过一个单日入口跑通 announcement selection、美股映射与超跌选股。当前限定复核到的 2026-09-30 manager workspace 记录不能证实这三个通道曾在同一个完整计划中成功，也不能否定一个单独 owner 入口曾经成功；独立入口/receipt 在本次限定证据范围内 NOT_FOUND，最终结论仍是 CANNOT_CONFIRM。

在可读到的 2026-09-30 workspace 运行中，09:53 手动计划 run f0db65a25bb340b584682542b8d597b8 是 PARTIAL：US attention 为 READY，期望美股 session=20260929，范围是 24 个 industry proxy rows + 33 个 configured US symbols（明确不是 full US market）；announcement 是 NOT_RUN，screen 是 CANNOT_CONFIRM，plan stocks=0。其它 3 个同日 workspace plan 也为 PARTIAL。后续 R2 对 09/30 保存 product 的 GET 因 read_contract_sha256 与当前 contract identity 不同而返回 HISTORY_READER_VERSION_CHANGED；该历史 reader fingerprint rejection 不证明原 owner run 失败，旧 product 仍被保存。

另一个已证明的子链是 2026-10-07 publication 到 2026-10-08 workspace 的 announcement。R1 live API readback 于 2026-10-08 12:30Z 记录 source_run_id=6730f3cf34c8480d86fa229df5aa4019、evidence_run_id=3f9d37a643060b57992167f3df05d987，analysis status/validation=VERIFIED，529 个分析 universe rows、33 selected、54 conditional watch、367 not selected、75 not assessed；workbench product status=CONSUMED，cutoff status=SATISFIED。但 Announcement daily channel 本身仍为 PARTIAL（33 candidate、54 watch、75 pending），HK_CONNECT 与 OVERSOLD 是 CANNOT_CONFIRM，plan NOT_MATERIALIZED，natural_run_verified=false。它证明现有 announcement owner 产物可以被消费，不证明三通道完整运行，也不是 09/30 的 receipt。

2026-10-09 isolated original-owner run 是可以复用的调用/产品契约参考，但它也是 partial：mapping run a95450cd4b264fb6840308d7d2681cf6 为 VALID_EMPTY，reviewed 4/33，full_market_coverage=false；同根 plan run dba211c2677045afb4e0ef8c990367ee 为 PARTIAL、0 stocks。Announcement 10/09 原始 capture/Reader/Reviewer 未运行，HK exact-date screen CANNOT_CONFIRM。因此不能把这组 10/09 replay 冒充用户所指的 09/30 成功 run。

上述三个时间点的元数据投影在 evidence/ 内；原始 payload 和股票行没有复制到包里。

## 可复用的调用顺序和接口

下面对应包内 original-owner runner 的实际调用逻辑。root 用环境参数表示；Chat 看接口，不能拿这个离线片段宣称重复执行了真实数据。完整、未改动的 10/09 runner 和 reviewer checker 快照在 code/actual_owner_runner_20261009/，每个文件的原 SHA 在 SOURCE_SNAPSHOT_MANIFEST.json。

~~~python
# A. 先校验同一日期所用输入 payload + receipt 的 SHA，再用原 owner 执行 mapping。
reader = ResearchPeripheralUsMarketReader(data_root)
owner = ManagerResearchJobService(
    ManagerResearchStore(manager_state_root), None, None,
    workspace_us_market_reader=reader,
)
mapping = owner.refresh_us_mapping_research(
    "20261009",
    now=started_at,
    execution_context={"trigger_kind": "MANUAL", "timing": "LATE_CATCHUP"},
)

# B. 保持同一个 owner / manager store / reader，把真实的 owner product 引用给计划刷新。
plan = owner.refresh_workspace_plan(
    "20261009",
    execution_kind="MANUAL_REFRESH",
    now=started_at,
    execution_context={"trigger_kind": "MANUAL", "timing": "LATE_CATCHUP"},
    workspace_date_bindings={
        "selection_date": "20261009",
        "announcement_date": "20261008",
    },
)
~~~

原实际 mapping reader lineage 指向 external_finance payload、独立 receipt、manifest 和 source identity；具体输入 SHA 在原 receipt 中留存，但本包只保留 reader lineage 摘要，不复制行情 payload。owner 写出的 mapping product 至少包含 target_trade_date、run_id、generated_at、status、artifact_sha256、coverage、matches、gaps、source_identity 与 safety flags。必须按 full_market_coverage、configured/available/reviewed counts 和 PIT/cutoff 评估空结果；0 matches 本身不能证明全市场有效空。

原 plan 会引用 US mapping run/artifact SHA 和输入 identity，并保存 owner attempt 与 product。workspace GET 是读取和校验，不是 owner 调度器：GET /api/v4/manager/research/workspace?date=... 最终通过 create_app 注入的服务 reader 汇总已保存 channels/plan，不应在 GET 里新增抓取、刷新或绕过原 owner。

Announcement 的复用接口见下节。HK Connect 和 oversold 保持各自已存在 source owner、date/root/manifest/readers；US_MAPPING 或公告分析不能替代它们。

## Announcement 原 owner 到 workspace consumer

10/09 原 owner handoff 明确依赖四件独立工件：精确日期 catalog read、已捕获 body corpus、实际 Reader 输出、身份不同的实际独立 Reviewer 输出。原 runner 子命令只提供原 owner 既有流程：

1. prepare 用 target_date 与 publication_date 加载并校验 catalog、semantic catalog 和 body corpus；不进行 review 或写出业务产品。
2. register-handoff 以真实 capture/evidence run id、实际 Reader 和 Reviewer 输出及不同身份校验日期与 SHA，然后写 handoff。
3. import 用 owner API 导入该 evidence run；readback 按同一目标日回读。
4. capture 是 side-effecting catalog/body capture 命令，不能由 Chat 自行替代原 owner。本次 10/09 没有发起 capture，也无 actual Reader/Reviewer 输出。

以上步骤和必需参数对应 code/r3_20260930_reference/v4/manager_research/announcement_autorun.py、announcement_source.py、workspace_announcements.py、announcement_materials.py 以及 runner source；2026-10-07→10-08 可消费 publication 的确切消费者版本在 code/r1_20261007_announcement_consumer/，固定 R2 消费端在 code/r2_chat_patch_target/v4/manager_research/workspace_announcements.py 与 announcement_analysis.py。source SHA 以清单为准。Chat 应沿 source/catalog → capture evidence → Reader/Reviewer → handoff/import → workspace reader → plan identity 查差异，保持已有 owner 的输入合同；不得从零造分析器、重抓相同来源或伪造 review。

## 交给 Chat 与 Mac 的边界

Chat 可以读取包内 R3/R1/R2 代码快照、四问题矩阵和离线接口 fixture，提出最小 R2 consumer/wiring 修复及回归测试；没有本地 owner state 时，不得宣称已接入真实日数据、复现 09/30 run、跑完 owner、部署、API/UI 或自然时段成功。

Mac 侧拿到 Chat 的差异后，在授权的 V4 源码树里由原 owner 执行需要的日期任务：确认实际 source/root/manifest/SHA、日期 pair、run id、cutoff 和 Reader/Reviewer identity；调用原公告 capture/review/import、HK universe/security-master/panel 与 US mapping 的现有 owner；将原产品挂入 plan；最后通过实际 create_app 注入读取器进行只读 GET readback。结果可为 verified selected rows 或 coverage-backed valid empty；缺来源、缺 exact-date key 或输入 identity 变化时继续显示 CANNOT_CONFIRM/PARTIAL/STALE_INPUTS_CHANGED。不要把 code review 或 synthetic smoke 当作产品行为或自然运行验收。

## 精确源码根与方法锚点

- 2026-09-30 参考代码根来自旧 input-readiness receipt 明确列出的 pinned contract owner root：/Users/lexi/Desktop/学习/agents调试/MANAGER_R3_BUSINESS_FIX_20260930/r3a/build/r3a-r9-import-closure-20260930T193024Z/app。该快照的 workspace.py SHA-256 35c9292d3b422c9d5a744590cc472de5bfa2da8a62d12c6382ca0d1a9b3a6168，在约 435–460 行把现有精确 session US reader 接到 us_market_attention；us_market_bridge.py SHA-256 46fcf3fce15dfce4ae45e8eefe2c9b619d884f602d4f5b4261f163755debf0ae，project_us_market 从 cutoff 推导 session、读 existing exact-session peripheral store，验证 lineage/schema/session/capture time/safety。workspace_plan.py SHA-256 0721e90fcc5c261545a23e1aca1545b48077956a312a3c4cfe703f11aa4023f9，read_rebound_screen 从 security-master/panel authority 读 oversold screen。保存的 09:53 run 只证明 us_market_attention READY 的 24 proxy + 33 configured scope，不证明 09/30 announcement、HK oversold 或完整 mapping 成功，也没有 receipt 把此 R3 snapshot 的 bytes 绑定到实际运行进程。

- 2026-10-07 announcement consumer 的 source identity 根是 /Users/lexi/Library/Application Support/com.lexi.v4.local/releases/manager-workbench-r1-mac-20261008-api/app，release-manifest SHA-256 d125d33b8c8a5cae6edead79cb756b671baf07a79ddc0653c2884800a7eafb49。announcement_analysis.py SHA-256 b60b8c0c663b203d2ece5a5b451eb41ca296396b2db3630dff4a92a8566f373f，build_product 从真实 Reader/catalog/body inputs 建产品，import_product 从约 1102 行进入现有 consumer；workspace_announcements.py SHA-256 ea259666727b71c78760d666f3fe7f90350829bdce5f2b55745927528546af04，read_analysis_consumption 约 2264 行验证 target/publication、product/manifest/receipt/hash 并投影 schema v4.manager_research.announcement_analysis_consumption.v1。实时读取的 metadata 证明 10/07 publication/10/08 selection 由该 release 消费；它不是 09/30 运行证据。实际代码和逐文件 SHA 在 package/code/r1_20261007_announcement_consumer/。

- 可操作的原 owner announcement CLI contract 随包一并提供：original_r3_business_source/ops/run_manager_daily_announcement.py 的源 SHA-256 bfb853fb982e0b2da1024fa942ae9dc5d67fa88a8d112f46054608641129c1ee（文件在 package/code/actual_owner_runner_20261009/ops/）。prepare/register-handoff/import/readback 是原 runner subcommands；capture 会访问源并 side-effecting，本次没有运行。函数锚点约为 _import 436 行、_register_handoff 481 行、_readback 629 行，命令绑定 659–702 行。它给 Mac owner 调用既有合同，不给 Chat 创造或冒充本地 Reader/Reviewer 运行的权限。

完整 source/app roots 与 caveat 写入 SOURCE_SNAPSHOT_MANIFEST.json。对应历史记录仍是 CANNOT_CONFIRM：user 所指独立 2026-09-30 runner/receipt 在本次限定目录内未找到；不据此否定用户报告。

- 10/09 actual owner run 所使用的 original_r3_business_source 是另一份精确基线，根为 /Users/lexi/Desktop/学习/agents调试/V4_MANAGER_REAL_RESULT_RECOVERY_20261009/candidate/original_r3_business_source。包内 actual_owner_runner_20261009/source/ 包含实际调用的 service.py、us_mapping_research.py、us_market_bridge.py、workspace_plan.py、workspace.py、store.py 与 research_peripheral_store.py；请以 manifest 的独立 SHA 对比，不要把它和 09/30 pinned R3 source snapshot 或当前 R2 candidate 混成一版。
