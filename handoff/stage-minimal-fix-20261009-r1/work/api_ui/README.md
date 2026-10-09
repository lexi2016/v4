# 原 API 读取端的最小修复

当前实际 API `execution_evidence.py` 前像来自本轮固定提交 `28ab2d35020adf031f10f38c1040514fc81b6d66`，SHA `e4c4ea94d892158383620beab1825014f21e926b57907354475f8c9ff382704b`。`consumer.py` 只有同一提交中的 10/5 历史 API 前像，SHA `61f8a3541aa7a2e698cc4374385e3d20d41b40ffd5a3cd7d87c9494cb8726cf4`；它是独立条件件，不能覆盖未知当前消费者。

## 行为

- 从原消费者已经验证的市场 envelope 单独投影 `selection_results`。即使缺执行回执，合法的 A 结果、216 请求、205/206 行情及 10/11 缺口仍可展示。允许状态与整数计数严格检查；未知状态、boolean 计数不当成可用结果。
- 读取同一原 owner 保存的历史正文，验证固定槽位、路径、SHA、当前正文和真实 UTC 写入时钟。旧回执不补造时间、不发生任何写入。
- 可选 `selection_store` 只使用原消费者既有的 `self.store`。沿原 `_verify_run` 和原 SafeRoot 读回 artifact/manifest/receipt，分别验证文件字节 SHA 与 JSON 规范化 SHA，并检测当前回执在读取期间被替换。
- 新回执的 `runner_clock_source` 正确映射到读回字段 `invocation_time_source`。HK 明确缺 STRICT_0_2_READY 的原因投影为 `PRESELECTION_INPUT`。
- `execution_verified`、`natural_verified` 保持 false；owner 自存档案、模式声明、写入时间、已核选股三件套都不构成独立自然触发证明。A 候选输入引用仍标 `REFERENCE_ONLY_CURRENT_TRIO_NOT_BOUND`，没有把尚未独立读回的输入三件套标成已绑定。

## 应用与核验

`SOURCE_CHANGES.json` 给出两个独立补丁的完整前后 SHA 与路径。`patches/actual_api_reader.patch` 面向本轮 actual API 前像；`patches/conditional_api_consumer.patch` 只在当前消费者精确匹配历史前像时应用。消费者仅增加 `selection_store=self.store`，没有修改预选池、limit、来源根或其他 API 功能。旧调用保持兼容，但不会得到独立 store 三件套绑定。

作者最终 28 项通过；独立 reviewer 以原 SelectionStore 实际发布和读回驱动 actual/canonical writer，再接 reader/consumer 原调用边界，34 项通过。三类初始独立发现（时钟键名、状态口径、非法状态类型）及最初 26/32 结果均保留，修正后重新通过。见 `../hk_entrypoint/api_review/REVIEW.md`。

本地复跑：在此目录用具有 pytest 的 Python 执行 `python -m pytest -q tests`。测试支持文件有明确固定身份；作者套件的 SelectionStore 是受控边界，独立往返使用原 store 与已 pin 的历史依赖。消费者测试只执行原调用 AST；不是完整当前 API 导入、HTTP、Mac 或浏览器验收。

补丁正向应用及反向还原逐字节通过，见 `evidence/PATCH_ROUNDTRIP.json`。完整集成/发布按主包 `MAC_ACCEPTANCE.md`，不得以这些切片测试替代运行版本、8873 或自然验收。
