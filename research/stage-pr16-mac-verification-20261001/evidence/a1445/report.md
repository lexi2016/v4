# A1445：2026-09-30 14:00 source/archive 投影见证

**结论：字段级重建已完成，确认 source/archive 投影仍不一致。** 现有只读取证脚本和 witness 的 SHA 相互匹配；本补充只核对并解释中断产物，没有重跑 Stage、collector 或 producer，也没有复制 source/archive 原件。

指定输入身份为 source 原字节 SHA `4076de79920c43cfa57336c23262a491cd77730f29b4e1a530bc5ed9836ef571` 和 archive stored-payload SHA `811b7803b540ec22c8e3f061804229e59fa51179f20a55a56ccc12d946af4af0`。原始文件仍在研究数据根；witness 只保留原件路径、长度、SHA、投影摘要与脱敏字段差异，不包含行情全文或 202 行 raw。

Stage cutoff 是 15:00:00（Asia/Shanghai）。原 reader 按原顺序选取 `1400`，其 archive `source_generated_at=14:12:03`；`1500` archive 时间为 15:00:02，晚于 cutoff，已被 PIT reader 拒绝。来源 manifest 同时记录 `pit_cutoff=14:00:59`、`capture_origin=LATE_RECOVERY`、`original_time_capture=false`。因此该见证证明的是 Stage 截止时间下的 slot 选择和投影差异，不证明该来源是原时段采集。

Archive 的 stored-payload SHA 合同是对解析后的 payload 使用 `infrastructure.data_store._canonical_bytes` 生成 canonical JSON bytes 后计算 SHA-256：`ensure_ascii=False`、键排序、紧凑分隔符、UTF-8、无末尾换行。该例中原 JSON 文件本身也是相同 canonical bytes，因此 raw-file SHA 与 stored-payload SHA 数值碰巧相同；这不是两种合同普遍相等的保证。Source raw SHA 则对原字节计算；消费者使用 `utf-8-sig` 解码。来源 manifest 未声明 source serializer/newline 合同。

按实际消费者顺序重建：`_verified_hourly_slot` → `_bound_source_rows` → `build_research_archive` → 2026-09-29 专用兼容 helper → `_payload_base_sha`。该 helper 的 source guard 期待 `506c947cad54071a286853df20afc74e10bb544b2b639fea1ea7a443216bc3fc`，本次 source 为 `4076de79920c43cfa57336c23262a491cd77730f29b4e1a530bc5ed9836ef571`，所以它是 no-op；没有删除 warning、改数组次序或泛化该 helper。

比较前仅尝试移除 `stage_evidence_v1`。Archive 和重建投影均没有这个字段，所以这一步没有改变比较输入。完整比较有 27 个 JSON Pointer 差异，均落在 `/cannot_confirm/1` 至 `/cannot_confirm/27`：archive 一侧是 36 字符字符串，重建一侧为 `MISSING`。机器可读 witness 对每条差异保留双方类型、长度、完整值及 canonical 摘要；未压缩或重排 warning 数组。原绑定校验仍报 `RESEARCH_SOURCE_WITNESS_INVALID:SOURCE_ARCHIVE_PROJECTION_SHA_MISMATCH`。

Canonical 摘要：source 原字节 982,826 bytes，canonical 804,617 bytes，SHA `34994edb74908dfa2dfaa0c49b442e0249fa021cd862e0dd5f7f18a90105d643`。Archive 完整 canonical 151,554 bytes，SHA `811b7803b540ec22c8e3f061804229e59fa51179f20a55a56ccc12d946af4af0`；移除不存在的 `stage_evidence_v1` 后仍相同。重建投影 canonical 150,501 bytes，SHA `f316026fd7177d441e5d4abcc4b95f0e60f09007f4a7d1758989abf13b318ed7`。

来源 manifest 声明 producer `ops.collect_hourly_research_input`、module path `v3.5/domains/research_hourly`、oracle SHA `850fffdf16b7c0127852cbe9cc374aed353e8d7cb1c2ba73d2eff880c95d022e`，并有 collector/domain identity SHA；这些是 manifest 声明。witness 对当前候选的六个参与模块记录了磁盘 SHA，但实际 2026-09-30 Stage 进程加载的模块和原 producer 字节仍为 `CANNOT_CONFIRM`。真实进程加载证据缺失时，不把磁盘文件 SHA 升格为运行时绑定。

完整 witness：[`a1445_20260930_1400_projection_witness.json`](a1445_20260930_1400_projection_witness.json)，SHA-256 `78ffc95f3ae7b6e0f69730796be69d9a4f3e1a294838b7873dbd5825908d3003`；生成脚本 SHA-256 `2c68bd11db32a24230a8a37bf5bbfbd48b7b20ea4151c006f12dc8284d306f00`。机器可读补充收据见 [`receipt.json`](receipt.json)。本批未修改业务代码，未运行测试或生产操作。



本次核实了此前一次 pin 转录错误：错误尝试使用 811b7803b540ec22e8c3f061804229e59fa51179f20a55a56ccc12d946af4af0，在 stored payload canonical SHA 校验处退出 1，未写出 witness。恢复原始 pin 811b7803b540ec22c8e3f061804229e59fa51179f20a55a56ccc12d946af4af0 后，原命令只读重建退出 0；source、archive raw/canonical SHA、receipt 与 manifest 绑定均通过，witness 仍记录 27 个字段差异。两次命令的 argv、exit code、stdout、stderr 机器记录见 [command_runs.json](command_runs.json)，SHA-256 f1629ecc9e14c57a2283e6b34170a1057bc70cf8a11a2541fb85d4a50c441d77. 原独立审查收据保留在上级 review/ 目录，本补充不替代独立复核。

**仍为 CANNOT_CONFIRM：** 原 producer 实际执行字节/serializer；Stage 进程当时加载的实际模块 SHA；投影差异的生产修复与真实 Stage/API/UI 行为。该证据仅确认并定位差异，不声称修复已完成。
