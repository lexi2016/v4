# BI-01 引用审查与定向证据

修复前 Store/history 合法保留三实例，投影 ID 只取 source/art_code，原 TS 公告 validator 抛 EASTMONEY_HK_DOCUMENT_IDENTITY_INVALID。修复后 ID 使用原 canonical digest([source, code, art_code, body_sha256])，捕获时间/run_id 不参加，重复采集稳定。未截断 hash。

引用扫描：`logs/event_id_references.txt` 包含在 bdc canonical + 95426 后像 + preserve 精确依赖装配上的全部 event_id 文本命中（v4 和 apps）。还检查了相关 DOM key/选择器，没有发现消费者重算旧 source/art_code ID 或要求其固定值。

| 消费点 | 结论 |
|---|---|
| eastmoney_run_history.read_history | 单一来源 EASTMONEY_HK 经原校验后按 symbol/art_code/body SHA 去重；无需再改或丢版本，原 occurrences 保留 |
| workspace_announcements.read/read_selection_inputs | 普通 read 返回历史文档；selection 按发行人/art/body 去重；只改投影身份 |
| announcement_materials.mirror_material | material_id 已含发行人/art/body；original_article_id=doc.event_id，owner_document 深拷贝自然继承；测试核唯一性及引用相等 |
| announcement_observation.event_lane | 逐条深拷贝合法文档；不按 art_code 折叠；实际输出喂原 TS 校验器 |
| research_evidence / workspace_discovery / workspace_briefing / evidence_identity | 读取或传递 event_id/original_article_id；保留既有归组政策，不变更 US 关联/BI-02 |
| managerWorkspace.ts | Eastmoney Set 唯一性保护保留；官方文档 find(event_id) 属于单独 official_documents 路径，未改 |
| manager-selection/announcementObservation.ts | data-eastmoney-announcement、data-eastmoney-body 直接使用新 ID；原 DOM 渲染器已验证三份完整正文 |
| ResearchImpactList.vue / ManagerSelectionView.vue | 前者 timeline key 取 event_id；后者 material key 使用 code/id、其它行用既有 stock/candidate 身份；不硬编码 Eastmoney ID 算法 |
| event_source/catalyst/selection contracts | 其它来源独立 ID/关联合同，未扩大修改 |

art_code 字段已可用于逻辑归组；本次没有新增无消费者的 logical_event_id。原 official/HKEX ID 不改。原保存产品不含这个派生 event_id，不迁移历史。外部缓存/旧导出中的旧 ID 不自动重写，需重新读回。

## 实跑

最终可复现命令为 WORK_ONCE 中 tools/replay.py。精确记录在 logs/receipt.json、before_receipt.json、import_receipt.json、junit.xml。

- before：1 failed，4 passed；失败来自原 TS validator 的重复 ID（logs/before.log）。
- after：5 passed，0 failed（logs/after.log）。同发行人同 art 不同正文；不同发行人同 art 同正文；重复同版本 ID 稳定且四 captures 合为三实例、occurrences 1/1/2；历史 cutoff 仅旧版；真实重复 ID 被拒；原 DOM 三份全文；selection material 引用/ID 唯一；读不写不请求。
- 4 个定向原负例：body 改而 SHA 未改、ref SHA 错误、raw blob 损坏、保留 observation 损坏，坏 run 拒绝而好 run 留存。
- runtime.patch 正向结果逐字等于 after，逆向 check 成功，测试前后源码 hash 不变。95426 preserve 九文件 SHA 全部匹配。

测试边界：合成 master/HTTP 响应；使用原 collect parser、MaterialStore、ManagerResearchStore、commit/history、校验和投影。为了模拟同 URL 的合法新正文，fixture 在 capture_eastmoney 调用边界设置原 force=True，避免原无限期内容缓存继续返回旧版本；没有修改生产缓存政策、mock 来源校验或伪造已验证产品。PDF 仍由原 manifest 校验后的私有 pypdf 解析。页面是 jsdom 执行原渲染函数，不是桌面浏览器。TS 使用 Node 原生类型擦除执行原文件，没有复制/改写 validator。

装配时发现冻结 handoff 少了 vendor py.typed/license；按原 manifest 完整 SHA 补齐，license 随测试依赖提供，空 py.typed 在固定 git blob 中。未禁用原校验。最初工具闭包漏带原 calendar JSON 导致离线回放报缺文件，现已加入锁并重新通过；没有修改日历。本地临时环境装过 pypdf/pymupdf，但业务执行仍使用原私有 vendored pypdf，其加载路径见 import receipt。

未执行旧全量 14/27/33；未做完整 workspace HTTP/validateManagerWorkspace 全入口、整页浏览器、Mac Python 3.14.6、实际 release 绑定、真实来源、采集、自然运行或部署。这里的 3.12.14 通过不要求 Mac 降级，也不代替 Mac 的实际服务解释器验收。Issue17/8 不自动关闭。
