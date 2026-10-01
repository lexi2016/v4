# BI-01：公告多版本实例 ID 局部修复

只改一个生产身份表达式。固定前像 95426；原 TS 校验/页面来源 bdc95a3；原 API6726 保留 SHA 不动。新增独立目录，不覆盖旧冻结证据。

- [Mac Work 一次验收及回退](WORK_ONCE.md)
- [引用检查、实跑结果和边界](REVIEW.md)
- [精确补丁](runtime.patch)，完整 [before](before/app/v4/manager_research/workspace_announcements.py) / [after](after/app/v4/manager_research/workspace_announcements.py)
- [前后 SHA](SOURCE_PINS.json)、[测试源码锁](TEST_SOURCE_LOCK.json)、[日志](logs/after.log)

Draft review only；关联 #17 BI-01 / #8。未部署。5 个定向用例通过，修复前跨端红例已保留。Mac Python3.14.6、普通 HTTP/整页浏览器与实际加载字节待 Work 验收。
