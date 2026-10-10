# A股预选：原函数只读迁移候选

用户已要求并行补齐模块。本批复用原A预选build函数，不新造评分、排名或跨池去重；不发布正式PreselectionPoolStore，不接管V4。

## 输入与输出

请求固定target_date、signal_date、data_kind与最多6条lane。lane仅允许v192、fupan、stage7、wechat、baimao、research，给定明确input_root、角色路径及完整候选文件SHA清单；不存在输入用清单中null明确声明。路径拒绝symlink和越界。实际读取的文件在读前/读后核字节，读期间变化不交付有效结果。

固定日历使用已冻结原trading_calendar。A目标日必须开市，signal_date必须是前一A股会话，例如20261008对应20260930；不能用港股20261007替代。年份外未知不按开市处理。

每条lane调用原build，返回原artifact全文和独立的accepted/缺口。完整rows不按UI页长裁切，不改原pool_score/排名。源错只隔离对应lane；未知程序错误整体返回FAILED而不伪装缺数据。全部lane无可用产物时row_count=null，不把缺失算成有效零。

本批五条健康lane组合运行已覆盖冻结V192 reader的有效非空artifact。原V192 verified空集产生V192_CANDIDATE_READY_EMPTY，但同版通用validator不接纳此空状态；候选会明确保留原artifact并报告LEGACY_EMPTY_STATUS_CONTRACT_MISMATCH。verified-empty合同仍未通过，本批不擅改其来源或状态。

输出是V5只读组装回放，formal_eligibility_verified=false、natural_verified=false、安全交易标记false。原artifact中既有VERIFIED标签保留作为原合同内容，不因此宣称V5真实源与自然运行已验。并集/阶段实际消费另按原consumer合同接续，不在此处另造算法。

## 独立执行

40个固定来源entry覆盖原preselection、hourly research/store闭包及冻结日历，逐字节固定。只在新Python子进程加载，固定source loader直接compile核定bytes，不占主进程domains/infrastructure命名空间。使用原只读V192 reader，避免原动态loader去找活动源码。

worker禁止网络、子进程和写入；原build仅返回结果，父进程读取JSON。SafeRoot为初始化只读目录FD以及在已声明输入根下检查文件所需的目录FD链保留最小只读访问；目录枚举限定在声明文件所在目录，O_DIRECTORY不能伪装成数据文件读取。文件内容仍须在声明清单中绑定SHA，未声明的数据路径会明确失败。Mac时区兼容仅接受系统UTC别名解析到平台时区数据库 `.../tz/<version>/zoneinfo/UTC` 的物理文件，并按物理目标打开；不信任 `PYTHONTZPATH`。固定代码、解释器库和这一精确系统资源之外的来源不开放。这是Python防护，不宣称已建立OS沙箱或owner读锁。

本批没有采集、模型训练/重算、服务启停或部署。验证结果只记录实际命令与回执。


静态审查补充：guard违规独立抛错，逐lane只允许自身清单；拒绝lane非有限值以tagged诊断记录，合计预算超限只省略拒绝诊断，不截健康rows。父端核schema、日期、数据种类、源码身份与安全旗。worker以固定且有限的owner拒绝消息隔离hourly research输入校验失败；未知错误仍整体失败，SHA一致但schema错误也不触发preview回退。V192有效非空路径已有运行覆盖，verified-empty路径仍是独立合同缺口；不以静态检查替代运行证据。


## M05 单一研报组合lane

`research` 是单一组合lane，仍只产出 `a_share_research_recommendation_pool`。先调用冻结的 `build_hourly_research_pool` owner；仅当它抛出 `FileNotFoundError` 且 `research_preview.json` 与 `selector.json` 都是已声明的普通文件时，才核验两份文件的SHA并调用冻结的 `build_research_preview_pool`。缺少任一文件时产出原 owner 的 `CANNOT_CONFIRM` 缺失artifact。错日、manifest/receipt或身份不一致等校验错误不会进入preview回退。

健康hourly路径不打开preview/selector内容；它们的路径与声明SHA仍完整纳入请求身份散列，只有实际使用preview时才核对字节。hourly/preview均由冻结owner构建，不另加分、不新建并列池。新增的hourly/store来源闭包逐文件固定并在装载前验SHA；原 `hourly_pool.py` 与 `HourlyResearchStore` 来源字节不改。

