# 待删除：旧版单股归档

本批将旧默认 daily.html 实体原字节移到 legacy-daily.html，保留SHA和回退。
当前已承诺的显式 /research-panel/legacy-daily.html 仍映射并读取本文件，
因此它是待退役归档，不可在alias仍启用时直接永久删除。

虚拟URL保持在研究根目录，原相对JS/图像资源继续由既有allowlist/hash校验。
默认 daily.html 只转新版workbench并保留请求日期。旧JS/renderer仍可能被此归档、
原式图和其它历史归档使用，不随HTML一并删除。

恢复旧默认入口必须另有用户授权：原字节可从本文件恢复到daily.html，
同步改静态manifest和mount迁移规则，走原发布锁/CAS；不覆盖数据或已保存结果。
