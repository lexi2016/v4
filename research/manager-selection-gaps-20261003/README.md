# V4 公告与美股研究选股问题包 R1 — 20261003

续办 GitHub Issue #8：https://github.com/lexi2016/v4/issues/8 。这是诊断与修复输入，尚未实施修复或运行本批测试。

## 冻结基线
活动 R9 manager-readback-r9-20261003-issue24-r1，目标日期 20261002，10月3日事后动态审阅。#22 成功原因文案、#24 大计划保存回读已独立验收并部署，不重做。完整333MB GET不重复上传；evidence/FROZEN_SELECTED_FIELDS.json 是带原始SHA的精确子树，非完整响应。source/ 提供活动R9全部manager_research模块与相关reader、日历、测试。SOURCE_MANIFEST.json逐文件注明来源与是否等同当前工作区；不得拿工作区新增D-1 fallback解释冻结运行。

## 已证实的问题与边界
1. 10月2日港股证券开市、港股通休市。R9 membership 返回 CANNOT_CONFIRM，具体缺失 universes/20261002/HK_CONNECT_FULL_MARKET.json；root已经绑定。正式Connect选股应表达当日不适用，不能伪造工件或用D-1成员升格目标日正式资格。
2. 公告官方797文档/411代码，目标日243且PARTIAL；9条正向观察涉及5股并在新鲜度窗口内，不能解释成全市场无利好。空membership使Connect evidence_view过滤所有研究注意力输入；同时research_attention显示READY且未充分传递缺口。官方HKEX观察与东方财富selection输入分开，后者仅2条过窗旧样本、body_material_count=0且非穷尽。恢复观察卡不自动获得正式focus资格。源覆盖和未知资格应明确显示。
3. 84条US关系全部拒绝于ISSUER_ACQUISITION_TIME_MISSING_OR_INVALID。GET不能判断available_at/retrieved_at哪项缺失，也不能证明原始owner缺失还是投影遗漏。先核现有owner中1条代表source ref；原始合法时钟存在才修映射，缺失则保留CANNOT_CONFIRM并给owner缺口。不得用发布时间、mtime或归档生成时间补造采集时间。样本另缺主体明确US关系，时钟修复不能替代关系/市场证据验收。
4. 公告与US研究lane需分别解释；不要把membership当成所有空列表的唯一根因。研究/观察/正式结果分开。不得扩大到全港股或强塞股票以通过非零验收。

## Chat交付要求
以source/活动基线作最小修复。先给复现、真实根因及精确修改路径；需要原owner单条记录时明确缺失字段和source ref，不另抓同源、不造producer。可优先交付休市状态和研究缺口表达；数据问题证据不足时明确blocked，不写假数据。
返回完整ZIP、runtime.patch、修改后文件、逐文件before/after SHA、针对性测试及结果、部署/回滚说明。必须覆盖：休市正式NOT_APPLICABLE；未确认membership不变正式资格；合法研究观察按约定保留且显示缺口；真实时钟映射与缺失时钟两支；时间通过但关系缺失仍拒绝；#22/#24回归不退化。不得宣称自然时段或封存验证通过。
禁止变更Stage/BUY/Vibe8910、服务/历史状态/调度及来源边界；RESEARCH_ONLY=true，production_allowed=false，buy_gate_updated=false，orders_sent=false。本地后续由Luna Writer落地、独立Luna Reviewer验收。

## 非本批范围
71,830条pending-review造成体积膨胀仅作为背景，不顺手重构性能。目标日52份文档归因未知和非穷尽覆盖继续标明未知。无需重跑已完成的保存回读、广泛测试或采集。

## GitHub完整包重建
按part1、part2、part3、part4顺序拼接 PACKAGE.zip.b64.part* 的文本后base64解码为ZIP，校验PACKAGE_RECEIPT.json中的字节数和SHA256。包内source/和evidence/均为完整文件，无需重抓333MB响应。
