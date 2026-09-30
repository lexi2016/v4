# Issue #8：B1 公告连续消费 / B2 盘前顺序 / US 原文匹配增量

本批不等待 17:20 F0，不修改资格供给、资格门、BUY、Stage、F5、Vibe 或调度配置。
R3B Mac 10/10 回执 `0d6005e8282ed5e3467c1b9e37d98c7c6d8fb286` 复用；不重复修复或测试。

## 交付边界

- `after/api/`：以用户固定 R1 业务前像为输入，修改 workspace_announcements.py、issuer_us_relations.py，新增 eastmoney_run_history.py。
- `after/snapshot_20260929/`：以 8851f7f84e3d506d3f1317eec03ba92c8f49e324 为输入的 cycle 顺序修复。不是活动 Mac 源码证明；使用单独 cycle_snapshot.patch。
- R2 connect_selection.py 和已验 R3B workspace.py 原字节保留，workspace_plan_autorun 的窗口/幂等规则原样使用。
- 完整改后文件、精确前像、三个 patch、源 SHA、实际红/绿日志与 JUnit 均附。原 R1/R2/R3B 包和 manifest 不覆盖。

## 实际业务改动

B1：默认每批仍最多 3 issuer、4 正文、原 45 秒/请求/字节预算；从本日已提交的 sweep 接续而非总取前三家。默认扫完回到新一轮，显式 singleton 不重置默认进度。覆盖区分已安排、真正留存目录响应、成功/失败查询、待读正文；始终不声称目录分页穷尽。

读取端枚举同日多个 committed named run，经原 master / HTTP-envelope / 正文 / PDF 来源验证后合并。按 issuer + art_code + body SHA 去重，保留各次 capture 引用。坏 run 独立拒绝，后批/失败 latest 不覆盖前批输入，跨日与 cutoff 仍严格检查。GET 不抓取、不写盘。

原 MaterialStore 的 latest-key index 会被重复 listing 抓取替换。新增模块在同一 MaterialStore 的 observations/eastmoney_hk 下保留原 index 的真实已验证字节见证，供原 response validator 读取；不从 ref 虚构旧 index、不改旧 run。旧索引已经丢失且没有见证的历史记录仍明确拒绝。保留原见证失败时，不先抓取覆盖旧索引。

新 run 先存可校验 terminal journal，最后创建 immutable named product 作为提交点；latest 不是新协议的提交证明。读取 legacy 历史需原 latest 或 terminal scope/time 证据，无法证明提交的孤儿文件不晋升。

B2：原 announcement collection 一次完成后，取新的实际时钟调用原 preopen autorun。最后一轮新输入能在同 tick 被消费；跨过 09:30 则 EXPIRED_NO_BACKFILL。采集异常保留失败状态，同时允许原 owner 在窗口内使用既有成功输入。取消/硬超时不吞掉；不增加请求，不增大时间窗。

US：只补原 `_BUSINESS` / `_RELATION` 简繁体等义词。原生分类器已经接受的“簽署/授權/許可”等语句不再在第二层被简体正则漏掉。原文 span、明确 ticker、两源时间、来源和 standing 合同门均不放宽。详见 US_SOURCE_GAPS.md；没有造出任何 LLY 或公司关系。

## 验证

补丁实际应用后的独立临时测试树：41 passed / 0 skipped / exit 0。
B1 原前像 9/9 复现失败；B2 原 worker 在 B1 修复后的输入树上 4 failed / 4 passed；US 原前像 7 failed / 6 passed。
作者 Linux/Python 3.13.5；上游 HTTP/master/资格/US 为合成边界，原存储、原校验、原分类、原计划事务及磁盘保存/读回实际执行。不是 Mac/Luna 或真实 API/UI 证明。

先读 WORK_HANDOFF.md。Work 负责隔离应用与独立验收，不承担宽泛研发。
所有真实供给、接线、API/UI/natural 状态继续分开；PR9 Draft，Issue8 Open，不合并/部署/启调度。
