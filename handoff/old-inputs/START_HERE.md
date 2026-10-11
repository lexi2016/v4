# M13 旧 08/07 真实回归原件

本目录补交原 M13 回归缺少的原 request 与 758 个绑定原件。它是工程材料 commit `166a106fd54d346346371569a3590d3adc978a7a` 之后的独立增量，保留工程包、旧数据、日期和身份，不重传工程源码，不修改 main/V4。

## 下载与核验

- [M13_ORIGINAL_758_INPUTS_ONLY_20261011.zip](M13_ORIGINAL_758_INPUTS_ONLY_20261011.zip)
- 9,500,208 bytes，764 个 ZIP 成员
- SHA-256：`a3ee5b39961dfdae5ce86c46e82ef530580e0cafedd54953b4e298029de2e5fa`
- Git blob SHA-1：`77d1fca03d9d9b9eddff9521c8598923ff539026`
- [MANIFEST.json](MANIFEST.json)：原 request 声明的逐件路径、长度和 SHA
- [VERIFICATION.json](VERIFICATION.json)：本次静态完整性结果

ZIP 共有 759 个原件（原 request + 694 manager + 64 material）和 5 份新交接文档/清单。原件逐字节保留，758/758 文件 SHA 匹配、CRC 通过。仅包括旧 M13 回归输入，不包含 10/12 缺件诊断、共享 M18 私人操作证据或此前被排除的诊断原件；与该诊断任一成员同字节重叠为零。

## 正确装配

1. 解压到新的独立目录，读包内 START_HERE.md 与 ASSEMBLY.md，先核六键原 request 及全部 758 个 SHA。
2. 原 request 保存在 original/request.json，138989 bytes，SHA-256 `817c2ac013db29d7fb6c560442edaaad7c583ecf8bb425252cc744fcd1c11b7d`；target_date=20261008、publication_date=2026-10-07。原 Mac 根保留原样。
3. 跨机器消费时，只能按 ASSEMBLY.md 另存清楚标注的“仅路径迁移”派生 request，改 manager_root/materials_root 指向解压目录；原 request、日期、两组路径→SHA 字典保持不变。派生文件不是历史回执。
4. V5_ANNOUNCEMENT_REQUEST_PATH 指向消费环境正确的 request 实际绝对路径。配合[固定工程交接](https://github.com/lexi2016/v4/blob/166a106fd54d346346371569a3590d3adc978a7a/handoff/m13-engineering-inputs-20261011/START_HERE.md)中的正确 SOURCE + consumer overlay 和两个独立合成 fixture 使用。

包内“仅在本地准备/没有上传”是原封存说明的历史状态，ZIP 保持同一 SHA；本次 GitHub 发布状态以包含本页的固定 commit 为准。

## 日期与执行边界

这批 08/07 真原件用于旧 20 项回归，不能重标为 10/12 预选结果。今天 10/11，未来的 target_date=20261012 与过去的 publication_date=20261009 必须分开；当前预选应基于原 cutoff 前可用的真实原始数据，由原 owner 生成分析、独立审核、导入和读取输出，不要求未来 12 日数据，也不能把待生成输出当作用户必须先提供的输入。任何新获取保留实际时间，不倒填历史 cutoff。

本次只核文件，不运行产品/pytest/fixture、采集、审核、导入、发布或交易。文件齐全不等于产品测试通过。
