# 交接：2026-10-12 下午港股通阶段选股与页面恢复

记录时间：2026-10-12 16:27，Asia/Shanghai。本文是未完成工作的交接，不是恢复成功报告。接手前核对实际运行身份；下面的运行状态最后核对于本轮，候选可能继续变化。

## 目标与用户决定

唯一目标：恢复当天 13:15、15:00、15:55 三个下午阶段的选股结果，确认实际页面有股票，然后结束本轮监控。

用户已明确：港股通使用富途；复用同一 D-1 固定池已抓齐的 100 只缓存，不再走 TDX、不重复抓取、不建第二 producer。验收通过直接恢复 13:15 并确认页面；其余阶段沿用原流程，有问题按已成功路径处理，不再复杂化。

本目标必要本地修复、研究服务重载与受控恢复已授权，无需再次询问泛化实施批准。仍须唯一 Luna Max Writer、不同身份的独立 Luna Max Reviewer；主控负责集成、运行、页面核验与 Git 同步，不写业务代码。

保持 `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。事后富途缓存只能作为观察数据：`temporal_cutoff_safe=false`、`execution_verified=false`、`NO_BUY`。不得改选股算法、池边界、模型门禁或把补跑标成自然验收。

## 实际完成与未完成

| 阶段 | 正式产物最后确认状态 | 缺口 |
| --- | --- | --- |
| `STAGE_1300_1315` | A 股 10 只保留；港股未恢复；原 TDX 失败累计 3/3 | 富途缓存已有 100 只；生产接线与严格一次新来源恢复尚未独立通过、未执行 |
| `STAGE_1445_1500` | A 股 10 只保留；港股未恢复；原 receipt 为 attempt 1/3 | 富途缓存已有 100 只；真实原 runner 隔离测试仍有 fixture 问题，未正式补跑 |
| `STAGE_1545_1555` | 已有 HK 10 只，run `run-a97bb6a8560dedce4e4a4679`；receipt 为 `RECOVERY`、`SETTLED` | API 保留行但将计数置空，页面未显示；不能称 `NATURAL_VERIFIED` |

13:15 原 A 股 run：`run-3b2d201a` 为先前记录的简称，接手应从下面正式 receipt 读完整 ID；不可用简称作为绑定。15:00 原 A 股完整 run：`run-6bb61f95527796da3cd57bd2`。两者已成功，恢复只处理缺失 HK，不重采 A、不替换其 run。

15:55 的原 Stage8 来源是 `FUTU_RTDATA_NATURAL`，实际消费活跃 D-1 交集 16 只，输出 10 只。该既有产物可用于本轮页面恢复；不得冒称它消费了 100 只，也不得为改写这个事实重新采集或扩大原 Stage8 池。

**当前不能报告 `DEPLOYED/API_VERIFIED/UI_VERIFIED/BEHAVIOR_VERIFIED` 的富途恢复成功。已抓到数据、孤立 selector 输出 10 只、手工 SourceResult 或 FakeOriginalRunner 测试，都不是生产链验收。**

## 当前正式入口与身份

- 唯一源码项目：`/Users/lexi/Desktop/学习/v4_app`。本仓库存在大量先前和并行修改，不可 reset、clean、无范围 add 或覆盖。
- 实际页面：`http://127.0.0.1:61796/?date=20261012&stage=STAGE_1300_1315`。
- 实际 API：`http://127.0.0.1:8873/api/v3/workbench/stage?date=20261012&stage=STAGE_1300_1315&limit=50`；61796 同路径由页面 gateway 转发。
- 正式 Stage app：`/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/afternoon-auto-stages-20261012-r1/app`。
- Stage 配置：上述 app 的 `stage_center_tick_config.json`。
- Stage 任务：`/Users/lexi/Library/LaunchAgents/com.lexi.stage-center.scheduler.plist`，`RunAtLoad=false`；原日程不改。
- 实际 API app：`/Users/lexi/Desktop/学习/agents调试/V4_HKEX_DIRECT_PREOPEN_20261012_R1/integration/minimal-api-owner-r3/app`。保留并行 HKEX 修改，不用旧 r6 API 快照替代。
- API 任务：`/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist`，`KeepAlive=true`。后续重载前再次核对当前 PID、cwd、plist 与 manifest，避免覆盖其他交付。
- 配置 Python：`/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python`。
- 正式 raw/selection/receipt 根：`/Users/lexi/Library/Application Support/com.lexi.v4.local/state/stage/{raw,selection,receipts}`。

已准备的 `afternoon-futu100-20261012-r3` Stage 和同名 API 候选 **未激活且已过期**。R3 只包含旧 frozen15_r1 的部分文件，漏了实际缓存 adapter/wrapper，不能直接启用或执行原 CLI。

## 已有富途数据与证据

证据根：`/Users/lexi/Desktop/学习/agents调试/V4_AFTERNOON_AUTO_STAGES_20261012/futu`。以下数据只存本地，不上传 GitHub。

| 数据集 | 内容 | SHA256 |
| --- | --- | --- |
| `rt_data_fixedpool100_dataset_20261012.json` | 13:15 固定池 100 只；每只 14 个 13:01–13:14 分时点 | `63cba10b805b60dc7108ac7d633b0b1c32da2211b04fd976e1cd637ce083afe0` |
| `rt_data_fixedpool100_1445_dataset_20261012.json` | 15:00 固定池 100 只；每只 15 个 14:45–14:59 分时点 | `4a310b4920dc5c6ebb7ac8b9f50d1e73d2dcb4d0ef685fef329358c09c2223d0` |

15:00 数据独立 PASS：`futu/integration/INDEPENDENT_DATA_1445_REVIEW_20261012.json`，SHA256 `78da5733c19c79dda59c6b28122df92c1eab4755214b6f9f1d4561ae95bfdddf`。本轮已再次核对两个 dataset SHA 未变，不重复 provider 查询。

归档缺口：Writer 曾在 15:38 重复抓取，覆盖先前 15:20 原完整 response 文件。已冻结 dataset、其中原 captured provider rows、provider/projection SHA 未变，Reviewer 已确认消费者可复用既有数据 PASS。原完整 response 原始字节归档可复现性保持 `CANNOT_CONFIRM`。新 `rt_data_remaining99_1445_1500_response_capture_153824_20261012.json` 明确 `NOT_USED`，不得代替旧归档或冒充原回包。

正式失败/结果快照均在 `futu/integration/`：

- `STAGE_1300_1315_AFTER_1500_NATURAL.json`：SHA256 `1e7a2fe0b3236de35b79688af6c34b4b2798f16a8bd1e0d6bc0bcf9d7758d0d6`。
- `STAGE_1445_1500_AFTER_1500_NATURAL.json`：SHA256 `907f00b0c7b2280315cc642c37fc71360fdfcc9d3949374c0c183c7ab7cc837f`。
- `STAGE_1545_1555_AUTOMATIC_AFTER.json`：SHA256 `7cf59bf03f6d45724f03e74e4f563f442a5b3c57c72324a553e4d5f0a9d4c011`。
- `API_8873_STAGE_1545_1555_AFTER.json` 与 `API_61796_STAGE_1545_1555_AFTER.json`：页面读取故障的前态。
- `RELEASES_PREPARED_R3.json`：仅准备记录，不是部署记录。
- `FUTU_RECOVERY_LEDGER.json`：本轮 ownership 与未闭环状态。

## 已定位问题与当前修复

1. 旧 frozen15_r1 漏列 `stage_center/_live_collectors_parts/hk_minute.py` 缓存 adapter 与 `stage_center/_runner_parts/slot_execution.py` 观察 wrapper。冻结包只覆盖 RawStore、registry、dispatch、API RawStore 和孤立测试；Reviewer 未给生产路径 PASS。后续必须冻结所有真实必要接线文件并绑定测试实际 SHA。
2. HK adapter 把固定池成员的列表顺序也当成身份。真实 StageUniverseBinding 和 15:00 dataset 都是 100 只，成员集合、pool artifact SHA、code-set SHA 完全相同，仅顺序不同，错误报 `FUTU_RT_DATA_CAPTURE_IDENTITY_MISMATCH`。Writer 在 `frozen15_r2` 候选改为去重集合相等，仍保留严格 100 只、code-set/pool/source/dataset SHA、日期、阶段绑定。该候选尚未独立 PASS，不得放松其他约束。
3. 第一次真实 CLI 隔离测试使用空状态根，误调度 A 采集；后续隔离测试虽然复制 A run，但人为构造 latest 指针漏 schema/owner，报 `latest.json schema/owner mismatch`。这些不是 PASS。正式写根未作为写入目标，正式阶段产物未改；后一次 provider guard 日志为 0 次。下一步应逐字复制原成功 A latest/所引用 run/raw/selection/receipt 必要结构，用原 reader 先确认 A10 和原 run 可复用，再运行真实原 runner；不得继续合成简化 fixture，不得再触发 TDX。
4. API `apps/api/v35_api/app.py` 的 `project_shared_selection` 将 `OBSERVATION_UNVERIFIED` 一概归为不可计数。真实 15:55 HK.rows/unified_rows 已有 10 行，但 `selected_rows/candidate_count/selected_hk_rows` 被置 null；`HK_FORMAL_ELIGIBILITY_FALSE` 保留为缺口。API Writer 正最小修复完整来源身份的观察行计数，保留观察状态和全部 false flags；缺失或无效身份仍不能显示为有效选择。

16:28 新进展：API 候选只读 GET 已得到 HK10、`OBSERVATION_UNVERIFIED`、`formal_eligible=false`、`NO_BUY`、`execution_verified=false`，原 `HK_FORMAL_ELIGIBILITY_FALSE` 保留，正在冻结可复跑证据，仍未独立验收或部署。原 15:55 CSV/receipt/API 行没有显式 `temporal_cutoff_safe` 字段；该字段缺失保持 `CANNOT_CONFIRM`，不人为制造 false，更不能当成 true。

runtime fixture 新检查在 runner 执行前发现：receipt 的 `A_SHARE.run_id` 是 **selection run ID**，raw latest 有独立的 **raw run ID**。把 selection ID 交给 `RawStore.verify_run` 会报 `run trio incomplete`。各 reader 必须使用自己 exact latest entry 的 run ID；这次只做预检，未运行 runner/provider。Writer 正修此 fixture 绑定，尚无最终真实生产路径 PASS。

## 正在工作的所有者

| Agent | 本批唯一 ownership | 当前终态 |
| --- | --- | --- |
| `/root/afternoon_cutoff_writer` | runtime adapter/wrapper/RawStore/registry/dispatcher、13:15 严格一次新来源恢复；已冻结 API RawStore 字节 | RUNNING；生产路径测试仍未通过，扩展 packet 未完成正式交接 |
| `/root/afternoon_cutoff_review` | 独立只读验收 frozen 实际 diff、真实缓存 runner、A 保持、provider 零调用和 NO_BUY | 等扩展冻结 packet；旧 frozen15_r1 无生产行为 PASS |
| `/root/afternoon_api_projection_writer` | 新 `futu/api_projection` 下 `apps/api/v35_api/app.py` 候选与必要测试 | RUNNING；已定位计数置空原因，未交最终候选 |

API app.py 写权已从 runtime Writer 撤销，两个 Writer 不写同一文件。不要复制或取消健康 worker；接手先消费其新 final/receipt，避免重复派工。候选目录存在不等于交接完成，`frozen15_r2/PACKET.json` 已出现也不能自行视为 PASS。

## 接手后的最短执行顺序

1. 收 runtime Writer 完整、不可变 packet。独立 Reviewer 只检查本目标实际必要 diff，并复跑 **真实 StageCenterRunner → 缓存 collector → raw projection → RawStore → 原 production selection registry → SelectionStore**。必须原成功 A 不变、HK-only、所有 provider fail-on-call、网络/子进程 provider 调用为 0；不能用 FakeOriginalRunner 或手工 SourceResult 代替。复用现有 DATA PASS，不再扩大旧归档审计。
2. 同时完成 API 计数修复的独立针对性复验：真实 15:55 观察 HK10 可计数并进入页面消费字段，原 false flags/NO_BUY 保留；无效或缺失产物不能变成成功。
3. 两个必要面 PASS 后，基于**当前实际** Stage/API 身份重新生成完整 release 和 manifest；确认所有已验 adapter/wrapper 一起纳入，保护并行 HKEX 修改。必要本地服务重载已授权，不另开部署审批。
4. 15:00 用原 dispatcher、原锁、原预算恢复 HK，保留 A10。原入口为 `ops/run_stage_center_nodes.py --config stage_center_tick_config.json --node STAGE_1445_1500 --trade-date 20261012`。必须复用实际 plist 的完整 environment 与 cwd，再绑定 `V4_HK_FUTU_AFTERFACT_DATASET` 到上述固定 SHA 的 15:00 dataset；不得只执行裸命令导致回到默认 provider。以 Writer 交接的已验完整命令为准。
5. 13:15 原 TDX 3/3 历史保留；不能把原上限裸改为 4。用户已授权用富途恢复，须先独立验收 **同日期/同阶段/同 dataset SHA/原 receipt 的严格一次新来源 allowance**，保留锁、旧历史、一次消费标记和 A10。旧 D1-only dependency rearm 不适用，不拿它伪造新授权。当前具体 allowance 命令/实现仍未交接，不能直接再跑 13:15。
6. 15:55 复用既有 HK10，仅修 API 读取，不重采、不补跑该已有产物。分别读取 8873 与 61796 三个阶段 API，再刷新实际页面核对卡片、股票行与观察标记，保存最终截图。HTTP 200、receipt 存在或文档自评不能替代页面结果。
7. 只同步必要源码、测试和精简验收证据到私有 `lexi2016/v4` 对应独立分支并读回 commit/关键文件 SHA；不上传 dataset、原始 response、账户、日志大包或 credentials。三阶段页面完成后汇总准确自然/恢复结论，删除本轮监控，结束。

## Git 与监控

原工作分支：`codex/afternoon-auto-stages-20261012`。既有已读回 commit：`53791437ceed8a98e7f2e926ed9a3ca726d0b379`，包含先前原 dispatcher 修复和独立验收/Stage 身份记录，不包含当前未完成的富途生产接线与 API 计数修复。不能把该 commit 当作富途恢复成果。

本交接将使用新的独立分支 `codex/handoff-futu-afternoon-20261012`，保留原冻结分支及并行修改；同步结果由主控最终消息提供。

现有 heartbeat automation：`10-12`，每 5 分钟，仍 ACTIVE，同一聊天。16:08 更新的 prompt 已记录当前失败、唯一 Writer/Reviewer、已授权恢复和缓存复用。当前新 API Writer ownership 以本文及 ledger 为准。未到完成条件不删除；通常静默，只通知实质失败、恢复、完成或必须用户处理事项。不要新建重复监控。

停止规则：若新实际代码/输入失败，保留精确错误并最小修复，不重复同输入盲跑；健康长任务等待，不能因 wait 超时取消。最终成功只认三个阶段的真实股票产物、API、刷新页面和准确观察/恢复标签。当前状态：**数据已齐；阶段与页面恢复仍未完成。**
