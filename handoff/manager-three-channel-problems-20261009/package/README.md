# 三路经理选股问题包

问题矩阵：problem_matrix.md。Chat修复指令：CHAT_TASK.md。本地验收：LOCAL_ACCEPTANCE.md。

package/source/ 包含固定R3交付manifest中相关修改文件的完整前像和候选after，以及screen调用链、master loader、store、公告consumer和原owner入口的完整参考源码。package/source_index.json列出相对路径、角色、原状态、字节数和SHA-256。

冻结候选ref：ca01c4d0260fecf7aae3c89e96899f36901bf8f7；本地交付manifest base：b98d85c95d19780e2900dce7de9372328e67acf6。完整源码可从固定Git ref取得，本包同时携带三问题相关的完整文件前像和after。

17:23 GET只读显示plan未物化、US daily未运行、公告未导入、当前20261009 POST_CLOSE screen报StoreError。16:01 frozen plan的20261008 loader已只读复现缺exact-date master key；17:34文件已更新到37日期、最新20261009，仍缺20261008。不同日期与时段分别记录；20261009错误内因仍CANNOT_CONFIRM。

RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false。无行情行、股票列表、完整公告正文、凭证或原始业务state。
