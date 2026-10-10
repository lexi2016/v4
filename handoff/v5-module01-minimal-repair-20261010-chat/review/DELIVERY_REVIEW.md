# 第一模块交付文档受限复核

日期：2026-10-10。审查对象：`work/handoff/v5-module01-minimal-repair-20261010-chat/`。本轮只核交付说明、manifest、只读前像检查器与已有验证记录；没有重跑生产测试、启动候选、读 Mac 业务原件或执行任何发布 / 回退。

## 结论

**已审材料没有 Critical / Important 文档缺陷，可继续封包和分发。** 有一项不阻塞交付的回退命令工作目录表述建议，已交给主控。此结论不代替尚待完成的最终包索引、材料提交 / 分支远端读回，也不批准部署。

## 已读材料

- `START_HERE.md`。
- `MAC_APPLY_AND_ACCEPTANCE.md` 全文。
- `SOURCE_MANIFEST.json` 与 `verify_preimage.py`。
- `validation/PATCH_VERIFICATION.json`、`validation/PREIMAGE_VERIFICATION.json`。
- 当审查期间生成的 `validation/VALIDATION.md`。
- 辅助核对 `provenance/CODE_REMOTE_READBACK.json`、前端来源 / 冻结文件清单、`review/FRONTEND_REVIEW.md`、`validation/HTTP_CHAIN_RECEIPT.json`。
- 为核实说明中的函数 / CLI 参数，只读查看原 `publish_read.py`、`assemble_web.py`、`announcement_analysis_api.py`、module / gateway main 与 `activate_generation`，没有再次运行这些业务入口。

## Critical

未发现。

## Important

未发现。

## Minor

### D1 — 回退代码命令宜显式指定 candidate 工作目录

`MAC_APPLY_AND_ACCEPTANCE.md` 第 10.2 节最后一段已经明确只允许在退出服务的隔离候选 checkout 回退，但文本中的命令为裸 `git apply --check "$V5_DELIVERY_ROOT/reverse.patch"` 与 apply。前面的操作曾 `cd "$V5_WEB_ROOT"`，连续按说明操作时不宜依赖隐含 cwd。

建议将两条命令都写成 `git -C "$V5_CANDIDATE_ROOT" apply ...`。这不改变回退语义、范围或权限。现有 after / before guard 会识别错误目录或未恢复的字节，因此该问题不按阻塞项分类。已即时发给 root。

## 身份、前像和覆盖范围核对

代码前像 F 为 `f7cb731c384ee6890a87d16c19a5b5a621779477`，唯一候选 C 为 `6daed6271313b5ae5324c8948f163258ab8d1fa3`。后续 H 被明确定义为材料分发身份，没有当成源码前像或第二个业务基线。两种操作模式分别是固定 F + patch 与直接固定 C checkout；C 模式明确禁止再次叠加 runtime.patch。

SOURCE_MANIFEST 的 20 路径实际为 10 个 MODIFY + 10 个 ADD，与摘要的 7 运行 / 配置文件、3 原测试适配、10 新测试 / 支持文件一致。CODE_REMOTE_READBACK 也记录同一 C、唯一父 F 和 20 个文件。该远端记录由主控提供，本 reviewer 本轮没有另发远端查询或冒称独立提交。

前像校验器只读：检查指定 20 路径、before / after 包内影像、patch SHA / 长度、目标 SHA / 长度 / Git blob，新增路径在 before 必须不存在，拒绝根 / 路径软链接和非普通文件。说明准确写明文件 mode 虽在 manifest 中记录，脚本不单独验执行位；不把 PASS 夸成完整 Git / 运行身份验证。

PATCH_VERIFICATION 记录正向 check / apply、20 after hash、反向 check / apply、20 before / 新增路径不存在。PREIMAGE_VERIFICATION 记录正确 before / after 成功以及篡改前像时非零退出、目标字节不变。它们证明隔离副本的字节转换，不证明现场现役前像。

Mac 所有可写路径都要求操作人确认并新建隔离目录；原 Git 工作树仅作对象来源。没有给未知现役路径的 cp / kill / 端口抢占 / symlink 覆盖命令，也没有要求在原 owner 根补造 marker。现役 V4、BUY、8910 和原 owner 数据边界持续保留。

## 真实 run、发布与 CLI 核对

文档沿用输入交接的 Mac run `5b4feaf7ef7d4d13bec639e90b6d3db0`、计划 SHA `56556a67ddc1a562e82b38e750be92fcfda070945397cc4eacffd1c79f42bcf0` 和原生成时间，但明确这些不是本轮实测。392 被正确解释为决定数，未等同入选股票数。

原请求转只读只改 action / view / now，其余 inputs、日期、owner binding、输出根和 SHA 均保留。`--expected-run` 被准确说明为发布前拒错 guard；当前 auto 选到其他 run 时停止回传，禁止改 latest、复制旧 run 到新 store、refresh 或新建 operation_id 来凑身份。

文档中的 publisher 参数、输出文件名和 stdout 形状符合实际 CLI。它明确区分独立保存的 owner envelope 与 publisher 的 publication / plan_product stdout；没有要求把后者传给需要 `.result.payload` 的原测试。独立只读预检和之后的 publisher 是两次操作，其中 publisher 内仍只读一次并在发布前守卫 run，说明没有误称跨两次操作的全响应字节必相同。

module / gateway 三个启动命令的参数、实际 18897 / 18898 默认 upstream、frontend root / manifest 参数都匹配。现场端口需另行确认，不能把默认值当授权；仅允许修改新配置中的端口。

独立 announcement analysis 使用原 `--binding`、`--config`、`--expected-generation null` CLI；完整 binding 原样传递，包括存在时的 revision 身份。explicit / compact / default query 与原 publisher 相符，列表 / selection 未因此发布，准确保留可能的 503 局部缺口。

回退分为切回旧整套入口，以及同根同 release 的 `activate_generation(... expected_generation=...)` CAS。新根 previous_generation=null 不能冒称存在旧 generation；没有手工改 active、跨 release 填入旧 generation 或无条件覆盖冲突的指令。

## 页面和只读能力边界

文档中的只读标头服务于“用既有材料生成计划”入口。第 9 节明确说明既有公告增量更新仍是独立入口，本批 gateway 未配置该 writer，验收不触发它，也不据计划按钮禁用宣称所有更新按钮已改造。

首次失败 / 缺 read_context / 历史 / 取消 / 切日 / 切 view 的操作均要求不触发计划 POST；未知生成结果不借 latest 判断失败。实际浏览器要求普通静态 HTML / JS 与真实 API，明确区别 jsdom、诊断页以及云端空 fixture。`cloudActualReadback.spec.ts` 的旧 20261012 空样本合同没有被拿来验健康 Mac 公告。

## 数字和证据边界核对

- 映射 CSV 实际 41 行；前端来源清单实际 125 original inputs、134 effective files，摘要相符。
- 新 exact-run 14、公告合同 9、发布 2、安装 4；最终新 HTTP 6 连同原回归 54，总数没有跨组相加冒称全工程通过。
- 最终 module01 三份前端 spec 是 27 API + 14 DOM + 3 HTTP = 44；五份受影响 spec 是 85 PASS / 2 原件失败，未写全绿。
- 原完整前端 442 PASS / 23 FAIL 的 17 原 owner/Mac 缺件 + 4 指定 cloud artifact + 2 旧合同差异分类相符；两项旧合同后来通过，没有冒称完整 suite 被重跑通过。
- 原 Python `Ran 222 tests; errors=6; skipped=6` 原样保留；补齐固定 F 的 archive manifest 后只报告对应 8 / 8，未改称原入口通过。
- 最终 typecheck / build 0 引用最终日志；真实合成 HTTP 元数据绑定最终 implementation hashes，同时保留 synthetic 标记与完整体未上传的说明。未把元数据摘要文件宣称为可直接喂原 frontend spec 的完整原响应。
- Mac 原请求 / offline binding / 392 体量 / API / 静态资源 / 内置浏览器 / 自然周期 / 完整三策略的 NOT_RUN 没有被定向合成测试升级。

## 本 reviewer 额外检查

仅对 MAC 说明中的 19 个 bash 代码块执行 `bash -n`，均退出 0；对其 Python heredoc 做 AST 语法解析通过。**没有执行其中任何安装、发布、服务启动或回退命令。** 本轮没有重跑任何生产测试。

`PACKAGE_INDEX.json`、`validation/NOT_RUN.md` 和 `DEPENDENCIES_AND_SCOPE.md` 在上述主干检查时仍在生成；最终包索引 / 文档齐备性、H 提交和分支读回属于主控后续封包步骤，不以本次受限复核替代。

## 主控关闭的文档 Minor

最终 Mac §10.2 两条反向应用命令均已写明 `git -C "$V5_CANDIDATE_ROOT"`；不再依赖当前工作目录。最终文档静态校验记录在 `validation/DOCUMENT_CHECKS.json`。
