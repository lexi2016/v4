# 经理每日研究 R3 修复候选与 Mac 接续交付

**本包已经包含修复代码、按实际源码角色拆分的补丁、定向合成测试和原共享 owner 的接续步骤。现役尚未集成或部署，真实 20261008 / 20261009 计划、API/UI 与连续自然运行仍待 Mac 验收。**

输入为 [固定 R3 问题包](https://github.com/lexi2016/v4/tree/b98d85c95d19780e2900dce7de9372328e67acf6/handoff/manager-daily-failure-20261009-r3)，共享父基线为 `66bb05a2e12976775ccb997191ce943bae8cc9a5`。49 件输入文件全部按远端 Git blob 身份核验，32 件可用源码快照逐项核对 SHA/大小；一件原 namespace 缺失按缺失记录处理。R1/R2 复用的是固定候选源码，未将其解释为已部署状态。

## 本轮修复了什么

1. **在一份绑定中区分 worker 和 API owner。** 顶层 `app_root/files` 仍标识 worker，新增严格的 `plan_owner` 标识实际 API 根和源码清单。两端仍核同一原始 JSON 的完整 SHA，并分别检查 root、enabled、闭合的来源清单和真实 canary。现存嵌套 API HK consumer 也进入来源身份检查；worker 没有该目录时不伪造目录。
2. **把不同失败阶段交还给现有调用链。** 本地未触发、disabled、API 只读 admission 拒绝、输入未就绪、owner 失败以及传输结果未知有独立结果。API 409 的原因必须来自限定集合并绑定 schema、owner、日期、binding SHA 与研究 flags；伪造或损坏的响应不能声称 owner 未调用。超时保持 `CANNOT_CONFIRM`。
3. **将候选 R1/R2 的必要增量一起交付。** API、当前 20261006 worker、web 与 HK child 分开成包；worker 包包含现役缺少的累计 `workspace_plan_autorun.py` 方法。HK child 重放原 R1 三件增量并保留当前 namespace。没有新增采集器、调度器、页面或平行数据层。
4. **补齐逐股证据的轻量来源指针。** 日计划投影保留 payload / manifest / pointer 等原生路径和 SHA，并保留证据卡锚点。不递归复制正文，不改变原筛选状态或名单规则。
5. **补齐原发布 owner 的审查材料。** 原 Issue30 政策尚未允许五条必要共享路径；`release_policy_review/` 只提出这五条 exact path 对 manager 的授权，不授予目录前缀权限，也不自动采用或绕过原 release lock / active-base / delta receipt。

## 补丁选择

完整前后字节、SHA-256、大小和来源在 [source_manifest.json](source_manifest.json)，人读映射见 [SOURCE_MAP.md](SOURCE_MAP.md)。同一角色只选择适合其精确前像的一个 profile。

| Profile | 文件数 | 用途 |
| --- | ---: | --- |
| `api_current` | 13 | R3 所附现役 Issue32 API 的经理累计修复；含一件父提交源码前像，必须单独核本机实际字节 |
| `api_r2_increment` | 7 | 已完成 R1/R2 候选的 R3 增量；不能叠加到已应用 `api_current` 的同一个根 |
| `worker_current` | 5 | 当前 20261006 manager worker 的累计兼容修复 |
| `hk_child` | 3 | 三件原 R1 精确重放；现存 namespace 不进入替换补丁 |
| `web_cumulative` | 4 | 复用 R1/R2 web 增量；本轮未新增 UI 代码，实际 before 必须匹配 |

原共享 scheduler daemon / launcher 没有源码变更。Issue32 的 `app.py`、`preselection_router.py`、`preselection_service.py` 三件保持问题包 SHA。测试源码装配不是可部署的完整 app。

## 阅读和验包顺序

1. [HOST_HANDOFF.md](HOST_HANDOFF.md)：原 Mac Luna Max / shared owner 的集成、绑定、实际两日验收与回滚步骤。
2. [HK_INPUT_CONTINUATION.md](HK_INPUT_CONTINUATION.md)：公告、US、HK 的原 owner 接续、当前缺口和限定的执行命令。
3. [TESTING.md](TESTING.md)：本轮实际环境、命令、成功结果、保留的既有失败和可移植离线复验方法。
4. [ACCEPTANCE_STATUS.json](ACCEPTANCE_STATUS.json)：机器可读阶段状态。
5. [independent_review/FINAL_REVIEW.md](independent_review/FINAL_REVIEW.md)：独立审查发现、修复闭环与最终候选边界。

先核完整包，再核明确选定的源码根。以下仅做只读核验，不应用补丁：

```bash
cd /absolute/path/to/manager-daily-r3-repair-20261009
shasum -a 256 -c PACKAGE_SHA256SUMS.txt
python3 tools/verify_delivery.py --package "$PWD"
python3 tools/verify_delivery.py --package "$PWD" \
  --profile api_current --source-root /absolute/path/to/isolated/api/app --against before
```

`verify_delivery.py` 校验 profile 闭集、逻辑文件与载荷路径一一对应、精确 before / after、补丁身份及保护文件。包已进行各 profile 在临时目录中的正向和反向补丁回放。这个工具不替代原发布 owner 的集成协议。

## 验收边界

本轮实现与定向合成合同测试已完成，三份 R3 新测最终合并为 **66 passed**（binding 44 / product 9 / HK 13）。测试覆盖不同根绑定、SHA / root / enabled / inventory 拒绝与失败传播，10/8 事后 `dynamic` 读回和原 `auto` 历史资格，10/9 已保存计划的普通 `auto` 同 run / product SHA / 输入身份读回，缺失输入、合法空结果、逐股理由及实际 API 嵌套 HK consumer 行为。

原测试中的一项公告状态断言、四项旧 plan-only fixture 锁合同断言、两项既有 HK screen 断言仍失败，分别保留日志及来源归因，未删除、跳过或改写断言。独立复核发现的验包工具闭集、真实 PREOPEN 超时分类和异常原文问题均已修复并回归；详情见 TESTING 和独立报告。

真实输入尚未因此恢复。R3 现场两份 GET 的 plan `date` 都是 **20261009**，不能写成已实际读取 10/8 计划；未获得实际 dispatch receipt，10/9 是否自然触发仍 `CANNOT_CONFIRM`。10/8 事后产物只有合法输入可用且原 owner 实际保存后才验显式 `view=dynamic`；10/9 当日产物保存后才验默认 `view=auto` 的同一产品。缺输入继续保留通道原因和未知计数，完整合法筛选为空时才接受可追溯空结果。

`INTEGRATED / DEPLOYED / LIVE_API / LIVE_UI / NATURAL = NOT_RUN`。至少两个连续适用交易日的自然链另由原 owner 验收，不能用候选 PASS、采集成功或 HTTP 200 替代。

全程保持 `RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false`。
