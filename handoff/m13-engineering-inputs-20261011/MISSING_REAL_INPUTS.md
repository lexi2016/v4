# 原 M13 真实输入状态与原件合同

本页仅依据原 M13 SOURCE/fixture README 和原接口，列出需要核取的输入类别。没有复制共享诊断原件、Mac 私人操作记录或真实业务目录内容。原 M13 会话此前已有的共享诊断附件未纳入此次 GitHub 交付。

## A. 目标日与来源日、原始输入与待生成输出

今天为 2026-10-11。`target_date=20261012` 是未来的预选目标日，`publication_date=20261009` 是过去的来源公告日。不能要求用户提供未来 12 日公告/行情。应按原 owner 合同和既有 cutoff 使用已经公开的真实来源数据，为 12 日生成预选分析。

必要原始输入是否齐全，按原 catalog、公告正文/材料、来源清单、获取时间、原始/规范化身份及 cutoff/PIT 合同逐项核。没有核到某个必要原始输入时，报告具体项和实际查找范围；不要把所有链条输出都列成用户必须先提供的材料。

analysis、独立 review/decision、owner import、readback 和 publication 绑定属于原 owner 链需要生成或保存/验证的产物。若尚未生成，归原生产入口接续/最小修复任务，不作为必须先由用户交出的输入。保留独立 Reviewer、时间门、同 SHA 消费及原导入/读取语义，不伪造审核、回执或 cutoff。

原 owner 代码把 target 与 publication 分开，publication 未显式指定时用前一个香港证券交易日作为默认来源日；见本页下方精确源码引用。旧 08/07 的 758 件只解决原回归输入，不能直接改标其分析结论为 12 日。

## B. 旧真实 20 项回归的 REQUEST_PATH

旧测试固定 target `20261008` / publication `2026-10-07`，与当前 10/12 业务验收独立。原输入 694 manager + 64 material = 758 文件，其中 624 handoff；body_corpus 为 21,861,605 bytes。33 selected / 54 watch / 75 unassessed 是核原件指标，不能用来造数据。

2026-10-11 后续更新：既有 Mac 任务已找到原 REQUEST_PATH 与全部 758 件，另包已独立核验。真实原件尚未纳入本工程 commit，不能把本目录当作已附真实 fixture。下列保留准确接口与消费者核验合同，不再要求重新寻找已找到的旧输入；其独立材料交接另行记账。

接口依据是固定 SOURCE `V5/src/v5_shadow/announcement_bridge.py:35–63` 的 `_request`。顶层只允许六键：

1. target_date
2. publication_date
3. manager_root
4. materials_root
5. manager_files
6. material_files

不是此前回复示意的 source_identity / run_identity / cutoff 简化结构。

两个 root 必须是真实存在、互不包含、无 symlink 的绝对目录。两个 files 字典是精确相对路径到原 SHA-256 的映射，各 1..4096 项；不允许绝对路径、`..` 和反斜杠。publication 非空时，manager 文件必须含规范化日期下：

```text
workspace_announcements/{target}/eastmoney_date_catalog/{publication}/analysis.v1.json
workspace_announcements/{target}/eastmoney_date_catalog/{publication}/owner_import_receipt.v1.json
workspace_announcements/{target}/eastmoney_date_catalog/{publication}/latest.json
```

manager 其他允许路径严格按原 `_request` 的 dated/handoff 白名单。material 仅允许 `blobs/{64hex}` 和 `index/{64hex}.json`。读取会逐件核 SHA，不能仅交一份 JSON 而遗漏其绑定原件。

找到原 request 后保留原字节、实际路径、bytes/raw SHA，并只读核两字典所指原件的存在性、长度和 SHA；逐项记缺失或不匹配。不搬无关整库，不改旧测试日期，不用 392 修订成果代替 08/07 的原件。

## C. 已齐工程材料不再索取

SOURCE、93 件 consumer overlay、原 e06d 和原 1a699a0 fixture 已齐；stages.py 就在 consumer 原包。先依 ASSEMBLY.md 正确并入同一 SOURCE 并设置两个变量。上述真实输入缺口不等于工程源码仍缺，不应阻断独立的 22 项合成工程分组，也不能由该分组结果代替真实业务验收。

## D. 精确原代码引用

以下都是原 SOURCE ZIP 内 `V5/vendor/<baseline>/v4/manager_research/announcement_analysis.py`，只读核源码，不执行产品：

- `announcement_readback_baseline`：previous_hk_session 第49–54行使用原 contracts.trading_calendar 的 hk_securities 日历；build_product 从946行开始绑定目标交易日与正文来源日；import_product 第1102–1129行验证同目标/来源后事务保存并原 readback；read 第1135–1148行区分 target/publication，并在未显式指定 publication 时采用 PREVIOUS_HK_TRADING_SESSION。
- `announcement_offline_baseline` 和 `announcement_revision_baseline`：对应函数起始行分别为49、969、1125、1158。三份版本保持各自原字节，不因语义一致就相互覆盖。

读取既有 9 日公告与现在重新获取 9 日公告的时间事实不同。任何新获取必须保留真实获取时间，不能倒填到原历史 cutoff。12 日是输出适用目标，不是要求拿到未来 12 日来源数据；历史真实08/07回归结论不得改标为12日。
