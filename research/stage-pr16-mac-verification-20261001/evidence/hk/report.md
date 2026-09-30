# HK：只读取证补充（2026-09-28 至 2026-09-30）

**结论：补证确认两类相互独立的阻断；关键 source-capture 关系仍为 CANNOT_CONFIRM。** 该补充复用既有 HK stage 汇总及原链恢复结果，只核对 9/28–29 的 D-1/active-snapshot 时间证据和 9/30 sentinel 的上游身份链，没有重做全阶段扫描。所有引用原件的 SHA-256 都先对原字节计算；发布件只保留路径标识、SHA、时序/状态摘要，不携带原始行情行或完整代码清单。

## 9/28–29：D-1 ready，active snapshot 超过早盘 cutoff

两日 exact-date D-1 Top100 都是独立的 100 行 `STRICT_0_2_READY` 输入：9/28 pool SHA `0024b72d7122f2a44ff21483eddc3d1be5b771caa854d915e23ea507e5d1f60d`，producer run `20260928-hk-connect-d1-top100-0-2-ef16f451b21c`；9/29 pool SHA `d94eae4903aa09088f88d954d358869e7c1ac991782488ad62fd3bec40eeaaf3`，producer run `20260929-hk-connect-d1-top100-0-2-224afd3caf59`。D-1 输入仍按原合同保留；本补充没有删除或替换它。

9/28 `STAGE_0930_0935` receipt（SHA `940234713db706bf6d79fc764622090ffd9e58812152ef441b44393ed66d79f3`）记录 HK `CANNOT_CONFIRM`、`HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE`、100 个请求/返回行、cutoff `09:35:05`、active snapshot digest `a9ce78baf58a8744823eda648a726a1b577dbf6c8bb9a4c7a181db80cab8e2f4`，且 `active_snapshot_temporal_cutoff_safe=false`。但该 receipt 没有 attempt event 文件、没有 `pre_captures`，也未带原 snapshot 字节、捕获时间或 producer/source-capture manifest；因此不能把这条 snapshot digest 绑定到 cutoff 前的原 owner capture，也不能从现有 receipt 还原精确晚到时间。

9/29 receipt（SHA `9b7f995df07eab960ed70aa0a1bbd25f1102ab9220897dd339a2e4dd444def54`）关联 stage attempt `e7ac60e201f243088ddd601467ee0b8b`。保存的 `002_HK_SNAPSHOT.json` SHA `1bdec5dc4e63d5cd7df3cff32f8bf07968dabf406045bf25c76f5ddd2ad61710` 记录 gate cutoff `09:35:05`，但实际 fetch 在 `15:02:19.095579` 至 `15:02:20.411968` 才发生；100 个 row timestamp 范围为 `14:49:15` 至 `15:02:19`。这份 Stage 诊断快照明确晚于早盘 cutoff，不能用于早盘选择，也不是 cutoff 前的原始 capture。

原链只找到一份 9/28 same-capture 日线原件：manifest SHA `e5970ec3d1d74cdff04298a8319757227dad302f8fa58bcb9e17f7c05d733695`、raw SHA `b6486574db5af2a2a74efe338cdec752c97328ee96774ce72c132047670fbf30`，manifest 标为 `READY`，687 daily rows/694 security-master rows，capture SHA `08e4044c079b395a602db01c614a4f06aa7ca7e0923eeb0884103fde7e21cd1d`。它属于 target date 9/28 的日线 capture；row schema 没有 active snapshot `update_time`，Stage receipt 也没有引用其 capture SHA，因此它不能证明 9/28 的 active snapshot 身份，更不能替代 9/29 早盘数据。原链记录 `same_capture_29=not found in checked authoritative paths`。

## 9/30：strict D-1 invalid sentinel 与三次 source-workload retry

9/30 exact D-1 pool 文件 SHA `972643a7a0ccc91d64681f5a62ac0cb8bd8940c2e3fc7b0a1ebc4370f29288df`，586 bytes、0 rows，状态 `CANNOT_CONFIRM`，`source_role=EXPECTED_MISSING`，`producer_id=graph_expected_missing_v1`，没有 `source_run_id` 或 source path，`source_sha256` 是空内容 SHA `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`。其错误指向 signal date 9/29 的 HK security-master metadata 无效。Stage 9/30 receipt SHA `08320ece4b0c0916b889a0b82097d3680293ef8faf99cb8723f12c597b26ed32` 的 HK 仍为 `CANNOT_CONFIRM`；attempt `5cd40470268f42078c8ae0f2854159a1` 记录零个 HK snapshot events、`NOT_OBSERVED` row evidence。

9/29 原链目录有三份 17:20 `research_panel_daily_hk` dispatcher retry receipt。它们都以 `UPSTREAM_NOT_READY`/exit 124 结束，dispatch attempt 本身并非已完成的 capture，也没有成功 source manifest：

| attempt | dispatcher run id | receipt SHA-256 | 完成时间（UTC） |
|---:|---|---|---|
| 1 | `d45d29c6c6d64a1aa73c277f3790da0d` | `5f7790d0ace78274df9e8b34145e6e47729185fd2b29bfac8e59cc480963478f` | 10:44:00Z |
| 2 | `144722afadea45f6bc1e4a0ffce0781f` | `dd90e5ebedb05d6d6c0176c2389ccc17433d1c301861721cf06ebd083abe526f` | 13:19:00Z |
| 3 | `c8367bd4cbbc458bbc1af61c980661aa` | `cad3f9995a18b18668c214d5a2f69a8fded44094bffb51733368cb3f2ec111dd` | 15:51:00Z |

既有 diagnosis receipt（SHA `c9d3b627e42fe38b9cd7eea58894a324d6bd417c002c5fafe49a128cc9390ca0`）记录三次 OpenD 连接拒绝发生在生成完整 9/29 same-capture raw file 之前，并明确 `same_capture_29=not found in checked authoritative paths`。但 9/30 sentinel 没有 run id/manifest 将其自身绑定到这三份 dispatcher receipts；因此“这三个 retry 是上游故障证据”可确认，“它们就是该 sentinel 的 source capture identities”不能确认。

原 owner 有一份独立的 9/30 current-quote canary：receipt SHA `d8e369590ccccd184a22ad3d83aa8d031fd9e39e74983dbf35e38e162d8b1ebb` 标记 `CANARY_PASS`，原入口 `ops.macos_research_panel_daily.collect_hk_futu_rows`，运行 owner release 路径 `com.lexi.v35.local/releases/20260929-manager-1555-pytdx-r1/app`，并记录三份 owner 源文件 SHA。该 canary 的 manifest/raw SHA 分别为 `69e989d4e39bc5693d0b8884426b7af06aa9f83b0ca5904eedc6c77a29f79469` / `5bd301078adb4541861f5ca0aae67be1444b13102ad8560a4d8354ddf7c9b3e4`，目标日是 9/30，snapshot 时间汇总为 09:20:15–12:00:00。它证明原 owner 在 9/30 有一条自身绑定的 capture 供给；它不绑定 9/29 same-capture、三个失败 retry 或 9/30 strict-D1 sentinel，不能用来补回 signal date 9/29 的缺失来源。

## 尚缺的最小原件

- 9/28 active snapshot 的原始 snapshot/source-capture artifact、捕获时间和与 active snapshot SHA `a9ce78…` 的 owner/run/manifest 绑定。
- 9/29 cutoff 前的原始 active snapshot/capture artifact，以及可将其绑定到当日 owner、请求代码摘要和 Stage 输入的 receipt/manifest。当前唯一保存的 Stage snapshot 是 15:02 的迟到诊断。
- 9/29 security-master 的原始 same-capture artifact 与 owner manifest，使 9/30 invalid sentinel 能通过 source run/manifest 直接连回供给。三条 dispatcher receipts 只有失败 workload identity，不等于 capture artifacts。

本批未删 D-1 校验、未用午间/9/30 current snapshot代替上午输入，未将 64 digest/3 sample 视为全量，未导出 quote rows，未运行 producer/collector/Stage、服务或测试。三日期段仍是分别记录的证据状态，不推断 HK 全局失败或修复。

机器可读 receipt：[`receipt.json`](receipt.json)。
