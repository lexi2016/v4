# 原 US owner 来源与当前源码缺口

范围：只核固定提交的变更文件名、交接说明/元数据和明确指向的原源码；没有遍历完整远端树、读取原始行情或账号数据，也没有修改候选源码、Stage、规则、pins、R1 交付或部署。没有重跑既有测试。

| 固定提交 | 本次核到的入口 | 可证明的范围 |
| --- | --- | --- |
| `9dfa50346357b6dc4b2463a30dcbf3718fce2f03` | `handoff/manager-workbench-20261008/HANDOFF.md` | 提交时间 `2026-10-07T12:21:49Z`，仅此文档新增 96 行；不是新实现，也不是冻结问题包之后的新 Luna 反馈。 |
| `759a1797df28574f73ab90d5005cc14c98ca1c14` | `handoff/us-hk-mapping-research-20261005/RESEARCH_RESULT.md` | 提交时间 `2026-10-05T11:33:31Z`；该提交的变更文件及对应交接目录均仅这份研究文档，没有在该交接入口提供实现源码。 |
| `840b9538c45c9ba8fd56f8e89048aff230df0f0f` | `handoff/us-mapping-daily-workbench-20261005/` | 提交时间 `2026-10-05T18:22:50Z`；确实提供原 US 映射实现与交付 metadata，但明确属于旧 R2。 |

## 此前缺失的 US 映射实现已定位，但不具备 R3 替换资格

原文件：[canonical/v4/manager_research/us_mapping_research.py](https://github.com/lexi2016/v4/blob/840b9538c45c9ba8fd56f8e89048aff230df0f0f/handoff/us-mapping-daily-workbench-20261005/canonical/v4/manager_research/us_mapping_research.py)。Git blob SHA 为 `790485744bc30447c1fb0ac1a31c561d9052b6c3`。UTF-8 内容实算 SHA256：

`f9b545202dc0a8865413f4a6bd7742ab6e69d5d9c756fee5ab3abd7070dff2e8`

该值与 [DAILY_DELIVERY.json](https://github.com/lexi2016/v4/blob/840b9538c45c9ba8fd56f8e89048aff230df0f0f/handoff/us-mapping-daily-workbench-20261005/DAILY_DELIVERY.json) 的 `canonical_sha256` 相符；但同一元数据明确记录其部署版 `deployed_sha256` 为：

`297dc6f5950d3614437378c22e3157b6866823fbf25fd39cb47f112ffea40da7`

两者不同。元数据与 [README.md](https://github.com/lexi2016/v4/blob/840b9538c45c9ba8fd56f8e89048aff230df0f0f/handoff/us-mapping-daily-workbench-20261005/README.md) 标记 `runtime_release=manager-us-mapping-daily-20261006-r2`、manifest `430b774a0157b5bf78c34c1abdd4770df2deb61577642ec8fe3a5c537d74b956`，并保留 `NATURAL_SLOT_UNVERIFIED`。这些是该旧交付的声明，不是本次对真实 Mac 或 R3 现役 release 的独立核验。**不能直接填入 R3 缺口、替换现有 pins，或当作当前运行证明。**

进一步核实：**R2 的 `297dc6...` 并非只有元数据引用，现有两个交付补丁可以完整、精确重构该历史部署文件。** 交接根目录只有 README、PAGE/DAILY metadata、canonical、operators 和 release_delta，未列独立 runtime 源码目录；实际字节来源链如下。

1. 固定提交下 [page_overlay.patch](https://github.com/lexi2016/v4/blob/840b9538c45c9ba8fd56f8e89048aff230df0f0f/handoff/us-mapping-daily-workbench-20261005/release_delta/page_overlay.patch)（Git blob `61852de6fb4466e4603fb9db8ecf34c301227f93`）对该模块是完整 `--- /dev/null` / `@@ -0,0 +1,262 @@` 新增。从该一文件 section 提取的前像为 **11,447 bytes**，实算 SHA256 为 `5d06b07077f4adef851e9c0711e41b406da6e51ce75d989561a93c347a27e2c8`，与 PAGE canonical/deployed 和 DAILY `r18_before_sha256` / `canonical_before_sha256` 一致。
2. 固定提交下 [daily_overlay.patch](https://github.com/lexi2016/v4/blob/840b9538c45c9ba8fd56f8e89048aff230df0f0f/handoff/us-mapping-daily-workbench-20261005/release_delta/daily_overlay.patch)（Git blob `b9f4bcf846925b14bcab1a12d28d21de3f0035e9`）提供该模块 6 个变更 hunk。只提取这一文件，在独立临时目录以 `patch --batch --fuzz=0 --forward -p1` 应用，验证没有 fuzz 或 offset，也没有其他文件路径。
3. 结果为 **14,052 bytes**，实算 SHA256 精确等于 `297dc6f5950d3614437378c22e3157b6866823fbf25fd39cb47f112ffea40da7`。本次未导入或执行该源码，未改 candidate；临时应用目录在完成后清理。

参考文件：`reference/us_mapping_research.runtime_r2.py`。同目录保留精确前像、两个单文件 patch section、`reconstruct_us_mapping_r2.py` 与 `reconstruction_receipt.json`，可仅用现有材料复核字节链。该结论为 **HISTORICAL_R2_SOURCE_RECONSTRUCTION_ONLY_NOT_CURRENT_R3**。

源码本体包含 `read_workspace_mapping`（81 行）、`build_daily_run`（183 行）与 `persist_daily_run`（279 行）。`build_daily_run` 187–205 行使用原 `plan_context`、注入的 `_workspace_us_market_reader` 和 `project_us_market`，并核 reviewed relation 的 available_at/cutoff；225、270 行仍显式输出 `target_date_eligibility=CANNOT_CONFIRM`。255 行说明固定样本与已审关系范围，不是全市场。它是旧版研究映射链路，不能产生目标日港股通资格。

## businessStatus.ts 仍未补齐

已核该交接的 `canonical/apps/web/src/manager-selection/` **目录元数据**，仅有 `catalystObservationPanel.ts` 与 `researchAttention.ts`。`PAGE_DELIVERY.json` 和 `DAILY_DELIVERY.json` 的文件列表也未列 `businessStatus.ts`。

冻结 `source_map.json` 对该文件指定的 SHA256 是 `36228506f199f26dc59c7919634e4c347171d156ec89b3d6b2359c764ed45d90`（其本身标为 canonical UI source candidate / untracked）。此次两个 US 交接入口没有提供与该值可核对应的文件，不能解除先前的源码身份差异。

## 成交量单位证明没有新增

本次已读 README、PAGE/DAILY metadata 与完整 `us_mapping_research.py` 没有提供 HK02 面板或 supplement 的 volume/unit attestation。该 US 映射模块没有 `volume`、`unit`、`shares`、`lots` 或 `attest` 字段/逻辑，也不读取 HK02 成交量面板。这仅是所检查入口的结论，不声称其他未检查路径绝不存在证明。

因此没有新增依据将现有量纲未证实状态改成通过，也不能据这些旧交付推导 shares/lots 或倍率。保留原 `close <= prior60_high * 0.80`、`current_volume >= prior5_mean * 1.5` 及原 owner 的单位准入边界。

## SOURCE_GAP_MAP（不授予 R3 替换资格）

| 对象 | 固定来源 / 实际字节 | 入口或版本限制 |
| --- | --- | --- |
| canonical 模块 | `840b9538.../handoff/us-mapping-daily-workbench-20261005/canonical/v4/manager_research/us_mapping_research.py`；Git blob `790485744bc30447c1fb0ac1a31c561d9052b6c3`；实算 SHA256 `f9b545202dc0a8865413f4a6bd7742ab6e69d5d9c756fee5ab3abd7070dff2e8`；**13,999 bytes** | `read_workspace_mapping` 81 行、`build_daily_run` 183 行、`persist_daily_run` 279 行。旧 R2 canonical，区别于其部署字节。 |
| 历史 R2 runtime 模块 | 同一提交的 page→daily 单文件补丁链；精确重构 SHA256 `297dc6f5950d3614437378c22e3157b6866823fbf25fd39cb47f112ffea40da7`；**14,052 bytes**；本地 reference 文件如上 | runtime 参考中入口为 `read_workspace_mapping` 81 行、`build_daily_run` 184 行、`persist_daily_run` 280 行。闭合的是历史 R2 字节可取得性，不是 R3 当前模块身份。 |
| 当前 R3 模块逐文件 pin | **未在已检查的本地 handoff/source inventory 中提供** | `frozen/{manifest,assembled_baseline_manifest,source_map,source_origins,source_identity_comparison,dependency_entrypoints,evidence}.json` 和 `remote/handoff/manager-daily-chain-20261008/bundle_manifest.json` 未列实现模块逐文件 SHA；只找到 `tests/test_manager_us_mapping_research.py` 的 pin `1c077f679083252b11d07c1499081304e7a3200b2d170baa682ade18be718dcc`。测试文件 pin 不能替代实现 pin。 |
| 当前 R3 release 整体身份 | README 记录 manifest `946c49b9c34bd09fbca04644556de3acba1635eb240fa9293f6391e9d46b40e9` 与 inventory `07ff61bc18f66f7e92eb45f57a20aecf3885eaa79c1bdb705b8f805fdbb95bd8` | 本地只有整体身份声明，不能从整体 SHA 推导缺失模块的逐文件 SHA；冻结问题包同时明确实际加载指纹未核。 |

需真实 Mac 的当前 immutable R3 app、实际导入路径和原 release inventory **共同确认** 下列原始 SHA256 集合。本次均不得以旧 R2 元数据、canonical candidate 或 R1 assembled 文件代填：

- `v4/manager_research/us_mapping_research.py`
- `v4/manager_research/service.py`
- `apps/api/v35_api/manager_research_router.py`
- `v4/manager_research/us_mapping_relation_registry.json`
- 该模块实际消费的 `v4/manager_research/us_mapping_reviewed_20260930.json`，以及 registry 对 seed/release 的真实绑定

已在 R1 assembled 的 service/router 核对，未见 `refresh_us_mapping_research`、`build_daily_run`、`persist_daily_run` 的直接入口；已提供链路中只有 workspace 的 lazy `read_workspace_mapping` import 和 dispatch 的 `hasattr` 检查。此结果**仅描述已提供/组装源码的入口缺口，不能推断实际 R3 service 没有对应方法**。当前 service/router/module/registry SHA 集合、实际 owner 方法、导入路径与 release inventory 未闭合前，不应复制历史 R2 模块覆盖候选或现役应用。
