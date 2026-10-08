# Issue #30：API 模块发布隔离设计

## 目标与依据

执行用户要求的源码修复：阻止旧整包覆盖其他模块修改，并在精确晚间 R2 前像上恢复预选池读取。输入为 `a0a0b88dc133d14ee5763569272c174bcd7cc445` 的 Issue #30 九文件交接包；九个 Git blob/大小及七项源码 SHA 已核对。当前执行环境为 Linux 隔离文件目录，不是 Mac canonical 或实际 API 目录。

保留 V4/8873 唯一入口；不引入第二面板、平行 producer 或多个公开端口。RESEARCH_ONLY=true、production_allowed=false、buy_gate_updated=false、orders_sent=false。部署、merge、服务与业务数据改写不在本次授权内。

## 选择与取舍

采用“单 API 装配 + 按模块差异交付 + 当前 active 基线整包原子切换”。独立后端进程会增加运行身份、路由和状态管理，本事故无需靠它解决。只做 router 拆分而继续接受任意旧整包，无法阻止事故复发。

保留已有 draft 的 active-base/delta 思路，纠正完整性和接线缺口。草稿不是已审实现；原 18 个测试单独保留并记录基线，新增测试需先复现失败。

## 模块边界

- 预选池：独立 `preselection_router.py` 提供既有 GET 合同，`preselection_service.py` 管理读取、聚合与来源选择；不造数据。
- 经理：保留已存在的 manager research/workbench routers 和 services，不移动其字节。
- `apps/api/v35_api/app.py` 是共享装配文件，只替换预选池注册/专用辅助逻辑；对晚间 SHA `90a2bf6390c6c0e219aa3d9bb22bc3b3630ecb2d447df494ae69425933424ed7` 生成精确补丁，不用旧 canonical 整文件替代。
- `ops/api_release_integration.py` 是共享发布合同、库存验证与 API 指针锁边界。第一版 ownership 只开放明确模块路径；未知路径拒绝，共享路径必须逐项声明。
- API、Stage、scheduler 是不同 owner；API 模块交付不使其他 owner 自动获得相同版本身份。

## 差异合同

v2 receipt 绑定 active release id/root、manifest SHA、完整 app inventory 和逐文件 before/after SHA、mode、文本 diff 证明。module_scope 绑定静态 ownership policy 摘要、模块名及恰好使用的共享路径。旧缺 base/delta、v1 草稿、错误前像、未声明新增/修改/删除、越权模块路径和多余共享路径一律拒绝。

从核验的 active app 复制非 delta 字节，只从 source_root 读取声明过的 after 文件；不把工作区全部内容复制进候选。文件/目录路径需拒绝 symlink 或别名逃逸。验证后复核 active plist、manifest、inventory，避免一次检查之后读到混合版本。

## 真实切换边界

实际 `api_only_cutover_r2_ready.py` 有任务路径推导和大量 R2 固定 pins，不可直接搬到中央 ops 目录。交付对其精确实际前像的补丁：execute/rollback 函数内部持有同一个 API plist 旁的共享锁；内部变更函数和失败恢复函数要求有效 lease；bootout 前和 active plist 写入前重新检查 base/delta。普通回滚仅从本次 candidate 回到操作 receipt 记录的 base。

shared lock 使用 persistent lock 文件、fcntl、NOFOLLOW、fd/inode/path/PID 校验；不删除锁文件、不使用 evidence 目录作正式 API 指针锁。实际脚本只从固定 canonical 路径读共享 guard，先核固定 SHA，再 compile/exec 同一份 bytes；不让 plan/environment 改 guard。

原 R2 旧候选没有 v2 集成合同，升级脚本应拒绝继续发布它。新 R3 恢复候选及其运行 pins 必须由本机从届时 active 构建并独立审查。此源码补丁不等于脚本已安装；其他未提供的 publisher 也不能据此宣称已停用或受保护。

## 验证与实际限度

覆盖 stale self-consistent package、wrong before SHA、undeclared byte/mode changes、strict schema/module ownership、late baseline drift、cross-process shared lock、execute/rollback guard、same-bytes guard loading、candidate path escape。预选池独立 API 测试同时覆盖空本地池、非空 A 加 HK、来源/date隔离、缺子池不阻断；经理字节保留另作精确证明。

完整 1016 项 R2 runtime 闭包、真实源 A=178/HK=100 read-only canary、Mac integration、deployment、API/UI reload 和自然时段均单列，未实际执行时保持 NOT_RUN/CANNOT_CONFIRM。HK 日期来源及其他 #28 问题不借发布改造改业务语义。
