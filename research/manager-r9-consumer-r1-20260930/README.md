# R9 公告正文选股与美股映射：本机验收反馈

状态：代码范围审查通过；目标运行环境接入验收 FAIL/BLOCKED。候选未部署，真实 API/UI/港股通名单未验证。

- [验收反馈](feedback/验收反馈.md)
- [独立验收回执](feedback/receipts/independent_review_receipt.json)
- [当前运行路径绑定](feedback/current_runtime_context.json)
- [给 Chat 的接续要求](feedback/提交Chat的补充提示词.md)
- [候选源文件身份](feedback/SOURCE_PINS.json)
- [实际运行前像](baseline/v4/manager_research/)
- [已验隔离候选后像](candidate/v4/manager_research/)
- [47项针对性测试](repair_tests/)

本目录是有明确身份的源代码/证据切片，不是独立可运行应用。reference_only 仅供来源及原owner判断，不得整树部署。使用实际完整r9闭包复验，禁止用旧参考service替代当前依赖。

## 当前缺口

候选依赖的 V4_MANAGER_UNIVERSE_ROOT 未在当前API绑定；已有HK_CONNECT_FULL_MARKET资格原件最新20260814，没有目标20260930。普通HK证券主表没有Stock Connect资格字段。当前Stage入口明确不运行旧full-market producer，不得绕过它补造资格。

## 已验事实

独立47/47通过；原回归候选/基线同为132通过、6失败，无新增失败。冻结10文件未发现P0/P1代码缺陷。实际目标资格、正向选股、HK.09969→LLY关系仍CANNOT_CONFIRM。镜像时间与拒绝原因的UI展示未验收。

RESEARCH_ONLY=true；production_allowed=false；buy_gate_updated=false；orders_sent=false。经理范围仅港股通；A股Stage、BUY、Vibe8910和暂停daily草稿不在本次接续范围。
