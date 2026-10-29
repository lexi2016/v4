# 同 owner 原式图发布 / 恢复最简 SOP

状态：最终独审 PASS，仅源码行为/隔离样例已验证；15:40 runtime、正式安装、自然日更、历史同事件收益仍 NOT_RUN。初始 P2 FAIL 不删除，见 INDEPENDENT_REVIEW_RECEIPT.json.initial_verdict 与 publication_fix/。

1. **核来源。** 使用专用 V4_RESEARCH_PANEL_A_DATA_ROOT → 原 executor --a-data-root → SourceContext.root。consumer 继续显式 V4_A_SHARE_HISTORY_DATA_ROOT；核实际路径相同，不能以通用 V4_DATA_ROOT 代替。原 paired pointers、generation/input、snapshot/config/formula/engine、bars/交易日历绑定必须匹配。
2. **保留而不重算。** fresh stock 原 engine 只计算一次；仅候选压缩保留该51/22结果。相同数字/图 checkpoint 复用零次 compute/render。旧 numeric cache 没有完整结果就记录明确 gap，不隐式计算补齐。
3. **固定数字后派生。** 原数值循环结束先 context.unchanged；数字 row/product/manifest 字节按原逻辑固定。sidecar 只引用已固定数字 manifest，由原 renderer 输出 HTML/PNG/projection，逐股记录成功或 typed gap。单图失败不得丢数字结果。
4. **发布前最后核源。** finalizer 完成后再次 context.unchanged；若变化，写 checkpoints/.../publication_error.json（CANNOT_CONFIRM、原因及数字/图refs）并 raise，保留产物，不前移当前 index/event。若已有旧当前指针，保留其原字节，不删除或冒充本次成功。稳定时才依序原子写同 owner index 的 optional descriptor，再发原 completion event；SSE 必须核 numeric refs 及 chart descriptor 一致。
5. **有据恢复。** 先读 publication_error.json 和 retained/ready checkpoints，核新旧来源差异。未解决来源变化前不得发布旧工件或改状态造 PASS。恢复在原 owner/原根继续，只复用匹配 identity 项；无完整结果保留 gap。GET 只读完成产物，禁止计算/渲染/抓数据。

针对性证据：初始Reviewer替身复现 finalizer 内 source pointer/panel 变化仍发布；修后同类变化零 index/event 发布，错误/产物保留。9项初始检查与真实600025的1次compute/2150行/51+22/数字row byte parity复用；返修只跑3个受影响 publication/error cases（0.10s）。没有重跑旧3/247/旧12/UI。
