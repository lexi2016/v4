# 智通来源与覆盖边界

DIYgod/RSSHub 锁定源码：[zhitongcaijing route at 897559b134a4edfcae1178fb61b588ffbdc5f937](https://github.com/DIYgod/RSSHub/blob/897559b134a4edfcae1178fb61b588ffbdc5f937/lib/routes/zhitongcaijing/index.tsx)。上游项目许可证为 [AGPL-3.0](https://github.com/DIYgod/RSSHub/blob/897559b134a4edfcae1178fb61b588ffbdc5f937/LICENSE)；只引用来源，不复制整份代码。

该版本的栏目映射为 `announcement → announcement`、`hkstock → content/hkstock`、`research → research`。路由读取对应栏目页的 API 形态 `https://www.zhitongcaijing.com/{栏目路径}.html?data_type=1&page=1`。试验中扩展分页时沿用同一 API，将页码改为 `N`。RSSHub handler 本身固定请求第 1 页，默认最多输出20条；`limit` 只截取该页返回项，不是分页。它将 `create_time`（缺失时回退 `original_time`）映射为 RSS `pubDate`，不能把这个字段当作权威发布时间。正文选择器观察为 `.digetst-box`、回退 `.telegram-origin-contentn`、以及 `.news-body-content`。

上述是已检查的上游方法与字段，不代表此环境运行或部署了 RSSHub。2026-10-14 的本地一次性试验是基于该路径的有限读取，不是可直接执行的通用采集器。优先复用已有同源缓存/权威链；没有可复用结果时，只按现有读取路径和本轮授权读取。上游返回浏览器验证页、权限拒绝、正文错误或超出可用预算时，停止绕过尝试，记录具体缺口。

分页不保证发布时间单调。试验页6–7出现非单调顺序；因此不能遇到一条窗口外的旧记录就停止。应继续到可观察的空页/结束信号，或明确记录预算边界、已扫页数、重复条目和错误。2026-10-14 的试验到第25页仍有20条、没有结束信号，虽然扩展页未发现新窗口内 ID，完整集合仍为 `CANNOT_CONFIRM`。只扫描 `announcement` 栏目不能代表 `content/hkstock` 或 `research` 已覆盖，也不能代表全市场。

每个来源独立报告“已观察、部分覆盖、未读取/待核”，包括入口、栏目、页码、时间字段、采集时刻和缺失原因。汇总只计去重后的底层事件；原始 article ID、跨页重复和跨栏目重复可用于追溯，但转载不是新的独立事件。
