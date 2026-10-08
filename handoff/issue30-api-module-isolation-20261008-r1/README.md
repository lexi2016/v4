# Issue #30：API 模块发布隔离源码交付

输入为 [Issue #30](https://github.com/lexi2016/v4/issues/30) 及固定提交 `a0a0b88dc133d14ee5763569272c174bcd7cc445`。本目录包含八个产品文件的候选、精确差异、完整便携测试和保留失败记录的独立审查证据。

请依次阅读：

1. [完整说明与实现边界](README.zh-CN.md)
2. [给本机接手者的处理提示词](PROMPT_FOR_MAC.md)
3. [最终测试与执行环境](TEST_RESULTS.json)
4. [独立最终审查](evidence/independent_final/final_review.md)
5. [源码前后身份](SOURCE_MANIFEST.json)与[剩余事项](OPEN_ITEMS.md)

**这是源码候选交付。Mac 集成、部署、真实 API/UI 与自然时段验收分别报告，不能由便携测试替代。** 完整当前 R2 依赖闭包及实际来源 canary 尚待本机核验；不要用历史 `test_support` 覆盖正式源码，也不要用 R2 专用 pins 直接发布新版本。

`RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false`。V4/8873 保持唯一入口，A/HK 分离，Vibe 8910 保持原样。
