# 落地脚本测试与边界

这组测试只依赖 Python 3.10+ 标准库，使用临时目录中的明确 synthetic manifest、源码字节和 API 投影。它不读 Mac 的 695 行采集文件，不调用行情商、HTTP 服务或现役 API，不构成现役业务验收。

在解压后的交付目录运行：

```bash
python3 -m unittest discover -s tests -p test_deployment_tools.py -v
```

17 个测试覆盖：exact 前像任一不匹配时不建立候选；包内 after 损坏时不复制；通过父目录符号链接嵌套源根被拒绝；已复制的全部前像在任何补丁写入前再核；源 marker 符号链接不误写外部文件；候选后像再次被改动时 configure/run 在导入应用前拒绝；输出根与原应用、候选及配置输入根独立；源配置的输入和其他字段保持原值；报告只能新建；API 同一个 run 仍须 date/stage/market、算法/raw/source SHA、研究输入与回执三件套一致，A 股也须绑定 owner 声明与原结果输入引用；summary 的 source SHA 相同也不能掩盖 owner 源码绑定冲突；HTTP 正确也不能掩盖本地 reader 冲突。

## 工具运行约定

三份脚本保持在同一个 `tools` 目录中，旁边的上一级目录必须含本包完整 `SOURCE_MAP.json` 和 `after` 文件。`stage_patch.py prepare` 会把角色和整个 SOURCE_MAP 的 SHA 写入候选 marker。`current_research.py configure` 与 `run` 均重新验证 marker、包 SHA 与角色下所有 after 文件。因此更换交付包后，应重新 prepare 新候选；不能把旧 marker 当成当前包的验证证据。

以下变量由落地人员设成实际路径，三个候选/输出目录均应为全新的独立路径。`V4_STAGE_ROOT` 是完整 Stage 应用根，不能指向只含补丁切片的目录；`V4_ORIGINAL_CONFIG` 仍使用现役完整输入配置。若原配置有相对输入路径，运行工具时保持与原运行器相同的工作目录，避免改变相对路径的含义。

```bash
python3 "$V4_PACKAGE/tools/stage_patch.py" check --role actual_stage --root "$V4_STAGE_ROOT"
python3 "$V4_PACKAGE/tools/stage_patch.py" prepare --role actual_stage --root "$V4_STAGE_ROOT" --candidate "$V4_STAGE_CANARY"
python3 "$V4_PACKAGE/tools/current_research.py" configure --source-config "$V4_ORIGINAL_CONFIG" --candidate-root "$V4_STAGE_CANARY" --output-root "$V4_RUN_OUTPUT" --hk-research-root "$V4_HK_RESEARCH_INPUT"
python3 "$V4_PACKAGE/tools/current_research.py" run --candidate-root "$V4_STAGE_CANARY" --config "$V4_RUN_OUTPUT/current_research_config.json" --trade-date 20261009 --stage STAGE_1545_1555 --report "$V4_RUN_OUTPUT/manual-run.json"
```

`configure` 只改 `raw_root`、`selection_root`、`receipt_root`、显式 HK 研究输入根，以及顶层与 `safety` 内的研究金融标志。它不复制或改写原行情/预选输入。原配置中的其他字段，包括旧授权或回填 metadata，保持原值；这条 `run` 入口调用原 `_load_config`、`_build_runner` 和 `tick(..., historical_backfill=False)`，不会据此改标自然运行。

`--report` 文件必须不存在；不要复用 owner receipt、selection JSON、源码、配置文件或上次验收报告的路径。输出报告可以放在独立运行目录下，但不能放进原应用/输入根或 selection/receipt 根中。失败的候选可能留下供排查的隔离副本；不含有效 `V4_CANARY_IDENTITY.json` 的副本不能 configure/run，应选新目录重建。

同一 run 的 API 回读在既有部署步骤完成后执行，`V4_API_BASE_URL` 是本机实际服务地址；下列命令没有在 Chat 环境调用真实服务：

```bash
python3 "$V4_PACKAGE/tools/same_run_probe.py" --api-root "$V4_API_ROOT" --selection-root "$V4_RUN_OUTPUT/stage/selection" --receipt-root "$V4_RUN_OUTPUT/stage/receipts" --base-url "$V4_API_BASE_URL" --date 20261009 --stage STAGE_1545_1555 --market HK_CONNECT --report "$V4_RUN_OUTPUT/same-run-api.json"
```

探针同时读取原 SelectionStore/owner receipt、明确 run 的 API 查询和 Vue 使用的普通查询。`SAME_RUN_VERIFIED` 仍只说明这些回读一致；浏览器渲染验收保持 `PENDING_MAC_BROWSER`，手动执行的 `natural_verified` 保持 `false`。A 股也可用同一工具指定 `--market A_SHARE` 和该市场实际有结果的阶段。
