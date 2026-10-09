# Chat修复任务：三路经理选股问题

请仅基于本包证据与完整源码前像修复三个既有问题。用户授权 Chat 负责代码修复；本机任务只交问题包并在修复返回后做本地验收。没有授权部署、重启现役服务、写共享state、导入真实公告、采集行情或修改交易门禁。

## 公告链路

target trade date 20261009，publication date 20261008。沿原任务与原 owner 追查 capture、正式 Reader、不同identity正式 Reviewer、handoff/import、workspace消费。检查证据未见 capture/Reader/Reviewer/imported product；first break 为 CANNOT_CONFIRM。定位实际断点；不能只报告缺输入、伪造review或建立第二producer。

## US mapping daily

20261008 POST_CLOSE 输入存在。隔离owner run a95450cd4b264fb6840308d7d2681cf6 是 VALID_EMPTY，产品 SHA-256 2ac764fa1d5b691c6db518ff35b278f89cceeedd3614549a6741d4e8987bfa67；33/33 configured/available，reviewed 4，US匹配0、HK关系0、full_market=false。17:23 live GET daily NOT_RUN、plan NOT_MATERIALIZED。修复既有 trigger/dispatch、映射保存消费、API/页面连接。不要重写算法或为产生匹配放宽阈值。观察到的binding配置不构成因果证明。

## 超跌screen reader

16:01 plan dba211c2677045afb4e0ef8c990367ee 为 PARTIAL，root 是 /Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data，session 20261008。只读复现得到：

StoreError: HK security-master metadata invalid: '20261008'

16:01快照的该root有36个日期条目、最新20260930；17:34只读复现时文件已更新为37个日期条目、最新20261009，但仍没有20261008键。loader在 entries[trade_date] lookup 失败，尚未执行该日期manifest/receipt schema/source校验。按这个已证事实定位并修复原reader/其权威输入消费。17:23 live session已变成20261009 POST_CLOSE，GET只暴露StoreError类型，内因CANNOT_CONFIRM；16:50另见exact-date panel missing。不要把10/8缺项称为当前唯一阻塞或宣称解决。695/Futu快照未证D1 security-master身份，不得冒充替代。

## 返回

只改三问题相关源码和定向测试，保留现有页面布局、owner、A/HK及BUY安全边界。返回每个文件完整after、patch、准确before/after SHA、准确源码身份、定向测试命令及真实结果；列出未运行测试和CANNOT_CONFIRM。交付候选代码，不声称部署、集成、API/UI或自然时段验收。不改计划任务，不写真实业务state，不上传原始行情/公告/凭证，不扩大权限。
