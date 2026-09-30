# Issue #8 最终业务修复候选

唯一入口：**FINAL_REPAIR_PLAN_ZH.md → WORK_ONCE.md → tools/work_once.py**。

本包已合并原B1/US代码，不再叠旧包；新RPC cycle/router/owner同tick修复和原US字段链适配已给完整after。7个本批既有文件修改；累计9改1增。新27项定向通过，未重跑未变旧套件。

`runtime.patch` 基于 SOURCE_PINS 所列 API6726＋上传冻结入口前像；`after/app/`包含全部累计改后文件；`before/app/`是精确前像。已有源码不同即集中报告，不盲覆盖。提供的冻结入口只进入inactive副本，不宣称安装绑定。

F0–F2独立23350050已PASS。R3A由Work原单写者接续，本目录不修改其5文件。当前真实资格、时钟/关系来源、API/UI与部署仍须按最终方案验收。PR9 Draft、Issue8 Open。不启调度、不改BUY。
