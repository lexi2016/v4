# V4 经理普通 UI 合同修复：BI01 / BI02

固定前像：`2ef8cd8da081afd5243744b943c5d62cda932c51/research/manager-current-gaps-20261001/source/`。只改 `SOURCE_PINS.json` 所列五文件；不覆盖 configured_release_reference、不叠旧 main/PR18/95426，不改 R3A、资格、日历、Stage、BUY、Vibe、服务或调度。

第一批 owner：Chat 研发与交付；本地 Codex 在当前完整隔离副本应用和风险定向独立验收。BI01/BI02 是本批 P1 跨端可用性修复；BI04 完成静态定位、建议后续单独最小修复。数据准入、候选集成及自然业务验收是后续批次，不是本批代码开发前置门。

## 实际代码

- `workspace_announcements._project_eastmoney_hk`：event_id 改为 `digest([source, issuer, art_code, body_sha256])`；同一实例重复投影去重。继承 PR18 的实例 ID 思路，但对本包精确前像重新适配。采集时钟不进实例 ID，不删除旧 run，不抹去合法正文修订。原 event_id 自动传给 material original_article_id、后续 evidence 和现有公告 DOM key。
- `issuer_us_relations.material_us_relations`：只在现有主体/来源/时间/有效期门已通过后，输出既有 `semantic_status=ACCEPTED`。没有新增 STANDING_RELATION semantic 枚举。
- `research_attention`：固定 `why_now_readable` lane 标签不再混入自由说明；方向、风险、原文、观察条件和撤销条件保留在既有 research_relationships。
- `managerWorkspace.ts`：复用原完整公告文档校验，兼容公司材料的镜像证据类；native 个股和行业同用来源/时钟/当前关系或 standing 有效期合同。镜像不是正式首次发布时间，standing 不是新催化。原个股/行业旧分支保留；双来源独立性、主体卡绑定、取得时间、过期合同负例仍拒绝。standing 的原发布时间可在短窗口之前，但必须与已准入关系原时间相同；不改 acquired 排序时钟。
- `researchAttention.ts`：用真实 DOM 显示 research_relationships，绑定到已通过校验的该卡对应 evidence。文本使用 textContent，来源 URL 保留既有协议限制。不删除有用说明来凑 validator 通过。

`runtime.patch` 是可直接检查、应用的完整运行增量。下载交付含完整 before/after；GitHub 的精确补丁在本地应用后生成相同五个后像，SHA 可逐项核对。原 40-file 输入核验、导入身份和测试原日志随包保留。

## 实际证据范围

新增同一组 39 项：原前像 14 failed / 25 passed；改后 39 passed，0 error / 0 skipped。TypeScript strict 编译通过。Chromium 执行原 `requestManagerWorkspace` → `validateManagerWorkspace` → 原公告/研究卡 DOM renderer；不是手写 TS 正例。

资格/master/文章/行情/HTTP 为明确标记的合成上游；全 owner IO/assembly 被测试边界替代，但 `_project_eastmoney_hk`、`mirror_material`、原主体分类、`material_us_relations`、关系层、研究排序、原 GET envelope wrapper 和 TS parser/renderer 实际执行。原 MaterialStore 网络响应重读、完整服务、真实 8873、整 SPA/CSS 和自然采集均未执行。

阅读 `WORK_ONCE.md` 进行一次隔离采用；阅读 `BI04_AND_CALENDAR.md` 看静态结论和最小缺项。`TEST_REPORT.md` 明确环境、依赖、异常与验收边界。Issue8/17 不关闭。
