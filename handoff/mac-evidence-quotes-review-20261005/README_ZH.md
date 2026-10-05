# PR26 Mac 独立隔离验收

固定输入 commit fb23fd159ef5201eef4eafa67c14f247d57c7c98；R11基线640c77a7f019a1a211faea937b70cc10e4329afc。已读其 README 后从实际活动 R11 release 复制源码，非 canonical 覆盖。候选身份及完整 before/after SHA 见 IDENTITY_AND_PATCH.json；活动/canonical/plist 在测试后保持原字节，810 个所复制源码无活动漂移。并行 Work 生命周期不能由文件证明，保留 CANNOT_CONFIRM。

候选只新增原补丁的7行显示逻辑：COMPANY_MATERIAL标题、原样摘录或明确缺失说明，现有textContent与链接过滤保留。未改正文解释、事件判断、排序、推荐、Stage、BUY或Vibe。

Mac服务Python3.14.6 / Node24.19.0 / Vitest4.1.10 / TS5.9.3 / jsdom28.1.0。复用已有依赖的隔离副本，锁文件相同，无安装。

| 检查 | 实测 |
|---|---|
| 原交付新增合成测试 | 11 PASS；真实Python producer→decoder→jsdom |
| 四套既有前端 | 101 PASS、1 FAIL；无跳过 |
| before基线针对失败项 | 同一断言FAIL；9项因-t过滤SKIP |
| renderer与原新增测试严格TS | exit0 |
| 既有保存真实9/29样本 | 1 PASS；19条摘录与标题逐字DOM读回、30张可见卡、输入不变 |
| 实际浏览器视觉、在线API、自然时段、部署、合并、全量构建/测试 | NOT_RUN |

失败位于catalystObservationPanel.runtime.spec.ts:347：旧Eastmoney样本测试要求“东方财富港股公告”，R11的before与本候选均未显示该文字。Mac实际有原样本，不再是云端“文件缺失”阻塞；保留真实FAIL，不删断言或按通过处理。后续owner先核此旧展示合同是否仍有效，再决定修复/更新验收，不能由本显示补丁宣称全前端通过。

保存样本SHA与摘录SHA见SAVED_SAMPLE_READBACK.json。只读已有workspace_after.json，没有重抓、重新解释正文或上传原始价格/摘录/账户数据。jsdom不等于实际页面视觉，不证明官方首发、当前事件、PIT、资格或选股成功。原Work R11目录结果保留，未重验该目录。

原两个新测试及before/after包可复用输入固定commit的handoff/research-evidence-quotes-20261005。此目录提供同一runtime.patch、候选目标文件、补充保存样本读回脚本与精简实测回执；既有失败完整日志仅留本机，远端仅摘要，排除真实行情长输出。

最小上线步骤（未执行）：owner重新核活动release目标before SHA与并行状态；裁决旧测试失败是否阻断此次发布；在隔离页面完成实际视觉验收。之后才由owner按原发布流程纳入该单文件，保留after/before反向补丁回滚及原R11验收。任何活动漂移先做新diff。此回执不授权切服务或部署。
