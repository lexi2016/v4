# 公告最新采集失败：OWNED_FILE_TOO_LARGE

本目录是 **2026-10-17 23:00 一次真实按钮操作的诊断材料**，不是已实施修复，也不是可直接部署的完整代码树。

- [给 Chat 的修复请求与验收要求](CHAT_REPAIR_PROMPT.md)
- [失败任务原始记录](failed-attempt.json)
- [采集产物大小、SHA和只读复现结果](capture-product-summary.json)
- [API前后状态摘要](api-before-after-summary.json)
- [现役源码与canonical绑定](runtime-and-source-binding.json)
- [现役源码切片](active-source/)
- [失败页面截图](failure-ui.png)
- [完整精简材料 ZIP](announcement-capture-failure-20261017.zip)
- [SHA-256清单](SHA256SUMS.json)

## 已确认结果
采集任务 e20cf0d93ea843a885b090173b6eab55 在 CAPTURE_ANNOUNCEMENTS 阶段失败，报 OWNED_FILE_TOO_LARGE。83.519 MiB聚合产物已落盘，但 save_product 使用64 MiB默认读上限，保存后读回失败。模型输入和结果文件均未生成，模型研究未启动。页面显示的旧11只候选不是本次结果。

## 代码基线
active-source/ 内四个文件来自真实运行 release announcement-continuation-api-20261017-r11c，SHA与本地canonical逐项相同。材料分支继承的其他仓库文件仅为宿主，**不得视为现役运行基线**。若修复需要更多依赖，先列精确路径；不要猜测或覆盖并行修改。

## 范围
仅修复既有采集产物保存/读回大小合同，复用缓存和既有成功模型结果；不得放宽全局安全边界、截断数据、另建producer、绕过PIT/资格检查或修改交易门禁。修复后须独立Reviewer、实际新增研究启动证据和API/UI读回；本材料不宣称修复完成。

旧问题 [#24](https://github.com/lexi2016/v4/issues/24) 属于另一条计划读回链路，只有错误类别相似，不是本任务的完成证据。

本包排除大型原始公告、完整API响应/AX研究文本、凭证、token、完整配置、账户和持仓信息。元数据中的本机用户目录替换为 ${USER_HOME}，源码保留原字节以便核验。ZIP内容与本目录一致（不递归包含ZIP自身）。
