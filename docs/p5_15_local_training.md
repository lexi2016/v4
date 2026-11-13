# P5.15 本地研究实验入口

`ops/p515_local_training.py` 使用 P5.14.8 修复版冻结观察、单股 RAW 前缀、同股历史关联和已验收的 P5.15 课程审查。输出位于 V4 本地 `artifacts/p5_15_local_training*` 实验目录。命令中传入已有研究证据目录和本地课程审查目录。目标目录应为新实验实例。

```sh
"$PANEL_PYTHON" ops/p515_local_training.py \
  --research-root "$P515_RESEARCH_EVIDENCE" \
  --audit "$P515_LOCAL_COURSE_AUDIT" \
  --output "$P515_LOCAL_RUN_ARTIFACTS"
```

冻结输入的 586 条观察覆盖 455 股、557 个技术事件键和 38 日。有 585 条观察可形成研究代理，1 条缺 RAW。根锚和波次真值、历史 PIT 以及独立阶段及回调标签的交集为 0。全组合开发 fit、预处理 fit、校准 fit 与预测计数均为 0。可运行的准入检查和输入合同与结果并排保存在本地。

后续接入一份独立验收的开发表时，调用方须传 `--certified-development-manifest` 与独立批准的 `--approved-manifest-sha256`。清单 `p515-certified-development/1` 绑定当前 runner SHA、CSV SHA、独审身份和冻结的开发标签截止日。证据分别为 `independent_label_adjudication` 和 `historical_pit_and_features`，记录所有者和 SHA。

1. 用 `--freeze-only --plan-author <身份>` 运行一次，把 `PREFIT_FREEZE.json` 交给独立验收方。该次调用只准备物料。方案记录来源版本、数据 SHA、特征合同 SHA、拟议变体、每折证券事件日期分母与窗口键 SHA。
2. 独立验收方核对同一方案及证据后，提供 `p515-fit-approval/1` JSON 与其 SHA。回执保存 `reviewer`、具明确时区的 `reviewed_at_utc`、`APPROVED_RESEARCH_DEVELOPMENT_FIT` 裁决、`prefit_freeze_sha256`，并照录方案中的 `scope`、`certified_manifest_sha256`、`certified_input_sha256`、`runner_sha256`、`feature_contract_sha256`、`verified_data_sha256`。复核身份须与方案作者不同。调用方从独立验收方取得已批准的回执 SHA，文件绑定本身不验证人员或代理身份。
3. 另一次调用保留相同数据参数，传 `--prefit-freeze`、`--fit-approval-receipt`、`--fit-approval-sha256`，使用另一个新的 V4 本地实验目录。入口在调用估计器前比对完整方案、回执、环境和实际折分，方案或样本变化后重新冻结和审查。

A 对照同样本价格与价格加结构，B 对成熟深度、成熟时间和支持失效分别比较同样本对照。C 用同支持市场、行业、个股、组合四组，D 用同支持市场与行业独立比较。开发窗按日期切两折，每折按事件与根锚去交叉，并去掉同股训练结果区间与开发事件重叠的记录。分类要求每类每折至少 5 个训练根、2 个开发根，回归至少 20 个训练根、8 个开发根。阈值用于最小开发运行，进一步的确认检验需独立冻结。UNKNOWN 或未启动、未成熟、删失不得进入相关目标的拟合。

当前运行核验包括来源 SHA、前缀截至 D、复合键与历史可得日期、原券日与图索引计数的对账。已发表的交易结果、原策略分数、类型和观察样本选择原因保持原研究用途。
