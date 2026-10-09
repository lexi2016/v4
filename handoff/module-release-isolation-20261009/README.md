# Stage / 经理工作台模块隔离交接

问题包已通过独立审查，包含冻结设计、真实共享面证据、精确路由方法合同、20份完整源码前像、逐文件实施任务及交叉发布/回退验收。

- [完整说明](package/README.md)
- [给实施者的任务](package/CHAT_IMPLEMENTATION_PROMPT.md)
- [独立最终审查](review/REVIEW_FINAL.md)
- [最终审查回执](review/receipt_final.json)
- [源码清单](package/source_manifest.json)
- [首次审查失败记录](review/REVIEW.md)

独立验包：45项包内文件记录、20份源码、ZIP字节及路由AST通过，篡改拒绝。最初缺少可携源码的P1已关闭。运行隔离、部署、业务/API/UI/自然时段验收均未由此包证明。

冻结参考父提交：ca01c4d0260fecf7aae3c89e96899f36901bf8f7。源码根、前像SHA与已有并行修改见source_manifest；进行中的module_proxy.py与api_module_contracts.json标NOT_BASELINE，不覆盖现有Writer。

原唯一平台发布owner已经直接实施拆分。本包供其参考与后续问题定位，不授权第二个Chat/Writer并行修改同一范围。经理R3与Stage业务候选仍分别保存；业务结果验收不以此文档PASS替代。

本机ZIP：V4_MODULE_RELEASE_ISOLATION_20261009_problem_package.zip，SHA256 21d027fee15dc1377c259e51b2eb36f45b242e033a52f3e2d3927a8412103507。

RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false。
