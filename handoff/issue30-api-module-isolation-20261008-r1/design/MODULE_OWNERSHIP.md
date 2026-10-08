# 模块、运行 owner 与发布边界

## 一个入口与模块所有权

V4/8873 继续提供统一 FastAPI 入口。模块分开 router/service，`app.py` 负责组装；API 发布仍是整包原子切换，但候选必须含当前 active 的非 delta 内容。

静态允许策略在已固定 core 的 `POLICY` 内；其 canonical JSON SHA 随 module_scope 写入 receipt。策略不能由 plan、环境变量或未 pin helper 任意替换。以下是第一版明确开放的范围，不宣称已穷尽整个项目的模块。

| module | 专属文件/前缀 | 可显式声明的共享文件 |
| --- | --- | --- |
| `preselection` | 新 preselection router/service，`domains/preselection.py`、`domains/preselection_pools.py` | `apps/api/v35_api/{app,config,run}.py` |
| `manager` | `domains/manager_research/`、实际 R2 的 `v4/manager_research/`、`apps/api/v35_api/manager_` 前缀 | 同上 |
| `research_review` | `review_router.py`、`domains/daily_research_review.py`、`domains/research_review_generation/` | 同上 |
| `api_platform` | 本批共享工具四文件按共享策略声明 | app/config/run及四个发布工具 |

真正的路径拼写与归属以代码中的完整字符串为准。未知目录、A auction、HK producer、web或scheduler，不因名字相似自动获得权限；将来修改这些文件需先扩充并独立审查 ownership policy。这个初始保守范围不会阻止保留 active 中的既有非 delta 文件。`v4/manager_research/` 来自精确 R2 app 和固定 manager router 的实际加载路径，只有 manager owner 可声明。

共享文件要求前像、后像、mode 和 diff，`shared_paths` 必须与这次实际使用的共享路径恰好相等。reviewer仍要检查共享 app 的语义范围；文件级所有权不能代替同文件内部的业务审查。

## 运行及发布 owner

| owner | 已知入口/根 | 本轮证据边界 |
| --- | --- | --- |
| canonical源码 | `/Users/lexi/Desktop/学习/v4_app` | 交接的四工具前像/必要支持可核；当前工作树与全部并行改动未在Linux读取 |
| API运行app | V4 releases 下晚间 `manager-workbench-r1-mac-20261008-api-r2/app` | 完整manifest/inventory摘要来自原交接；app单文件匹配；其余1016项正文未取得 |
| 当前提供的实际publisher | 经理任务 `completion_20261008/workspace_failure/staged/api_only_cutover_r2_ready.py` | 原脚本精确前像补丁；执行、回滚与恢复有合成验证；实际安装未执行 |
| 共享integration guard | canonical `ops/api_release_integration.py` | stdlib-only；实际publisher固定路径+固定SHA加载同一份bytes |
| active API pointer | `/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist` | 共享persistent flock位于同目录，由 core 函数导出；不再用任务evidence作为API指针锁 |
| Stage | 原 `com.lexi.stage-center.scheduler` 及其自身app/config | 没有随本包部署或改写；独立库存和来源合同仍需本机核 |
| scheduler | 原 `com.lexi.v35.scheduler` 及其launcher/app | API builder只生成未激活审查副本；不重绑此服务 |
| Vibe | 8910原入口 | 本批不修改，替代验收前保持 |

## 本机入口接管的判定

同机不同任务必须争用同一个 API plist 锁文件，并把 lease 传到最终 active 写点和恢复写点。锁为持久文件，不能解锁后 unlink；lease需核PID/fd/inode/path，跨进程fork或路径替换不可继续使用。新事务重新pin guard，当前事务的恢复继续使用已验证的 bytes。

本包没有修改操作系统写权限，也没有禁止不遵守协议的旧脚本直接写 plist 的能力。实际发布闭环必须盘点 launcher、任务脚本、历史安装/恢复入口及所有可写同一pointer的路径，确认接入或退役。缺任一实际入口证据时，这一项保持 `CANNOT_CONFIRM`。旧 #28 install/recovery 的外部guard未pin和双link失败问题是另一套工具的合成观察，不能混称晚间 R2 已发生同样事故。

当前 R2 publisher 的47原任务pins被保留，以免改装过程中静默换业务批准边界。新的恢复release不能重用旧批准对象；本机取得完整候选、业务证据后，应把新plan及pins冻结在一个明确受保护入口，并由独立reviewer验其加载与所有写点。不能继续把任意旧整包放进另一个临时任务发布器中执行。

## 保留证明的实际范围

core绑定文件字节、普通文件mode、symlink文本和目标是否存在；目录集合/mode另绑定。它不证明外部venv依赖版本、symlink目标文件内容、Mac ACL/flags/xattrs或所有业务效果。复核这些外部身份与Mac服务用户权限后，才可能给运行闭包验收结论。

预选池单文件app补丁保留其余54个`create_app` statement和经理装配后缀；本批新service是读取consumer，不授予producer或Stage的数据写权限。合成API通过与真实Stage/自然时段通过分开记录。
