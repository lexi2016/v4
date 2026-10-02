# C：目标日 HK Connect V2 qualification 当前精确缺口

固定反馈：`660e1e8e97027f70865d2df84ccf132c90c8c278`。本文件只解释为什么本轮不能诚实提交 V2 publisher patch；不改 Manager reader、不改日线、不新增 producer。

## 已确认现有链

1. 活动 `v35_dispatcher.research_panel_daily_hk` 已注册并有完整本机 binding。
2. 当前活动 collector `ops/macos_research_panel_daily_collectors.py` 调用 Futu 两个 plate，再采 exact-date market snapshot；持久化的是 v1 capture / 行情 rows / security-master rows。
3. `macos_research_panel_daily_gate.py` 在 panel authority 后调用 `ensure_hk_security_master`；当前返回路径没有 target-date V2 authority publisher。
4. pinned `stage_center/hk_universe_preflight.py` 已包含两个 V2 纯函数：
   - `validate_captured_hk_connect_membership_v2`
   - `build_captured_hk_connect_authority_v2`
   但后者只生成 bytes/payload，没有把 V2 artifact/capture/manifest/receipt/current/publication 原子发布到 store。
5. Manager consumer 的 `require_v2=True` 保持不动。

## 为什么不能把当前 v1 capture 直接喂给 V2 builder

V2 validator 明确要求：
- `schema_version=v4.manager_hk_connect_capture.v2`
- 两个完整 `plate_responses`，每个都保留 columns、原始 rows、requested_at、completed_at、row_count、response_sha256；
- `producer_owner.workload_id=v35_dispatcher.research_panel_daily_hk`
- `producer_owner.code_ref=ops/_macos_research_panel_daily_parts/hk_market_capture.py`
- 对应 `code_sha256`
- 完整 `forward_source_set` 及其 SHA；
- 从 plate frame 重新推导的 union、overlap、source SHA、capture SHA。

当前实际 collector 在循环内把 plate frame 立即折叠进 `universe`，持久化产物没有保留上述两个完整 frame 和其时间/response SHA。因此不能从 689 行价格、696 行 security master、D-1 码表或现有 v1 capture 事后补造 V2。

## 仓库历史核对

在 `codex/stage-regression-origin-20260930` 找到已有路径：
`ops/_macos_research_panel_daily_parts/hk_market_capture.py`（Git blob `97e4915cbc63d52ad4004b93d86616ec804ec267`）。

但该文件自述为 review candidate，且不包含 `producer_owner`、`plate_responses`、`forward_source_set` 或 V2 membership-source 逻辑。它不能当成 pinned V2 validator 所要求的现役 producer 源字节。

## 一次性精确缺输入

要继续实现**原 owner 的最小 V2 发布连接**，只需要补齐下面两类输入，不需要再给日线或 Manager 全工程：

1. **实际 V2 producer 源文件**  
   `ops/_macos_research_panel_daily_parts/hk_market_capture.py` 的最终/现役候选字节，以及它应绑定的 SHA256。理由：pinned V2 validator 把这个 exact code_ref 写进 producer contract，当前 8 文件包没有该版本。

2. **producer provenance 的 7 个原值**，或生成这些值的既有正式 receipt/manifest 文件：
   - `source_head`（40 hex）
   - `forward_receipt_sha256`
   - `candidate_manifest_sha256`
   - `candidate_build_receipt_sha256`
   - `api_writer_receipt_sha256`
   - `api_reviewer_receipt_sha256`
   - `api_source_mapping_sha256`

没有这些值时，任何所谓 `producer_owner` 都只能是编造，V2 validator 也应拒绝。

另外，pinned builder 定义了 `HK_CONNECT_PUBLICATION_SCHEMA_V2` 与 `publication_relative`，但本文件末尾没有生成 `publication_bytes` 或发布函数。若上述实际 V2 producer 文件并不自带 publisher，则还需**唯一一个**现有 publisher/source file（实际负责原子写 `artifact/capture/manifest/receipt/current/publication`）的字节；若 producer 文件本身已经承担发布，则不再额外要文件。

## 停止规则

在上述输入补齐前：
- 不执行 `research_panel_daily_hk` 来“碰运气”生成资格文件；
- 不修改 `read_universe_evidence` / Manager `require_v2`；
- 不用 security master、价格有效 689、D-1 696 手拼 target V2；
- 不 backdate acquisition/publication clock；
- C 状态固定为 `EXISTING_V2_BUILDER_FOUND / PRODUCER_PROVENANCE_AND_PUBLISHER_INPUT_INCOMPLETE`。
