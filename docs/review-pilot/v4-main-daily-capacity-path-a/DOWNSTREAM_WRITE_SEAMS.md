# 下一有界批次：日产品 / Top200 写前上界的具体缺口

本表来自同一冻结 R4 源码，不是要求重建模型或历史行情。D20 行文件/Top200 的已观测大小只能衡量量级，不能当成未来输出上界。所有阶段继续使用同一不可递增 Claim、现有 producer 与 V4 Reader，不增加 producer、面板或手工逐日 proof。

| 原 owner / 真实边界 | 实际落盘 / 既有条件 | 写前可直接确定 | 仍需补的可执行约束 |
| --- | --- | --- | --- |
| `research_daily_product_parallel.initialize/checkpoint/run_pending` | spawn worker 调用 retained、history、daily row；parent 写 parallel_run/progress | 当前日期、选中代码、源 generation、namespace、每股 Reader bars 数；初始化参数可以传同一不可变计划 | parent 在 submit **前** 原子计入全部在途额度，future 成败/排空都归还槽位；child 禁止超每股总字节、文件数和单文件上界；父子输入/代码 SHA 相同 |
| `research_panel_daily_product.save/save_daily_stock_checkpoint`（50、833） | row、label lineage、metadata、index/event、event case；mac compress_row 转 `research_storage_compaction.publish_daily_row` | canonical raw 已在内存；目标/临时路径和 immutable existing 状态已知 | 精确 raw、4 KiB、替换临时并存计费；`publish_daily_row` 的原始临时+压缩临时峰值均纳入；不能只量最终压缩大小 |
| `research_panel_history_checkpoint._publish/write_checkpoint/_retain_legacy_seed`（255、295、269） | delta/head/seed/checkpoint，原 `observe` 回调 | 每次 `_bytes` raw、upserts、removed、base_ref；旧 seed 的原字节身份与大小 | child 内的每次 `_publish` 必须先守卫；legacy seed/临时替换不能漏；历史 bootstrap 不得借此被允许 |
| `research_panel_chart_blocks.retain_owner_result`（98、130） | retained gzip 临时后替换；复用先验块 | gzip raw 在内存、history_blocks 清单、每股真实新增数；无整表副本 | 写前按精确 gzip 检查，覆盖 worker；不能被 capture 的 `except Exception` 转为“图件缺失”后继续 |
| `render_original_formula_projection.finalize_owner_charts`（278、291、353）及 `write_json`（239） | 一份共享 HTML、每股 spec/ready、manifest/receipt；当前 normal pending 为空，virtual projection，不写 PNG | 共享 HTML、spec/JSON raw 在内存；株数和每股 bar/drawing 数已知 | parent exact pre-write 守卫及 max_file/file_count；容量异常须越过 broad except，不能默记 OWNER_CHARTS_PARTIAL。`owner_pngs` 非日更路径，未证时在 browser/外部进程启动前拒绝，不能估 PNG 大小 |
| `materialize_workbench_score_action.project_symbol/save/materialize`（141、212、46） | worker `cachepath.write_bytes(raw)`；parent records/indexes | scope、输入prefix/规则SHA已知；缓存 gzip/raw 写前已完整生成 | process cache raw 的每股及在途额度；parent save 不在现 `product_write_seams` modules 列表；所有降级异常不得吞容量失败 |
| `complete_workbench_v192_assets.prepare_completed/attach/at_numeric_completion` | 调既有 owner.save 写模型视图/manifest，**不是模型训练或全模型复制** | 实际缺失 symbol/views；cache_identity；owner.save raw | 核完整调用与模块别名；证明复用已算结果，只补缺视图；父 phase 统一计费，容量异常不能转 `V192_ASSET_COMPLETION_FAILED` 后发布 |
| `build_mac_workbench.materialize_statistics`（181） | 仅有 `V4_WORKBENCH_STATISTICS_ROOT` 时；下层 write_json/页面资产 | 当前数值工件和目标路径；输出 buffer | 判定自然环境是否启用；开时计入 phase，关闭时绑定环境 SHA；不能换环境遗漏 |
| `research_panel_top200.prepare_incremental_history/run_incremental_history/_register_automatic`（296、370、344） | calendars/contracts、history label 增量、append 注册账本；调用原试验 owner | 当前日期/已接受标签/ref、真实新增日期、追加行 buffer；日产品 scope | 复用成熟标签；禁止日更全历史 bootstrap；动态加载原试验 writer 的 serializer、append fsync 和任何临时输出纳入同一门禁 |
| `research_panel_top200.build/stage/prepare_exact_metadata_row/prepare_current_history_view`（128、234、406、502） | metadata、staged index/event、immutable assets、公用 owner 发布 | 已取回官方行情/分类 refs、选中代码、staged raw 及文件映射；最多 Top200 输出不是选股输入截断 | 每次 immutable writer 与 stage/publish/rollback 的精确临时峰值；不是仅 build 边界 incoming=0；与完整候选输入 scope 绑定 |
| `research_panel_f10._write/complete_f10/publish_f10_completion`（83、253、330） | upstream source receipt、stocks/checkpoints/receipts、index/event CAS | 网络返回经原验证后、序列化 raw 写前可得；已知目标代码 | 在发起前设原有响应长度/项目数限额并审计；不能从历史 F10 体积猜未来；`_write` 当前不在 scoped product adapter modules 中。超限应中止并保存真实错误，不能把 partial success 当 bounded completion |
| `research_panel_top200.record_daily_attempt`（713） | attempts receipt、attempt index，使用 completion owner 锁 | 真实 attempt/owner ref 与 JSON raw | 对成功、失败与回滚回执保留固定有界槽位；不得在 claim 之外无计费直接写 |

最小后续方案：先把上述精确 serializer 的容量回调接到同一上下文，并让 spawn initializer 显式接收/核验计划；在提交前为每股预留经审查的槽位，写前按实际序列化 bytes 从槽位支出（含文件数和临时峰值），不追加 registry reservation。纯内存分类/计数可自动生成每日计划；只使用独审静态硬上界并由运行时执行。先用单个 append、因子修订和缺缓存三类代表覆盖父子写路径，再做受影响并发/故障/恢复验收。该批独审通过前，不填写生产 caps、不启用 delta、不执行切换。

实际正常写集还必须按最终 daemon 环境的 feature flags、source module SHA 和原试验动态调用闭合，不能仅凭此静态表声明“所有写者已覆盖”。
