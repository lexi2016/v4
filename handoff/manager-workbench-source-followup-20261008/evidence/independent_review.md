# 原 US owner 历史源码补充：独立只读复核

日期：2026-10-08。范围：`inputs.md` 及其中的 SOURCE_GAP_MAP、单模块 reference/patch/receipt/重建脚本，以及补充包 README 和 SOURCE_GAP_MAP。未修改 candidate、R1 交付、生产源码或 pins；未重跑业务测试，未接触实际 Mac。

**结论：历史 R2 来源与精确字节重建通过复核。本范围未发现未关闭的 Important 问题。当前 R3 准入仍为 NOT_ESTABLISHED；这份补充不构成模块安装、当前部署或自然运行验收。**

## 独立来源与字节核对

本人独立通过 GitHub 读取固定提交 `840b9538c45c9ba8fd56f8e89048aff230df0f0f` 的 PAGE/DAILY metadata、canonical 模块及两份原始 patch，另核对该提交下 patch 路径与 Git blob 的对应关系。完整 blob 内容的 Git SHA 实算匹配：

- `page_overlay.patch`：`61852de6fb4466e4603fb9db8ecf34c301227f93`。
- `daily_overlay.patch`：`b9f4bcf846925b14bcab1a12d28d21de3f0035e9`。
- canonical 模块：`790485744bc30447c1fb0ac1a31c561d9052b6c3`。

两个本地单文件 patch section 与上述原 blob 中的唯一对应 section 逐字节相等。page patch 对此模块是完整新增文件；提取后的前像与本地 `us_mapping_research.page_base.py` 相等。随后本人在独立临时目录仅对该文件执行 `patch --batch --fuzz=0 --forward -p1`，成功且没有 fuzz 或 offset。

| 对象 | 独立实算 SHA256 | 字节数 |
| --- | --- | ---: |
| page 完整新增前像 | `5d06b07077f4adef851e9c0711e41b406da6e51ce75d989561a93c347a27e2c8` | 11,447 |
| canonical 模块 | `f9b545202dc0a8865413f4a6bd7742ab6e69d5d9c756fee5ab3abd7070dff2e8` | 13,999 |
| 重建的历史 runtime 模块 | `297dc6f5950d3614437378c22e3157b6866823fbf25fd39cb47f112ffea40da7` | 14,052 |

前像匹配 PAGE 的 canonical/deployed 与 DAILY 的两项 before SHA；最终 runtime 匹配 DAILY 的 `deployed_sha256`，且与本地 `us_mapping_research.runtime_r2.py` 完全相等。canonical 与 runtime 是不同字节，不能互换。

该 metadata 登记的 release 是 `manager-us-mapping-daily-20261006-r2`，manifest 为 `430b774a0157b5bf78c34c1abdd4770df2deb61577642ec8fe3a5c537d74b956`，其 `NATURAL_VERIFIED` 为 false。复核证明与**旧交接登记的部署字节**一致，未实地复核历史或当前 Mac 进程。

## 重建脚本与 receipt

另将原脚本、前像及单文件 patch 复制到新的临时目录，实际执行脚本，退出码为 0。输出仍精确为上述 14,052 字节；生成的 `reconstruction_receipt.json` 经 `json.loads` 成功解析，内容与现有 reference receipt 相同。

对所审最终脚本做 AST 检查，`write_text` 末尾追加的常量是真实换行；生成文件也以真实换行结束。未复现 literal backslash-n 导致无效 JSON 的疑虑，无需为此修改脚本。两种独立复现均未导入或执行重建出的 US 模块，临时目录随后清理。

## 当前身份和验收边界

独立检查了 SOURCE_GAP_MAP 列出的 `frozen/{manifest,assembled_baseline_manifest,source_map,source_origins,source_identity_comparison,dependency_entrypoints,evidence}.json` 及 `remote/handoff/manager-daily-chain-20261008/bundle_manifest.json`：其中未提供当前 R3 `us_mapping_research.py` 的逐文件 SHA。可见的 `1c077f…` 是测试文件 pin；R3 的整体 manifest/inventory SHA 也不能推出缺失模块的 SHA。这是对上述已检查材料的结论，不声称未检查处不存在对应源码或 inventory。

R1 assembled 的 service/router 未见 `refresh_us_mapping_research`、`build_daily_run`、`persist_daily_run` 直接入口；workspace 的 lazy reader import 和 dispatch 的方法存在性检查确实存在。文档正确将此限定为所提供源码的入口缺口，没有据此断言实际 R3 没有 owner 方法。

当前 immutable app、实际导入路径及 release inventory 仍须共同核实 module、service、router、relation registry、reviewed seed 的原始 SHA 与调用关系。不能用旧 R2 reference、canonical 或 R1 assembled 字节代填当前身份，更不能据此放宽 R1 before/preserve pin。

参考源码明确保持 `target_date_eligibility=CANNOT_CONFIRM`，只描述固定样本及已审关系，不提供全市场或目标日港股通资格；本次没有得到 HK02 成交量单位/倍率证明，也没有得到独立有界 US 自然调用的现场回执。

补充包 README 和 SOURCE_GAP_MAP 均将历史恢复、当前 R3 准入、部署和自然运行分别表述；R1 业务修复仍指向固定提交 `66339d576431285cfaa7e62ca58de31e7548a931`，没有因来源恢复而宣称三路每日运行完成。本复核不替代旧模块业务逻辑、当前适配、完整依赖或调度执行的验收。
