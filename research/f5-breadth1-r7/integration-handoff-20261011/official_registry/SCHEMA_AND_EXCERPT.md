# 官方注册表字段与本包事件摘录

`OFFICIAL_REGISTRY_RELEVANT_EVENTS.jsonl` 保留原始逐行字节，但仅包含当前 route 下三个精确 execution_id：R7 真实 admission action、只读 probe 01、只读 probe 02。不存在 probe 03 RUN_STARTED；该状态在 `REGISTRY_SNAPSHOT.json` 和 `probe_03_contract_only/PREPARATION_STATUS.json` 中记录。

Event JSONL 的机器验证/追加实现随包提供：`registry_adapter.py`、`execution_guard_core.py`、`build_experiment_registry_backfill_20260821.py`、`validate_experiment_registry_append_compatibility_v1.py`。关键字段包括 `execution_id`、`route_id`、`event_type`、`event_sha256`、`previous_event_sha256`、`budget_action_key`、`budget_action_debit`、`deterministic_metrics`、`truth_access`、`research_only`、`production_allowed`、`buy_gate_updated`、`orders_sent`。记录摘要仅用于交接导航，不替代官方 adapter/validator。
