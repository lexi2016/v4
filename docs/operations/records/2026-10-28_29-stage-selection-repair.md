# 2026-10-28—29 V4 阶段选股修复记录

记录截止：2026-10-29 15:23，上海时间；后续追加实际结果。此处是事实账本，不能作为未来动作的现役 CAS/PID/期限。

## 用户目标与后来明确的处理规则

- 修复 A/HK 完整阶段链路，安全上线，按各阶段实际结果验收，保护其他任务和原 5073 只股票数据。
- 用户多次要求继续直接修复，不只给排查报告，不反复向其他用户会话发送材料。
- 2026-10-29 新明确决定：缺回执时重新抓当前快照，以后默认如此；原阶段、实际采集时刻、晚到标记和降级原因必须清楚，原失败不覆写。
- 当前快照观察可以完成降级交付；原阶段自然/PIT/正式 selected 结论保持独立。
- 用户同时要求将整个修复过程记入 V4 SOP。

## 2026-10-28：原始故障和候选修复

来源：[用户原交接](/Users/lexi/.codex/attachments/e2ab8172-31d9-4307-a7d0-c62c364955b2/已粘贴的文本.txt)，原快照时间12:42；以下首先是该时点已记录事实，不声称当时已部署。

| 故障/尝试 | 当时证据与处理 | 结论边界 |
| --- | --- | --- |
| 09:25 A 竞价无原始 manifest | 原273候选，272条Futu源时刻09:30晚于09:25捕获；BJ920509未认证；TDX无有效报价 | 正确拒绝未来时刻；午间重试不能证明原竞价成功 |
| A上下文异常连带HK失败 | HK分钟原件100/100，但共同异常路径使其没有独立阶段结果 | 修复市场隔离；原始行存在不是已选股 |
| PARTIAL研究来源整批拒绝 | 原09:00来源20页仍has_more=true；reader仅接READY/READY_EMPTY；完成时刻与SHA认证缺口 | 保留PARTIAL并贯通合法部分；不能伪造原可用时间 |
| 单个池/Stage7/复盘缺口 | 有可读有效成员，另有source-only、不具资格或缺失子池 | 有效池继续、坏来源隔离，不全局抹掉成员 |
| 首轮独审FAIL | HK CSV OSError未被窄异常捕获，仍可阻断A | 记录P1及返修；不把6个隔离测试当真实API/自然PASS |
| Main attestation语义问题 | PARTIAL认证失败却返回过强READY；写前取generated/published可能跨cutoff | 降低状态、保留缺口，补真实完成证据 |
| 名称修复R6/R7 | 原交接时有source-only独审候选，页面仍可见代码缺名称 | 只记当时状态；不能凭候选PASS声称现役名称已修复 |
| Main/Stage安全切换及API身份 | 用户回传R7 helper执行；后一次API身份helper返回EXPIRED | 保留各自事实，过期helper不重放；回传本身不代替全组件读回 |

原交接中Stage-only r1/r2仍为候选或REVIEW_ONLY_NOT_EXECUTABLE；旧PLAN、旧owner及脏工作树不能整体覆盖。原程序缓存/失败观察被保留，没有清理其它任务。

## 2026-10-29：实际定位、发布与结果

| 时段/阶段 | 实际动作或结果 | 结论 |
| --- | --- | --- |
| 08:30/09:00 Main | 同日EXPECTED_MISSING占位与研究materialization碰撞；重试生成新的封存身份 | 既有严格CAS恢复与同代码/同来源幂等复用修复，未降低PIT |
| 早盘09:25 | 56条Futu未来09:30被拒，2只BJ不支持；原TDX连接后空回包 | 无有效native原件；晚间/午间数据不冒充原竞价 |
| 09:35/09:40/09:45 | 每阶段原raw58 READY，无A正式selection；原09:00三条dispatch均FAILED | 原owner校验缺completion witness；内层authority成功不能盖过工作项失败 |
| 10:30 | 原版本Main0bfa/Stage00c6实际A10 WATCH_ONLY，原raw58/原件与owning启动链可核 | 发生在本次Main部署前，不作为本补丁因果证据 |
| 约12:25 Main R4 | 原五标签完成切换，guardian正常释放；Main528a，Stage0d15；原保护61/61 | 当时部署/API/代表UI完成；全七阶段自然验收仍待完成 |
| 随后API页面发布 | 另一任务更新API/UI，后为daily-numeric283-r2 | 本任务保留其成果，禁止用旧API计划覆盖 |
| 13:00 | 原新Main定时任务SUCCEEDED，输入/出版/原完成见证齐 | 第一个可验证的部署后原小时结果 |
| 13:15 | 原Stage0d15实际A raw58、A观察10、HK10；raw3/3、selection5/5，原attempt/caller/launchd事件匹配 | 原自然运行产出已证明；业务PARTIAL与866缺口、PIT/自然独审标志不升格 |
| native控制R1预检 | Main ps的UTF8与原Live.identity LC_ALL=C转义不同，身份比较拒绝 | 无动作；R2只校正locale捕获与本地路径，严格身份比较未放宽 |
| native认证335ca0ed | 5分钟请求过期，guardian ABORTED_BEFORE_ANY_ARM | 0服务/数据动作，3锁释放，只结束本批过期认证客户端 |
| 14:23 native切换f4fbbcd8 | 新鲜认证完成，API/collector/Stage/precapture四role DONE；Main保持73799 | guard正常释放，新源1e816...、图478c、loaded/API绑定验证；不等于真实选股reader已通过 |
| 14:37左右发现包装错误 | 新Stage清单fe725的984条inventory漏kind=file，原reader报RESEARCH_RELEASE_CODE_OR_CONFIG_DRIFT | 本批打包错误。服务健康/封装哈希/独审遗漏了真实消费合同；此前上线完成口径过早 |
| metadata R1 | 候选be16仅补kind及aggregate/app_files，两plist只换manifest SHA；原fe725完整保留；2新fixture与候选overlay通过 | 独审PASS，但14:54期限已过；没有执行，不用秒级TTL抢窗口 |
| metadata R2 | 控制/候选/4份plist不变，仅6路径及新15:25期限；原同Reviewer参数增量PASS | 原15:00任务自然完成后才尝试，300秒间隔保留 |
| 15:00原任务 | Stage A raw READY、正式A0，明确CODE_OR_CONFIG_DRIFT，HK10；Main整个dispatch FAILED，内层hourly SUCCEEDED | 原失败保留，不改成自然成功；跨层状态必须分别记录 |
| 15:07后预检 | 发现其它任务已更新API，以及Main有新健康子任务 | 0动作停止预检，刷新身份，等健康任务自然完成；不回滚他任务API |
| 15:14:01—02 metadata修正 | 568107d5完成两idle标签bootout、3文件精确CAS、bootstrap；无需新管理员认证 | 真实无overlay reader1300/1400见证通过，0900继续拒绝；Main/API/collector/图保留 |
| 15:19用户要求重抓 | 原58候选，只读Futu当前快照返回56有效；BJ920249/920455拒绝；源时刻全部15:00 | 已取得真实当前观察，尚非V4阶段正式选股 |
| 15:23后置核对 | 实际loaded/env、当前API/graph保留，原61保护项一致 | 包装兼容性修正已上线；新默认快照降级及页面接入仍在实现 |

## 已解决、尚未解决

已实证解决：
- Main占位恢复与同来源重试的源修复已部署，13:00/13:15链路有原自然结果。
- native原窗口仅对缺失支持代码最多3次、间隔0.5秒原snapshot补读，真实截止/源时刻/拒绝规则保留；其代码已部署。
- 清单kind=file遗漏已以可追溯元数据修订修复，真实消费者恢复通过。
- 其它任务API/页面、Main和原5073数据保护项保留；本轮61/61一致。

仍未完成：
- 原10月29早盘正式selection及09:25自然结果不能补造。
- 新用户默认快照降级：源数据已重抓，原producer/API/UI实施及真实展示待完成。
- 下一自然窗口七阶段及约定收盘链仍需按原结果或明确降级结果验收。
- 最新一次浏览器控制报browser.user unavailable，不能用API成功代称新UI已验证。
- 本文件和SOP的存在不等于自动降级代码已生效。

## 本轮必须避免重犯的具体错误

1. 先调用真实消费者验证manifest契约，再把服务启动称为功能恢复；kind、size、SHA、身份和源绑定都要完整。
2. 优先组合必要变更，不把一次修复拆成多次认证；已空闲的日历任务能用原审核的同UID路径时，不重启无关常驻服务。
3. 预检失效/窗口关闭就保留证据，下一窗口只更新必要参数；不重复全套测试或旧认证。
4. 源码PASS、包PASS、DEPLOYED、API、UI、原自然运行及补采观察分别写，不能用阶段总卡片/HK行掩盖A0。
5. 遵循用户新增快照降级规则；缺回执时交付真实当前观察，不能一再止步于缺回执报告，也不能造历史成功。
6. 不用删除旧目录替代服务配置切换。定向核对的6个前身中2个仍为现役API/collector依赖、4个仍被证据/回退引用，当前0个可直接删除。

## 可机器追溯的证据

本任务证据根：
/Users/lexi/.codex/worktrees/v4-stage-sync-20261028/v4_app/docs/handoffs/v4_a_chain_completion_20261028/online_completion_20261029/natural_repair_20261029

- Main原发布：[STABLE_ONLINE_HANDOFF_R4.json](/Users/lexi/.codex/worktrees/v4-stage-sync-20261028/v4_app/docs/handoffs/v4_a_chain_completion_20261028/online_completion_20261029/natural_repair_20261029/STABLE_ONLINE_HANDOFF_R4.json)
- Main源独审：[SOURCE_REVIEW_R1_R2.json](/Users/lexi/.codex/worktrees/v4-stage-sync-20261028/v4_app/docs/handoffs/v4_a_chain_completion_20261028/online_completion_20261029/natural_repair_20261029/SOURCE_REVIEW_R1_R2.json)
- 原13:00：[ORIGINAL_1300_RESULT.json](/Users/lexi/.codex/worktrees/v4-stage-sync-20261028/v4_app/docs/handoffs/v4_a_chain_completion_20261028/online_completion_20261029/natural_repair_20261029/1300_capture/ORIGINAL_1300_RESULT.json)
- 原13:15：[RESULT_SCOPE.json](/Users/lexi/.codex/worktrees/v4-stage-sync-20261028/v4_app/docs/handoffs/v4_a_chain_completion_20261028/online_completion_20261029/natural_repair_20261029/1315_capture/RESULT_SCOPE.json)
- 当前清单失败：[CURRENT_STAGE_TRUSTED_READER_ACTUAL.json](/Users/lexi/.codex/worktrees/v4-stage-sync-20261028/v4_app/docs/handoffs/v4_a_chain_completion_20261028/online_completion_20261029/natural_repair_20261029/morning_recovery_20261029/CURRENT_STAGE_TRUSTED_READER_ACTUAL.json)
- 早盘原件/回执：[RECOVERY_DISPOSITION.json](/Users/lexi/.codex/worktrees/v4-stage-sync-20261028/v4_app/docs/handoffs/v4_a_chain_completion_20261028/online_completion_20261029/natural_repair_20261029/morning_recovery_20261029/RECOVERY_DISPOSITION.json)
- metadata独审：[INDEPENDENT_REVIEW_PASS.json](/Users/lexi/.codex/worktrees/v4-stage-sync-20261028/v4_app/docs/handoffs/v4_a_chain_completion_20261028/online_completion_20261029/natural_repair_20261029/morning_recovery_20261029/manifest_metadata_r2/INDEPENDENT_REVIEW_PASS.json)
- 真实reader/保护：[POST_EXECUTION_READBACK.json](/Users/lexi/.codex/worktrees/v4-stage-sync-20261028/v4_app/docs/handoffs/v4_a_chain_completion_20261028/online_completion_20261029/natural_repair_20261029/morning_recovery_20261029/manifest_metadata_r2/POST_EXECUTION_READBACK.json)
- 新抓快照：[CAPTURE_RECEIPT.json](/Users/lexi/.codex/worktrees/v4-stage-sync-20261028/v4_app/docs/handoffs/v4_a_chain_completion_20261028/online_completion_20261029/natural_repair_20261029/snapshot_recovery_r1/current_capture/CAPTURE_RECEIPT.json)
- 退役依赖：[RETIREMENT_REFERENCE_BOUNDARY.json](/Users/lexi/.codex/worktrees/v4-stage-sync-20261028/v4_app/docs/handoffs/v4_a_chain_completion_20261028/online_completion_20261029/natural_repair_20261029/native_window_r1/RETIREMENT_REFERENCE_BOUNDARY.json)
- 持续状态：[CONTINUATION_STATE.json](/Users/lexi/.codex/worktrees/v4-stage-sync-20261028/v4_app/docs/handoffs/v4_a_chain_completion_20261028/online_completion_20261029/natural_repair_20261029/CONTINUATION_STATE.json)

## 版本与同步锚点

这些只代表各自快照，未来操作重新读当前身份。

| 对象 | SHA / commit |
| --- | --- |
| 当前Main | 528a7413168931473a2f418f394efaa0ad640356a3c9d6f68ef455b238e71176 |
| native源码 | 1e8166771b2194629574d0073f058d4a138909f9553519e7843a536b0f82289c |
| 原错误Stage清单 | fe7250448b863ecb421e0055a997eeef635506d1f0823b80db7827c413e2d863 |
| 修正后Stage清单 | be16a5a75f7bcaf578af4e0e3506d7be2f628eeae1508470ab1ae05ff9e1d902 |
| 保留的其它任务API | 1d8028771bbab4e92dafe2917a6fc936df705c2259485fe478f2d34689466240 |
| 保留graph | 478c0b1ee55ffc8610af54d1ff3e867578582412205464cf69e6b2d633f902a5 |
| Main源远端 | 5734815af922a590a4e95f61e1f9920f0d1a05c4 |
| native源远端 | 3f0f3963588832fe0ac58332b11d67e2d9383c8c |
| 激活记录远端 | e36c35e2d97cd073952ef3a8d2e7fbf13cef28ad |
| metadata/SOP/新降级 | 正在处理；未核远端前不称SYNCED |

不上传原行情、完整响应、安装树、计划/认证/nonce、备份或依赖。固定金融边界：RESEARCH_ONLY=true，production_allowed=false，buy_gate_updated=false，orders_sent=false。
