# 原来源接续与尚缺的事实

本文件更新 R1 中关于输入和源码闭包的判断。已找到的原修复直接复用；这里的源码与历史回执不代表本轮已检查 Mac 当前进程。

## 普通页面原依赖已恢复

从固定 commit `9dfa50346357b6dc4b2463a30dcbf3718fce2f03` 的 `handoff/announcement-daily-repair-20261007/source/` 读取了两件既有原文件，完整 Git blob 和内容 SHA 一致：

| 原路径 | SHA256 |
| --- | --- |
| `apps/web/src/api/managerAnnouncementAnalysis.ts` | `f30ec19c2c5b21f79ecfe3a3a23b1cf9d59bc5f5f48d117c7db4bcce39f3e5b5` |
| `apps/web/src/manager-selection/announcementAnalysis.ts` | `7365a33cd65c024131844ea7a451bc3d89220f6391a17863f31a3781e0b6e327` |

它们作为原依赖用于隔离测试装配，不是新实现，不进入本轮生产补丁，也不证明已加载到现场。原 `ManagerSelectionView.vue` 的 33 文件相对 import 闭包因此可用。原两个 Vite HTML 入口仍未提供；没有补空文件或新造入口后声称完整应用 build 成功。

旧公告包的 API/UI 回执仅用于原字节身份。当前公告后端已有后续变化，因此本轮正向页面数据由当前原 announcement owner 实际产生，没有从旧回执拼接 DTO。

## US：已有原采集入口，不应另启 V35 副本

固定 [原交付回执](https://github.com/lexi2016/v4/blob/840b9538c45c9ba8fd56f8e89048aff230df0f0f/handoff/us-mapping-daily-workbench-20261005/DAILY_DELIVERY.json) 报告原 V4 独立 US 采集任务已加载，上海时间四槽 04:15、05:15、21:00、22:00，`RunAtLoad=false`。这些是历史交付事实，当前 label/argv/启用状态和自然 dispatch 仍需实际读回。

已有修复的 [原 `run_us_market_slot.py`](https://github.com/lexi2016/v4/blob/840b9538c45c9ba8fd56f8e89048aff230df0f0f/handoff/us-mapping-daily-workbench-20261005/canonical/ops/run_us_market_slot.py) 为 10,195 字节、SHA `16f7895072a66b8a7e6ed0c792f74069101426cfa1194df3bd89e63d95f4d948`。较老 canonical 是另一份字节，不能用它覆盖已有迟到槽修复。原 executor 有内联实现；缺少拆分文件不能推出执行能力不存在。

原 V4 capture 只生产 US 输入；R1 原每日循环已经接入 `refresh_us_mapping_research`。不应再新增 mapping hook，也不能把 disabled 的 V35 US entry 启用后当作修复。

实际接续需核：**原 US 任务 `--data-root` = API `store.root` = 经理 US reader root**，并以同 session 的 payload/receipt/manifest 与真实 dispatch 关联。已核两份原 registry/seed 字节与问题包 metadata-only pin 一致，原只读 loader 接受；本包仅记录固定链接和 SHA，不重传原研究 seed，不拿它作合成数据，不把读取验证当成真实 10/8 daily run。

| 经理目标日 | 原应读 completed US session | 原上海 POST_CLOSE 槽 |
| --- | --- | --- |
| 2026-10-08 | 2026-10-07 | 10/8 04:15 |
| 2026-10-09 | 2026-10-08 | 10/9 04:15 |
| 2026-10-12 | 2026-10-09 | 10/10 周六 04:15 |

这是原日历合同推导。保留 `NATURAL_DAY`；冬夏令时由原 resolver 判断，不同时跑两套槽，也不能用 PRE_OPEN 代替 completed POST_CLOSE。

## 公告：外部 Reader / Reviewer 执行合同尚未提供

原 runbook 指定 06:30 heartbeat。原桥接 CLI 已实现 capture/resume、prepare、register-handoff、import、readback。精确缺口在 **capture 固定 evidence run 后，到 register-handoff 接收真实 Reader JSON 与独立 Reviewer JSON 前**。现有桥接代码验证外部产物，不调用这两个外部任务。

仍需原 heartbeat 的非敏感 task ID/时间/启用配置、实际可执行或受支持 API、指定 Reader/Reviewer 的请求与原规则、输出和 task/run 绑定，以及超时/重试/恢复合同。不需要上传凭据。没有这些事实就不能实现一个自称原任务的 adapter，也不能填入统一 SELECTED/WATCH、伪造 Reviewer 或将一次固定导入当成日常生产。

R1 已完成合法已审产品到后续计划的消费；这项成果继续复用。外部产物生产尚缺原合同，单独保留为 `ANNOUNCEMENT_ORIGINAL_HEARTBEAT_EXECUTOR_UNAVAILABLE`。

## HK：实际原 owner 已有时间元数据，超跌量纲仍缺

固定 [实际 shared owner](https://github.com/lexi2016/v4/blob/b00ca5a658a9de83cf5e54ad39aa68ddd5c23526/handoff/stage-autorun-readiness-20261009/source/actual_shared_owner/shared_data/hk_0_2.py) 来自 `20260923-hk02-owner-rebase-r2` 原 upstream，57,090 字节、SHA `45a5091cb26800b7ccf8d7c3c75b680e951d492ac8ceb5f30b80a1ff9a6eebac`。原代码已有 `native_observation`、`manifest_prepared_at` 和不回填旧 manifest 的保护。

R1 测试装配的旧 canonical `27da90f0…` 缺时间不能认作现役缺陷。后续先核 actual updater argv/脚本 SHA、导入 `shared_data.hk_0_2.__file__`/SHA 与 manifest `owner_source_sha256`；不重写旧 canonical 来冒充实际原 owner。

这个实际原 owner 的 v1 仍只证明新增字节，明确单位未知、继承历史尺度未知、供应方 session finality 未证明。经理原量比门槛只接受 owner 已验证证据。因此即使补齐六条同源数值，严格/接近筛选仍不能据此称已完成零入选。

没有找到可安全复用的单位与全六日尺度证明合同。本轮保留 `OVERSOLD_VERIFIED_VOLUME_CONTRACT_UNAVAILABLE`，不以字段同名、scale=1、裸单位文字、lot size 或金额/价格推算升格。R1 同次 capture→membership/V2→HK02→master→读回继续复用；真实历史资格与 PIT 缺口仍保留。

## 共享发布边界更新

Issue #30 已有固定源码候选 `2ead7eb9e9f067b69610d24990bc47f792bc75b4`，但未取得本轮现场集成/部署证据。本轮只检查兼容边界，不修改其 policy 或 Stage。

其原 policy 尚不接受 R1 的四条 API 接线路径：`infrastructure/_research_peripheral_store_parts/_namespace.py`、`infrastructure/scheduling/manager_announcement_supervisor.py`、`ops/render_manager_announcement_binding.py`、`ops/run_manager_announcement_cycle.py`。唯一集成 owner 应先确定这些路径的 ownership，并在受保护的累计基线上验证；不能偷偷扩大 shared_paths，也不能使用旧整包覆盖 #28。

本轮新增生产 delta 仅经理 `workspace.py` 与 `catalystObservationPanel.ts`；它们不能替代整个 R1 的受保护集成。上述原任务、实际来源、真实 10/8 和连续自然日仍按原执行交接验收。
