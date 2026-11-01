# R2.1落地与独立验收反馈，请裁决下一步最小合同

我们按你最新R2.1合同只改三个shadow文件，没有自行修改membership/close owner，没有开启自然canary。实际独立结果见REVIEW_RESULT.md：53 tests passed，工程模式隔离/真实gate阻断/runtime日期窗口/局部immutable检查通过，但整体R2.1仍FAIL。

用户分工锁：Chat给方案，Codex负责落地、测试、反馈。以下新问题没有自行修复。

请读取当前源码、r2_1.diff、manifest和REVIEW_RESULT，然后明确裁决：
1. P1：production_run_id可由metadata自报；freeze API能接受手工构造的capture receipt，无真实selector调用也能工程FROZEN/verifyPASS。REAL当前仍全部blocked。你要求的实际invocation identity如何在原三文件范围实现？若确实需要已有runner/owner身份，请指出最小依赖和允许范围，不让Codex再猜。
2. P2：receipt缺独立source_artifact_sha256字段，虽raw/source确实做相等校验，请给准确schema要求。
3. P2：verify只校验本地冻结工件，外部provenance变更后仍PASS。请明确需封存哪些原始bytes或复验哪些路径，以及“本地工件完整”与“源仍可复验”的状态边界，避免无限扩大安全目标。
4. 明确REAL owner pending时，本批合格终点是否应是工程admission hardening PASS而自然继续blocked；cases3-6及真实case8如何按未实现/blocked记录，不能要求用工程fixture冒充自然READY。
5. 补足你认为必要的最少反例，尤其真实selector未调用不得声称invocation已验证、动态baseline mismatch和独立receipt字段不一致。

固定selection.py和ops SHA仍未变；无需改margin/tau/H/同lane规则。目标仍是全部港股通当日收盘涨幅Top20，D1Top100仅输入，不cap筛、不剔已大涨。现有membership/close缺口见附SOURCE_AUTHORITY_FACTS.md，不恢复20260911、不抓第二底板。

下载链接中的R2_1合同文件没有出现在本机，我们执行的是用户完整粘贴文本CHAT_R2_1_CONTRACT.txt，不宣称验证过链接的5d91...SHA。

源码包不是完整V4环境，依赖不足时不要把无法pytest当实现失败，也不要把本机53PASS当Chat独立复跑。正式自然样本=0，无scheduler、BUY、交易动作。
