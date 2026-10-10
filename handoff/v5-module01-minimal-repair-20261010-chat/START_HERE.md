# V5 第一模块最小修复代码交付

**唯一代码候选 commit：[`6daed6271313b5ae5324c8948f163258ab8d1fa3`](https://github.com/lexi2016/v4/commit/6daed6271313b5ae5324c8948f163258ab8d1fa3)。** 仓库 `lexi2016/v4`；分发分支 `v5/module01-announcement-readback-20261010-chat`。该 commit 的唯一父提交是固定 V5 前像 `f7cb731c384ee6890a87d16c19a5b5a621779477`。分支后续的交付材料提交仅补充本包与实施记录，不改变这 20 个代码/测试文件；运行代码身份以此固定 commit 和逐文件 SHA 为准，不用浮动分支代替。

任务来源为 [`9cac0ff.../PROMPT_FOR_CHAT.md`](https://github.com/lexi2016/v4/blob/9cac0fffe12fda6ec06e106206e0c647b427913f/handoff/v5-chat-module01-20261010/PROMPT_FOR_CHAT.md)。这是按该提示完成的代码候选、测试与落地材料。状态：**代码候选已实现、独立终审通过；真实 Mac 原件/部署/API/静态资源/内置浏览器及自然时段验收均 NOT_RUN。** 不升级为完整三策略或 18 模块完成。

## 先看什么

1. [SOURCE_TARGET_MAP.csv](SOURCE_TARGET_MAP.csv)：41 条函数/来源映射，覆盖原 V4 的 11 条逻辑路径及 28 个候选变体、公告现有适配和 d659ff0 三项局部修复判断。V4 donor 不是 V5 目标路径。
2. [runtime.patch](runtime.patch)、[reverse.patch](reverse.patch)、[after/](after/) 与 [before/](before/)：完整可应用代码，20 条明确路径；10 个修改文件有完整前像，10 个新增测试/支持文件的前像为不存在。
3. [SOURCE_MANIFEST.json](SOURCE_MANIFEST.json) 和 [RUNTIME_FILE_HASHES.csv](RUNTIME_FILE_HASHES.csv)：逐文件 before/after SHA256、Git blob、字节数、新增路径及 patch 摘要。
4. [validation/VALIDATION.md](validation/VALIDATION.md)：实际命令、通过、失败和未执行边界；[原始日志](validation/raw/) 保留初次失败与后续修正证据。
5. [MAC_APPLY_AND_ACCEPTANCE.md](MAC_APPLY_AND_ACCEPTANCE.md)：现场前像、隔离应用、原件同 run/API/静态资源/浏览器、单窗口切换及回退。所有现场路径由操作人据实填写，没有猜测现役覆盖命令。
6. [review/FINAL_CODE_REVIEW.md](review/FINAL_CODE_REVIEW.md)：新鲜独立终审；两项 Important 均已修正并复核，无未关闭的 Critical/Important。审查结论不批准部署。

[DEPENDENCIES_AND_SCOPE.md](DEPENDENCIES_AND_SCOPE.md) 说明原依赖、manifest 唯一变化及后续事项；[validation/NOT_RUN.md](validation/NOT_RUN.md) 明确尚未拿到的原件、接口和运行证据。[provenance/CODE_REMOTE_READBACK.json](provenance/CODE_REMOTE_READBACK.json) 记录固定代码 commit、父提交、tree 和全部 20 个文件远端读回。

## 7 个运行代码/配置文件改了什么

| 真正 V5 目标 | 最小修改及结果 |
| --- | --- |
| `V5/src/v5_shadow/manager_plan.py` | 用既有不可变 run 文件及原 owner validator 精确核验本次 product + 同 run terminal；单列 latest 观察。普通页不借另一 run 的 journal；同日缺终态仅保留未确认预览。发布 helper 可在发布前检查 expected run。 |
| `V5/tools/cloud_preview/publish_read.py` | 消除两次普通读之间的竞争窗口；一次已验证读的结果直接发布，expected run 不符时不建立 active generation。 |
| `V5/src/v5_shadow/module_api.py` | 真实只读 manager module 用响应头声明只读能力，不修改保存 DTO。 |
| `V5/src/v5_shadow/api_gateway.py` | 仅在 manager 全部路由都没有 POST 时给工作区标只读；保留既有 generic 分离 refresh 路由行为。 |
| `V5/ui/manager-workbench/source/apps/web/src/api/managerWorkspace.ts` | POST 日期 bindings 进入完整 validator；保存产品与原同 run 终态准入补齐；只读能力仅来自经校验响应的传输元数据。前端校验 SHA 标识格式与时序，原后端仍负责封印重算。 |
| `V5/ui/manager-workbench/source/apps/web/src/manager-selection/catalystObservationPanel.ts` | 成功 POST 消费一次；取消/切日/切 view 后迟到回包失效；历史默认、失败/不完整初读和 V5 只读入口关闭计划生成；未知副作用不冒称失败或自动重试。 |
| `V5/ui/manager-workbench/overlay-manifest.json` | 修复 `dailyChannels.ts` 同时列为“变更”和“必须保持更旧 SHA”的矛盾；更新真实改动源 SHA，登记必要新测试，保留其他依赖严格前像。 |

其余 13 个文件是测试：3 个旧合成测试文件中各一项合同适配，10 个新增测试/支持文件。没有更改 `V5/vendor/`、业务 source contracts、`dailyChannels.ts`、依赖锁、现役 V4、BUY、8910 或任何 Mac 数据。实现计划与审查决定另存为材料。

## 实际验收结论

- 精确 run / terminal 新测试 **14 通过**；原 owner 公告合同 **9 通过**；单读发布竞争 **2 通过**；最终安装器 **4 通过**。最终只读 HTTP 新 **6 项**连同原 gateway/module/artifact 回归合计 **54/54 通过**。这些不同组的次数有重叠，不相加冒充全工程总数。
- 最终 3 份 module01 前端测试 **44/44 通过**，包括最终字节的真实合成 owner → module/gateway HTTP → 完整前端 validator。两面 HTTP 为 200、run/SHA 一致，GET 前后输入/存储字节不变，临时服务器已关闭。
- 最终受影响 5 份前端 spec **85 通过、2 个原件缺失失败**；全量类型检查 **exit 0**，最终正式 build **exit 0**。原完整入口 **442 通过、23 失败**：17 项缺原 owner/Mac 证据、4 项缺指定 cloud artifact、2 项旧合成合同（后两项随后修正并在受影响组通过）。未重跑整套并宣称全绿。
- 原 Python 受影响入口记录 **222 tests，6 errors、6 skipped**。一个 setup 需要 Mac 原请求；六项原 skip 缺指定原 fixture；五项 error 是本地缺原 archive manifest。已按固定 F 补齐该原依赖、保持源码不变，对应 archive **8/8 通过**。原失败原样保留，不把完整入口改称通过。
- 前端 **125 个原来源、134 个有效组装文件**逐字节核验。正向/反向补丁全部 20 路径验证成功；前像检查器在正确 before/after 成功、篡改前像时拒绝且不写文件。

具体原始日志及未执行项见验收文档。四条合成决定只用来证明原链及边界，没有替代 Mac 的 392 条决定。

## 必须由 Mac 完成的真实验收

沿用原回执的 run `5b4feaf7ef7d4d13bec639e90b6d3db0`、计划 SHA `56556a67ddc1a562e82b38e750be92fcfda070945397cc4eacffd1c79f42bcf0`，原生成时间 `2026-10-10T02:23:24.502381+00:00`。392 是决定数：2 event / 0 earnings / 26 observe / 270 not selected / 94 unknown，不能当作 392 只入选股票。这些是输入交接记录，本轮未重新验证。

`--expected-run` 是发布前拒错 guard，不是任意历史 run 的选择器；若当前 auto 指向别的 run，按实际身份记录差异，不能改 latest、新 store 或 refresh 凑回旧身份。`publish_read.py` 初次只发布 manager 工作区；独立 announcement analysis 的原只读发布另有明确条件，`/announcements` 与 `/selection` 不因此变成已验收。本包不交伪造回执、不恢复部署，也不把单条公告通路升级为全部策略完成。

材料提交自身的固定 URL 是本包分发身份；其中不会写入其自身不可预知的 Git commit hash。交接时用最终消息提供的固定材料 URL，代码 authority 始终是本页开头唯一的 `6daed627...`。
