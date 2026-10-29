# 2026-10-28—29 V4 阶段选股修复记录

记录截止：2026-10-29 17:58，上海时间；后续追加实际结果。此处是事实账本，不能作为未来动作的现役 CAS/PID/期限。

## 用户目标与后来明确的处理规则

- 修复 A/HK 完整阶段链路，安全上线，按各阶段实际结果验收，保护其他任务和原 5073 只股票数据。
- 用户多次要求继续直接修复，不只给排查报告，不反复向其他用户会话发送材料。
- 2026-10-29 新明确决定：缺回执时重新抓当前快照，以后默认如此；原阶段、实际采集时刻、晚到标记和降级原因必须清楚，原失败不覆写。
- 用户再次明确“补采集以后要选股”：必须在快照后调用原引擎评分、排序并交付补选结果。上一版只给观察名单不算完成；原阶段自然/PIT/正式 selected 结论保持独立。
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
- 快照补采观察及SOP导航已部署，但补采后的真实选股仍未上线；当前唯一Writer沿原引擎补齐。56观察不能作为完成选股的验收。
- 下一自然窗口七阶段及约定收盘链仍需按原结果或明确降级结果验收。
- 最新一次浏览器控制报browser.user unavailable，不能用API成功代称新UI已验证。
- 本文件和SOP的存在不等于自动降级代码已生效。

## 本轮必须避免重犯的具体错误

1. 先调用真实消费者验证manifest契约，再把服务启动称为功能恢复；kind、size、SHA、身份和源绑定都要完整。
2. 优先组合必要变更，不把一次修复拆成多次认证；已空闲的日历任务能用原审核的同UID路径时，不重启无关常驻服务。
3. 预检失效/窗口关闭就保留证据，下一窗口只更新必要参数；不重复全套测试或旧认证。
4. 源码PASS、包PASS、DEPLOYED、API、UI、原自然运行及补采观察分别写，不能用阶段总卡片/HK行掩盖A0。
5. 遵循用户新增快照降级规则；缺回执时抓取真实快照后必须继续原引擎选股并交付补选结果，不能一再止步于缺回执报告，也不能造历史成功。
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

## 16:23—16:53：快照降级与 SOP 导航真正上线

- 用户明确要求将 SOP 放入现有“功能入口”；同一候选加入 view=sop、固定3文档GET和同阶段补采卡片/表，不新建页面服务。
- 候选15个直接场景及Vite构建通过；现役/候选TypeScript既有收盘诊断完全相同，无新增，不声称整个项目typecheck全绿。
- 组合独审独立复现P2：1行quantity.volume=NaN会导致整批artifact编码失败。仅对4个provided数量字段做finite/nonnegative检查、坏行隔离，不填零；新增1个encode/store/read回归通过。原FAIL和原freeze保留，同Reviewer只增量核该返修与pin传播后PASS。
- 新Stage清单8b9e9c22f4641c395e853dcfd2b0c7054f9fdcd416d9ed0bc86412da617a5694、新API清单acccc7915d9435333c0490f51cd4bf75f8c8931d6792fc17b880498f29134a9f的不可变候选安装后，原trusted reader在无overlay环境13/14通过、旧09拒绝，再进入实际切换。
- 16:35—16:36完成同一批API/collector/Stage/precapture切换，Main73799保持运行；四角色DONE、guardian NORMAL_DONE_ALL_GUARDS_DISCHARGED。当时本批发布窗口已释放，没有持锁；用户后续指出缺少实际选股，现恢复有界源码修复。后续确需发布时重新核当前owner/原锁，不沿用已完成控制。
- 用户再次要求以后不要反复认证。此次把快照与SOP合并一次切换；日常自动补采只调用原行情接口，不调用系统换版认证。
- 16:38由实际现役Stage入口一次manual import已封存15:19 capture；未再请求SDK。派生5目标receipt保留原4目标receipt及SHA，追加实际15:00失败上下文；两段原候选集合均58且相同，未改时钟、原raw或失败。
- 实际GET七A阶段：09:25/09:35/09:40/09:45/15:00各56条补采观察，formal A仍0、NATURAL/PIT不升格；10:30与13:15原A10保留。HK各原10保留。五个上下文使用同批56股票，不是280只不同股票。
- 16:52核对五个观察trio和capture共20文件SHA及原61保护项通过；派生观察写入独立索引，不写原selection_latest/raw/panel/pointer。原15:00失败和五个原失败SHA均保留。
- 后置读回时另一个已授权API任务已从本版本继续发布至88904c6d7ffbdc096933f6a71864c8b0cbdcd14ce1a956baa04601fe878bf1b4；本任务保留其成果，按实际版本读回，不强退回自己的PID/旧manifest。
- 页面工具高层及同origin CDP报browser.user unavailable，原生Codex访问被工具安全策略拒绝。实际UI状态保持CANNOT_CONFIRM，需实际可见反馈；没有绕过权限或把API当UI证据。
- 原自然tick自动触发仍待下一原时段，既有同一条跟进继续验证，不新增producer/定时器。

最新机器记录：snapshot_recovery_r1/COMBINED_REVIEW_PASS.json、INSTALLED_CANDIDATE_READER_RESULT.json、POST_DEPLOYMENT_READBACK.json、post_deploy/SEVEN_STAGE_GET_VERIFIED.json、LIFECYCLE_WINDOW_RELEASED.json。源代码与必要精简结果在本次收尾同步并记录远端SHA；行情、完整响应、计划和认证材料不上传。


## 17:15：用户指出补采后没有选股，继续修复

- 用户明确纠正“补采集以后要选股”。主控承认上一版只交56条观察名单少做了选股，不再把观察上线当作本目标完成。
- 已定位现役原入口 production_selection_builders → select_a_live_stage → live_stage_quality_score / stage_row_sort_key → 原Top10上限；不改算法、权重、配额或BUY。
- 封存15:19快照的56有效行具备原引擎必要行情字段；17:12隔离运行已按原引擎真正选出10行。研究源分值仍null、原引擎中性默认行为如实记录；1400有效见证与1500失败分别保留。隔离结果不是已上线补选。
- 当前继续补齐补选产物、原Stage/API/UI接入和实际验收；原5阶段失败、10:30/13:15已有A10、HK、他任务图表和5073底板保持。


## 17:58：真正补选整包已独审、安装，等待原日更结束后切换

- 7个业务源接入快照→原select_a_live_stage→原评分/排序/Top10→独立snapshot_reselection产物→原Stage/API/App；没有另造引擎、producer或面板。
- 五个空缺阶段的真实封存56输入各选10；原SDK补抓0次。研究缺失字段null、原neutral内部默认明示；1400合法last-known-good与1500拒绝并列，确无合法上下文则明确NO_VERIFIED_RESEARCH_CONTEXT继续原行情补选。原正式A10/READY_EMPTY/HK/FAIL不替换。
- 同一独立Reviewer PASS，零P0/P1/P2；只读复算09:25/09:35/15:00与封存排名/分数完全一致。9个针对性场景及Vite构建通过；旧PASS复用。新Stage986/API1295保留完整kind和Chart455资源。
- 不可变安装成功，实际原trusted reader无overlay验证13/14通过、旧09拒绝。新Stage清单cb390fa6aa0d5d2863fb2809835134d0269197e6698f120c0766205d0688b46c；新API清单049603267a7f34a04f16d48c629f0425f2d832ce563331d601f7f15a9b384fb9。尚未激活，不声称线上补选完成。
- 尝试减少认证的直接证据：现役API原lifespan会等待已接任务，但普通bootout有launchd超时KILL风险；submission scope含任意合法日期等，无法枚举封闭。自有纯sleep canary证实disable仍会自动拉起loaded KeepAlive，测试失败已保留且自有标签/plist完全清理。没有把此方案用于真实服务，没有新权限/信号技巧。
- 原17:00股票日更在Main73799→96690→96767健康执行。原guard要求它自然结束；Main、5073底板和旧component/app/argv/checkpoint均保留。只有真实安全窗口、freshowner/原guard和全部前置完成后才发最终系统认证；不假填idle，不复用过期nonce，不因合法日更推进而回旧指针。
- 16:36只交观察名单是本次实现遗漏；这正是现在仍需完整补选发布的原因，不是每天自动快照选股都需要认证。SOP以真正selected补选验收，不能再以56观察完成收尾。

机器证据：snapshot_selection_r1/COMBINED_REVIEW_PASS.json、IMMUTABLE_INSTALL_RESULT.json、INSTALLED_CANDIDATE_READER_RESULT.json；下一动作以CONTINUATION_STATE.json为准。


## 2026-10-30：补选快捷路径纳入SOP

- 用户要求以后不要再把补选拖成漫长发布。已明确既有快照优先直接补选、已有匹配补选直接复用，观察名单不能收尾；API显示版本更新与默认Stage升级分开。
- 本批实际禁网运行原CLI：5×56输入到各10条，耗时1.6036285秒、峰值RSS330170368bytes。126项原formal/FAIL/HK/来源保护SHA在执行前后不变。
- 原reader逐项通过算法/观察/上下文/真实时钟绑定，源缺失分值保持null；CLI摘要截断不提供provider计数，零新SDK查询以进程禁网和原观察身份保持为证。
- 新API候选及原引擎补选已独审通过。01:38单API人工认证等待到期，caller已退出、socket和release lease均已清理；actions为空，原API PID38816及plist SHA保持。没有重启或切换正式服务，旧固定命令不得再执行。
- 正式8873的“SOP → 阶段运行规程”已实际点击，快捷补选条款可见；这只验收SOP页面，不代表五段新补选已在旧API显示。候选、实际补选、独审及切换边界已写CC_TAKEOVER_ACK，避免同范围另起发布。
- 默认Stage自动补选尚待激活/自然验收；原09:25失败及非原时点边界保留。
