# 20261008 港股阶段选股失败问题包

本包只交接 `STAGE_0930_0935` 的港股失败定位和可审查输入，未包含修复补丁、原始池行、股票名单、完整API响应或凭证。当前阶段状态仍为 `CANNOT_CONFIRM`。

## 已确认的失败链

2026-10-08的实际Stage由独立LaunchAgent `com.lexi.stage-center.scheduler` 负责。它当前未运行，launchd记录的最近退出码为3；实际入口是 `ops/run_stage_center_nodes.py`，工作目录指向 `~/Desktop/学习/agents调试/V4_HK_STAGE_RECOVERY_20261003/issue23_runner_helper_r3/stage_r1_binding_candidate_r3/app`，配置 `release_id=20261003-hk-binding-wrapper-r3`。配置把HK D1根目录设为 `~/Library/Application Support/com.lexi.v4.local/state/data`，把共享预选池来源根设为 `~/Library/Application Support/com.lexi.v35.local/state/data`。10/08主根的日期目录不存在，来源根的日期目录存在，因此现有日期owner解析到v3.5数据根下的 `preselection_pools/20261008/hkconnect_d1_top100.json`。完整路径和校验哈希见 `evidence/hk_d1_input_summary.json`。

实际Stage日历在launchd配置的V4 Python环境下解析出 `price_signal_date=20261007`、`eligibility_source_date=20260930`。被读取的共享池有100行，行级 `signal_date` 均为20260930；池文件没有 `historical_provenance` 对象。Stage回执的HK首个失败是 `HK D1 split-date eligibility provenance missing`，HK `selected_rows=0`、`write_performed=false`。缺少的是对两套日期来源的可追溯连接，不能从池的 `source_sha256` 推造资格来源哈希或采集时间。若只给池补一段provenance，当前同一校验后续还会遇到两项身份约束：每行 `signal_date` 必须为 `20261007`（现有行是20260930）；并且校验器把 `d1_source_manifest_sha256` / `d1_source_receipt_sha256` 与输入payload的同名字段比较，而实际池payload没有这两个顶层字段，虽然物理manifest/receipt文件的SHA已核验。候选必须把provenance绑定到resolver验证过的真实trio身份，并核实真实价格输入与Connect资格来源；不可改标日期或补入未经来源核验的字段。

API和Stage是两个不同owner。API LaunchAgent `com.lexi.v35.api-only` 当前在8873运行，工作目录是 `~/Library/Application Support/com.lexi.v4.local/releases/manager-daily-chain-20261008-r3-api/app`。对 `GET /api/v3/workbench/stage?date=20261008&stage=STAGE_0930_0935` 的一次只读请求返回HTTP 200，但整体 `PARTIAL_WITH_ROWS`；API的HK摘要只显示较粗的 `SELECTION_ARTIFACT_UNAVAILABLE_OR_INVALID`。实际Stage回执保留了精确的D1来源错误。API GET读取共享Stage selection状态，不证明Stage再次执行，也不证明页面已自然读回。打包时API PID为21204；先前交接记录的PID为1297，PID变化原因 `CANNOT_CONFIRM`。

## 源码和上次交付边界

`source/canonical/`保留当前V4源码，`source/actual_stage_owner/`保留launchd实际Stage目录中的对应文件，`source/api_runtime/`包含当前API入口和GET读路径摘录。Stage的 `hk_input_validation.py` 与当前V4源码SHA相同；`runner.py`、`slot_execution.py`、`preselection_pool_store.py`、`preselection_pool_sources.py` 和runner入口等文件存在版本差异，具体SHA在 `evidence/source_identity.json`。Chat应按实际Stage owner适配，不能仅修当前canonical文件后声称运行已恢复。

上一交付参考由用户提供：commit `4c9218789fe320dd42c1946e5dfb5161d8f8ed2a`，branch `codex/issue28-historical-p2-mac-20261008`；两项历史P2据报仅完成本机集成测试38/38、未部署。这些证据不代表本次拆分日期provenance问题已修复，也没有闭合当前Stage owner适配和运行发布链。

## 交给Chat时的目标

阅读 `PROMPT_FOR_CHAT.md` 后，先固定复现并核对本包证据，再产出可复核候选补丁、针对性回归测试、canonical与实际Stage owner适配差异，以及Mac最终验收步骤。保持 `production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。不得发明来源hash/采集时间、放松日期/池/来源门禁、使用latest或另建producer；任何来源缺口仍标 `CANNOT_CONFIRM`。本问题包不授权服务切换、部署、计划任务修改、数据写入或Git同步。

## 证据和验证状态

- `evidence/stage_receipt_summary.json` 和 `evidence/api_readback_summary.json` 是脱敏摘要；原始回执、池行和全响应没有复制。
- `tests/test_hk_prior_observation_source_binding.py` 是针对缺失拆分日期provenance的既有回归测试；本次打包未运行项目测试（`NOT_RUN`）。
- `publish_minimal_git_sync/` 是未修改源码与测试基线，不含补丁，便于Chat形成后续最小同步清单。
- `SHA256SUMS.txt` 列出本目录中除该checksum文件自身以外的每个文件；其自身SHA会随交付回执单独提供。外层ZIP会做完整性检查。
- `UI_VERIFIED`、`NATURAL_VERIFIED`、部署与实际修复均为 `CANNOT_CONFIRM` / `NOT_RUN`。
