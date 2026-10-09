# 经理工作台三路选股问题：交 Chat 修复

用户分工锁定：Chat 负责代码修复；Mac 会话负责问题描述、交接和返回后的本地验证。本轮未修业务代码、未部署、未执行真实公告采集/审查导入。

1. 公告：目标20261009、公告日20261008的正式审查导入产物缺失。沿原capture → Reader → 独立Reviewer → import定位首断点；不能制造审查或新producer。
2. 美股映射：源数据存在，隔离原owner已产生有限覆盖的VALID_EMPTY；现役17:23仍daily NOT_RUN、计划NOT_MATERIALIZED。修原触发、保存、消费和API/UI连通性，不要求人为制造入选。
3. 超跌：固定10/8读取复现exact-date key缺失导致StoreError。历史与当前索引身份分开；当日收盘后读取的内部原因仍需沿原入口定位。当前695证券资料不等于有报价和资格证明的精确日主表。

- [给Chat的修复任务](package/CHAT_TASK.md)
- [完整问题说明](package/README.md)
- [本地验收要求](package/LOCAL_ACCEPTANCE.md)
- [源码角色与SHA清单](package/source_index.json)
- [最终独立审查PASS](review/report_final.md)
- [最终审查回执](review/receipt_final.json)

验包通过：64项清单文件，含48份完整源码前像、after或参考文件。ZIP目录/字节与离线解包一致。最初P2验收措辞已修正；16:01历史输入原件不在包内，历史重放CANNOT_CONFIRM，当前probe不得冒充历史回放。

本机ZIP：three_channel_problem_package_20261009.zip，SHA256 bace4ace340d38c1d964be1d5609e9cd2333f5b82f80cdfc0474187a0332e74e。包内保留首次审查；最终PASS报告在上方review链接。

本分支基于41a9242d400acec08af3934d1da314b1626a1bcd，只增加本次问题包。API模块隔离复用该固定提交的独立需求包，不重复设计，不把进行中代码当基线。

RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false。
