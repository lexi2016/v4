# R2 独立 Reviewer 结论：PASS（仅冻结候选范围）

**Reviewer:** `/root/monthly_direction_review`  ·  **Writer:** `daily_chain_writer`  
**SCOPE SHA-256:** `db18939a6266b6e1bd1c4b230c458300cce522e5d462a73fa3a892cb77914eb7`  ·  **WRITER_R2_RECEIPT SHA-256:** `9f907a42952e93dae07e8207d79ad7c963a446022c9741c96399c165fd5fa71a`

## 结论

冻结 R2 变更审查通过，没有发现本批 P0、P1 或 P2 问题。此 PASS 仅覆盖候选源码、回归测试、保存输入重放和未激活 API/scheduler release；部署后 live API/UI、激活后的手动任务及自然时段仍由主控后续验收，当前为 `CANNOT_CONFIRM`。

真实保存输入重放通过：目标日 `20261020`、美股会话 `20261016`、港股通月度观察范围 `698` 只。`NativeAdapters → run_us_mapping → display_read.us_summary` 共读取 1,051 条输入记录，得到 1,761 条完整 lane 行（698 条行业观察、1,003 条 catalog observation），输出覆盖 698 只。上行/下行/零变动/待核为 `153 / 109 / 0 / 436`；所有方向行的身份、月度成员身份、会话与正负号逐行核验通过。月度成员来源日为 `20261012`，来源 SHA 为 `e908f19b…`; 目标期正式资格保持 `CANNOT_CONFIRM`，历史 PIT 为 `false`。

七个 Friday 代理主题的 quote 行使用引擎公式 `(last / previous_close - 1) * 100` 独立复算，结果与来源和引擎路径逐项相等；来源 owner 为 `research_peripheral.external_finance`，source SHA `bb79cb28…`。界面构建 JS/CSS/HTML 的 SHA 与 web build receipt 和 API candidate manifest 一致，目标 UI Vitest 通过。

## 验收证据

- 独立 Python engine/display 回归：`32 passed`。
- 月度成员边界回归：`8 passed, 28 deselected`。
- saved-lane UI Vitest：`1 passed, 2 skipped`。
- API 与 scheduler release manifest、应用 inventory、改动后文件 SHA 均与 build receipt 一致；非 delta 文件完全保留，staged plist 仅更新 release identity，schedule/config 未改，capture disabled，非生产安全标记保留。两个候选均为 `NOT_ACTIVATED`，live plist SHA 仍为基线。
- `ROOT_CODE_GITHUB_SYNC.json` 记录远端分支 `codex/monthly-membership-research-20261018`、commit `7487dc84445b0241fd7a37addcab0c9b0fb94be7`，已核验文件 `16` 项。

## 验证差异

当前 workspace 的三文件宽测为 `40 passed, 1 failed`。唯一失败是未改动的 `test_source_binding_carries_configured_quote_scope_and_proposal_sources`：当前 workspace 的 `ResearchPeripheralStore.publish` 在 `infrastructure/_research_peripheral_store_parts/market_validation.py:146` 拒绝 fixture 的 `47/49` 行却标为 `READY`，且发生在月度成员断言之前。该 fixture 的字节相同 pre-R1 测试在冻结基线 API release 上 `1 passed`；当前 `infrastructure/research_peripheral_store.py`、`ops/materialize_research_peripherals.py` 有本批外修改，`market_validation.py` 与 `ops/us_market_digest.py` 是本批外未跟踪文件。这不是冻结 R2 candidate delta 的回归；这些并行工作区文件是否属于其他验收范围，标为 `CANNOT_CONFIRM`。完整日志见 [pytest-broad-current.log](local_only/reviewer_r2/pytest-broad-current.log) 和 [pytest-pre-r1-baseline.log](local_only/reviewer_r2/pytest-pre-r1-baseline.log)。

## 仍未确认

- 候选当前尚未激活；部署后 live API/UI、激活后的手动运行和自然时段结果由主控后续验证。
- `20261012` 月度成员观察没有明确覆盖目标日的有效区间；不得提升为正式目标资格或 PIT 安全成员池。

结构化回执：[INDEPENDENT_REVIEW.json](INDEPENDENT_REVIEW.json)。
