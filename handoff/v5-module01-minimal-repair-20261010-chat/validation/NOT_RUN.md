# 未执行与尚未提供的证据

本表区分“runner实际失败/skip”和“业务验收未执行”，没有将缺原件改成通过。已有GitHub源码已按固定对象补齐，以下不要求重发整库。

## 真实 Mac 业务与落地

| 验证项 | 状态与精确输入 |
| --- | --- |
| 原392公告决定、原正文/catalog/registered handoff/owner receipt | NOT_RUN；原件留在Mac。仅引用输入交接中的392分类和run/SHA，不重新采集/分类或伪造。 |
| 原 `announcement_offline_owner` 绑定 happy path | NOT_RUN；需要Mac原binding请求及它引用的原目录/文件SHA。本批合成经理fixture经过已import manager/materials输入，不冒充该Mac路径。 |
| Mac经理run `5b4feaf7ef7d4d13bec639e90b6d3db0` | NOT_RUN；需要原request、原store、同run产品及terminal；历史回执SHA `56556a67...` 只是期望校验值。 |
| 活动Mac文件前像/完整前端根/监听进程 | NOT_RUN；影响具体安装和切换，不阻断对固定F交代码。用操作人实际观察填表，不猜覆盖路径。 |
| 真实module/gateway API、静态bundle、内置浏览器普通页 | NOT_RUN；必须匹配上述真实run/SHA、真实日期和release，不能使用本包合成HTTP结果或旧PARTIAL/0 portable data代验。 |
| 候选启动、单窗口切换、现场回退 | NOT_RUN；本会话未操作Mac服务，代码审查不批准部署。 |
| 自然时段、盘前资格、三策略、18模块 | NOT_RUN；真实回看生成时点不改成当日盘前，自然运行须独立验收。 |

## 原测试入口缺原件

| 原测试文件/组 | 缺失对象及实际结果 |
| --- | --- |
| Python `test_manager_announcement_binding.ManagerAnnouncementRealOwnerTests` | setup缺 `V5_ANNOUNCEMENT_REQUEST_PATH`，原runner ERROR `V5_ANNOUNCEMENT_REQUEST_PATH_REQUIRED_NO_SKIP`。需要对应Mac原公告request。 |
| Python `test_manager_offline_announcement.OfflineAnnouncementOriginalChainTests` 6项 | 原代码skip：指定固定1a699a0 upstream fixture bundle不在其期待位置；本批新原owner合成fixture不替代它。 |
| `managerWorkspace.currentRecovery.spec.ts` 3项 | 原真实`.result.payload` envelope，例如原manager-read-publication.json；runner ENOENT。用原 `V5_REAL_CURRENT_RECOVERY_RESPONSE` 指向Mac原件。 |
| `managerWorkspace.announcementReview.spec.ts` 4项 | 原两个公告日完整保存payload；runner ENOENT。保持原fixture变量与格式。 |
| `catalystObservationPanel.runtime.spec.ts` 2项 | 原manual observation fixture binding与原Eastmoney workspace；最终受影响组仍2 FAIL，不补造100行。 |
| `researchSelectionLedger.spec.ts` 6项 | 原`issue8R2.ownerObservations.json`；runner ENOENT。 |
| `actualResearchSelectionProjection.spec.ts` 1项 | 原689行owner projection；runner ENOENT。 |
| `workspaceAfterReadback.spec.ts` 1项 | 原Eastmoney workspace；runner ENOENT。 |
| `cloudRecoveryContract.spec.ts` 3项 | 指定原empty/cloud恢复响应artifact缺失；不使用本批四条非空响应代替。 |
| `cloudActualReadback.spec.ts` 1项 | 原20261012 cloud auto artifact缺失，且该test要求无股票行；不适合拿真实392响应套用。 |

17项前端原owner/Mac材料与4项显式cloud artifact依赖未改来源、未增加skip。两项旧合成生成测试已按用户新合同修正通过，不留在未解决业务缺口表中。

## 现有接口能力边界

1. `publish_read.py --expected-run` 只核预期身份；若auto当前返回别的run，拒绝发布，不能改latest/new store/refresh拼回旧身份。
2. 原publisher初次只生成manager记录，独立announcement三个route初始503。现有`announcement_analysis_api`可在原binding和两次原reader产品SHA一致时发布analysis显式日/真实默认日；它不发布另外的`/announcements`或`/selection`。详见Mac步骤，不据此声称所有公告独立入口通过。
3. 本批header门控的是经理计划生成。原公告增量更新属于其他入口，本批没有把全部旧更新按钮统一改造，也没有为V5新增writer。
4. 兼容旧POST若请求响应丢失，当前协议未事先向客户端提供可信run；UI只能保持结果未知，要求原owner定位run核验，不自动重试或借latest充当其终态。

上述边界不需要新增operation_id/store、放宽来源SHA或重新构建完整经理。若Mac发现确实阻断本批非空普通页面，应按回传模板提交具体请求、函数、run/SHA和原错误，交同一代码修复链处理。
