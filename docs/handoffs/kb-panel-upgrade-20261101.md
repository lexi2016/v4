# 单股 KB 展示与面板增量交接

基线 commit：`69d31e8971f38a00b4e76f84c48b45f08a3e4cb2`。本分支保留已确认的 57 个 A 股 KB 字段及 QFQ 权威路径的日更适配；非 A 行保留 null。`kb_rebuild` 因上游仅以 5/10 日数据计算 MA14/28/57/114 黄线而标记 `SOURCE_IMPLEMENTATION_DEFECT` 并输出 null，不能将上游默认 false 当作否定结果。固定上游检测函数没有修改。

已验单股范围为 `002865.SZ`，来源 2026-10-30，观察 2026-11-02，2,311 个历史日期。原 172 条候选、旧式买卖点和两张全局面板指针保留。单股绑定只用于研究，不能代替全市场面板或日更验收。全历史成对候选、日更追加/修订回放和自然时段均未完成本批验收；无消费者删除清单仍为空。

2026-11-01 已在本机既有 V4 API 中激活指定单股展示，activation receipt SHA-256 `a31807ca1cc7cdf38df26439ec7188fb50ee364f50013ec5c9b2616f66eb30a5`；单股 API、日期及原候选数量已回读。此状态仅说明本次本地展示接入，不代表权威面板或自然日更已切换。

`ops/research_panel_qfq.py`、`ops/research_panel_factor_cache.py`、`ops/kb_signal_authority.py` 和 `contracts/a_share_kb_fields_v1.json` 构成面板计算与身份绑定。源重定位仅接受明示、SHA 绑定的隔离只读引用，未改写原目录、原指针或归档。`infrastructure/research_workbench_host.py` 和 `research-panel/` 中提交的文件是基于现役字节恢复的工作台显示来源；`ops/junda_single_release.py` 是只针对本批单股展示的受控本地 operator，需实际可用的冻结 stage、原始来源回执和共享锁，不能作为通用发布器。

下列现役依赖未包含在原始基线 commit，本分支仅恢复精确字节：

- `ops/vendor/data_layer_daily_formula_increment_update_v1.py`：SHA-256 `1b5f4caa099add5f0c369b72e0c6b9d8d80c964fe245a662290971e5142dcdae`。
- `components/a_formula/build_canonical_formula_research_panel.py`：SHA-256 `074a038699eae84d093602ee6df551b5279368c5800ad78067902a496c990258`。
- `ops/research_panel_turnover.py`、`infrastructure/research_classification_view.py` 及 workbench 的既有静态模块由当前 owner 恢复，作为本批实现的运行依赖。

当前实际 V4 owner 的 `apps/api/v4_api/research_router.py` 注册了 workbench router；此分支的原始基线对应文件没有该注册，且没有实际 owner 的 `apps/api/v4_api/app.py`。因此本提交不是可单独重建现役 API 的完整 release：需要在后续集成中对齐该 owner 路由、其实际 V4 app 和既有构建路径，不能用旧 V35 builder 代替或覆盖其他 owner 的变更。本批隔离候选基于当时实际 API app 和静态根，通过完整 inventory/delta 证明保留其余文件。

定向检查：`tests/test_a_share_kb_fields.py` 7 项通过；`tests/test_junda_single_release.py` 10 项通过；此前 `tests/test_qfq_source_relocation.py`、`tests/test_workbench_single_stock_kb.py` 及单股浏览器/source gate 已按冻结身份验收。独立 Reviewer 仅对指定单股与本地受控切换范围给出 PASS；该结论不包含全市场、自然日更或独立复建。

任务执行、来源门禁和临时静态资产的完整回执保留在本地任务证据目录；原始行情、候选 Parquet、压缩视图、plist、SDK、运行环境和大日志不随源码提交。金融标记保持 `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。
