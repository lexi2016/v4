# A股汇总来源与两个复盘池缺口 · 20261014

目标日期20261014，信号日期20261013；直接处理，无子智能体。保留WATCH_ONLY及所有交易安全限制。

## 结果
- A股主池82、复盘观察56、Stage7分时10、研究推荐191；逐只比较与汇总池差集均为空。339条来源行去重为292只，页面200+92分页。
- 分时10只位于汇总第128–137行，例松霖科技。研究191只全部存在；大连友谊等重叠行原先遗漏研究来源标签。
- 唯一业务修改：`domains/preselection.py:414`补充研究池来源映射。现有合并逻辑保留（选）/（复）/（分）/（研）；不改变排名、分数、候选集合或原始产物。

## 未补造的真实缺口
- 复盘观察池：现有自动复盘结构化来源已提供56行；未找到20261013视频逐股gap matrix及对应视频元数据。配置下的native/video及既有review-core、close-review数据目录均无该日可用视频结果。
- Stage7：既有PyTDX原始阶段产物覆盖220/224，缺SZ.920021、SZ.920275、SZ.884133、SZ.920985；保留原始返回代码，不据此认定它们均为有效深市股票。已输出10只观察候选。
- 原始阶段每行bar_count=14，source_status=CANNOT_CONFIRM、temporal_cutoff_safe=false；有分钟聚合价格，但没有可确认十档/逐笔/撤单资料。不能凭已显示候选升级完整或PIT安全。
- 两个池READY_DATA_PARTIAL仍保留；其cannot_confirm还携带上游研究评分和历史输入诊断，条目数量不等于缺失股票数量。本次未清空上游诊断、未改写历史收据。

## 验收
- canonical测试：`python -m pytest -q tests/test_a_pool_source_labels_20261014.py`：2 passed。
- 运行候选实际模块复跑两个测试：2 passed。
- API两页fingerprint相同，292只不重复；全部A子池差集为空，研究191只均显示（研）。
- 8873实际浏览器：大连友谊显示（选）/（研），皇台酒业显示（选）/（复）/（研）；第二页92行，含华海清科等研究股票；返回第一页后分时10、复盘56、研究191行。
- 页面未增加其他模块；API派生发布仅一行映射，基于当时manager-workbench v13 API，保留并行修改。首次bootstrap返回5，退出释放后一次重试成功，API及页面已验证。
- 用户要求直接处理；独立Reviewer NOT_RUN，自然时段NOT_RUN。

## 运行身份与本地证据
- source_root: `/Users/lexi/Desktop/学习/v4_app`
- baseline_commit: `55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054`
- canonical_before_sha256: `85c75d206e5edb66c5dc3f34c8e9d0c1889e73c49950b627fb63c4f12ae9be18`
- canonical_after_sha256: `eab106f0a87408f36af1edf0d3e35e95d64904feca9bbec01dfc8b69cbf51fa1`
- runtime_app: `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/a-pool-labels-20261014-r1/app`
- runtime_file_sha256: `eab106f0a87408f36af1edf0d3e35e95d64904feca9bbec01dfc8b69cbf51fa1`

证据目录：`/Users/lexi/Desktop/学习/agents调试/V4_A_POOL_GAPS_20261014`。原始行情、完整API响应及页面截图只保存在本机，不上传GitHub。
