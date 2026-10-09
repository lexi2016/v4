# Issue #31 — R3 增量修订

**独立复核状态：PASS_OFFLINE_SCOPE（仅离线候选范围）。本目录是候选增量和证据，不是部署记录。Issue #31 保持打开。**

本轮直接接续 [9735baa2 Mac 验收回传](https://github.com/lexi2016/v4/tree/9735baa24d1c26c0836850a1336888022c77781a/wechat-workflow-issue31-mac-20261009) 与 [独立 FAIL 评论](https://github.com/lexi2016/v4/issues/31#issuecomment-6072731268)。当前 runner、collector 和继承规则已经齐备，并用于本次实现。未重做此前已通过的无关 Mac/OCR/附录范围。

## 修订内容

### 所有 BODY 统一检查图片完整性

正文有文字时也必须检查图片清单。图片投影采用回传 collector 的实际规则：从 js_content 取图，处理 HTML 实体，只保留 mmbiz、排除 wx_fmt=gif，并按 URL 首次出现的顺序去重。投影结果须与 manifest 的连续 index、有序 URL 一致；原来的文件路径、图片字节、长度与 SHA 门禁继续有效。

这覆盖了 Mac P1 的两条路径：带文字正文漏 manifest 行应拒绝；合法的重复图片引用应按真实 collector 去重后接受。错序、多项和缺项都有针对性断言。

### 历史 run 使用当前重新验证的证据

正常入口仍是现有 runner。需要恢复历史来源时，显式提供原本地冻结 ZIP，以及从外部固定回执取得的 expected ZIP SHA、package_id 和 input_digest。适配器复用现有 handoff ZIP 验证器，核验正文、图片清单、原始 HTML 摘要及每张图片的绑定。

路径已经重绑的隔离副本还需提供原始 summary 与原始 CSV 的只读文件；两者必须精确匹配冻结 ZIP 中 source_intake_sha256 与 source_manifest_sha256。新入口只接受真实 collector 的四个路径字段，以及 CSV local_path 的受限根目录映射；其他初始值与行列顺序必须一致。无需猜测未随回传附上的 COPY_REBIND_RECEIPT schema。

接纳后写入新的 REVALIDATION_RECEIPT.json，明确 historical_promotion_claimed=false、collector_invoked=false、network_attempts=0。它证明当前工件通过验证，不补造旧 ATTEMPT/PROMOTION。Runner 在复用时重新核对本次证据，只有通过冻结 HTML 绑定的历史来源才可走 http_status=0 兼容路径。OCR 就绪状态从现有缓存工件独立判断。

### 继续使用现有 prepare/OCR 消费者

工作副本中的路径必须已经位于当前 run 内，并能由现有消费者解析。之后 prepare_ocr 仅可更新既有 download_status、image_size、ocr_text_length 三列的值，还要分别与图片状态、解码尺寸和已验证 OCR 记录核对；列/行顺序、URL、index、图片长度和 SHA 等稳定字段仍受绑定。没有修改 collector、prepare、Vision、handoff 或通用路径 helper。

## 变更范围与字节绑定

只改动以下三个产品文件，其余 32 个候选基线文件不变。完整 before/after SHA 与来源见 [SOURCE_MANIFEST.json](SOURCE_MANIFEST.json)，组合基线来源逐文件列于 [BASELINE_PROVENANCE.json](BASELINE_PROVENANCE.json)。fetch/test 的 before 是固定 R2；runner 的 before 是本次 Mac source_current。

| 文件 | Before SHA 前 12 位 | After SHA 前 12 位 | After bytes |
|---|---|---|---:|
| `wechat_article_fetch.py` | `5d648dac0b71` | `192564aea742` | 91,948 |
| `wechat_pipeline_runner.py` | `b65fc26d232d` | `46d8761e44a2` | 77,999 |
| `test_wechat_article_fetch_recovery.py` | `3d5a55f32c62` | `3c2316ff77f2` | 52,232 |

- [actual_diff.patch](actual_diff.patch)：三个文件的完整增量。
- [runtime.patch](runtime.patch) 与 [tests.patch](tests.patch)：按运行代码/测试拆分。
- [source/](source/) 和 [before/](before/)：精确 after 与 before 字节。
- [补丁正反向校验](evidence/root/PATCH_ROUNDTRIP.json)：从组合基线应用后等于候选全部字节；反向应用后恢复原始全部字节。这是包装校验，不代替产品验收。

## 验证结果

| 验证层 | 本轮结果 | 证据 |
|---|---|---|
| 独立源码审查 | PASS_OFFLINE_SCOPE；开放 P0/P1/P2 均为 0，R2-MAC-001 在此候选中已解决 | [独立结论](evidence/reviewer/R3_REVIEW_FINDINGS.md) / [机器回执](evidence/reviewer/R3_REVIEW_RECEIPT.json) |
| 独立受影响回归 | 25 passed + 3 subtests；exit 0 | [完整日志](evidence/reviewer/r3_fetch_recovery_pytest.log) |
| 历史接纳与拒绝子集 | 2 passed，属于上述 25 项，不另行累加 | [子集日志](evidence/reviewer/r3_adoption_focus_pytest.log) |
| 独立恢复/续跑探针 | 保存 HTML 的 http_status=0，runner → adapter → prepare_ocr；50 张合成图；source 与既有 OCR 缓存字节保持；接纳/续跑阶段零 collector 调用与网络尝试；next stage=package | [可复现脚本](evidence/reviewer/r3_runner_resume_prepare_probe.py) / [探针日志](evidence/reviewer/r3_runner_resume_prepare_probe.log) |
| R3 实际 Mac 运行 | 尚未执行；CANNOT_CONFIRM | [增量复验计划](MAC_REACCEPTANCE_PLAN.md) |
| 既有 R2 Mac 子路径 | 保留 17+3 targeted PASS、真实 50 图及 OCR 缓存复用证据；不升级为 R3 Mac PASS | [收到的 Mac 证据](evidence/root/RECEIVED_MAC_EVIDENCE.json) |
| 完整 Drive ZIP 回读 | CANNOT_CONFIRM；HTTP403/code1010 | [失败回执](evidence/root/DRIVE_R2_ZIP_READBACK.json) |

独立探针在 Linux 用平台标志模拟 runner 的 Mac 分支，运行的是实际候选 runner、adapter 子进程和既有 prepare_ocr 子路径；它不是 Mac 设备上的执行。探针准备阶段生成了合成 fixture，其中 collector_returncode=17 仅属于构造测试数据；被测接纳/续跑阶段没有采集或网络请求。没有执行新的 OCR 引擎。


原始日志和失败用例保留于 evidence/writer 与 evidence/reviewer。提供的 R2 复现脚本用于展示旧缺陷：旧版退出 0 并展示错误接受；修复后遇到预期拒绝而退出 1，这个退出码不计为通过。新行为以具备明确断言的回归和独立复核为依据。

Writer 的初版回执曾将一次修复前复现的退出码抄为 1，已对照日志更正为 0；原回执及命令文档以 *.initial.* 保存，并在当前回执中注明更正。该元数据修正没有改变三个产品文件或重新执行产品测试。

## Mac 增量复验入口

按 [MAC_REACCEPTANCE_PLAN.md](MAC_REACCEPTANCE_PLAN.md) 准备新的隔离候选和 working run，再执行 [精确命令](evidence/writer/R3_ACCEPTANCE_COMMANDS.md)。保留 run basename，用不同父目录隔离；不覆盖原 R1/R2 验收目录、正式源码或原 run。代码 before SHA 不相符时，先据实际文件重做增量，不整树覆盖。

命令文档会先强制核对原 ZIP 的外部 expected SHA，再从包内取得两个原件 SHA，通过限定目录的文件名与 SHA 查找原件；只输出命中路径。未找到原始字节、非法路径重绑或源字节不符时，给出具体拒绝，不把当前副本重新算出的 SHA 当作历史锚点。

当前 Linux 环境没有执行新 R3 的 Mac 验收，也没有取得那篇文章、50 张原图或原 ZIP 的原字节。新版本的 Mac 结果须用最终源码 SHA 和实际命令另行记录。你已提供的旧 Mac 验收和当前源码已用于本轮，不再被列为缺失输入。

## Drive 与总状态

本轮对固定 R2 Mac 验收 ZIP 做了一次原字节读取，仍返回 HTTP403 / error code 1010，失败发生在现有连接器返回的下载地址到当前环境这一层。完整 ZIP 字节未取得，未计算下载 SHA，不能将 metadata 或小文件回读当作整包验证。详见 [DRIVE_R2_ZIP_READBACK.json](evidence/root/DRIVE_R2_ZIP_READBACK.json)。没有推断 OAuth 原因、改共享设置或新增 Drive 客户端。

[STATUS.json](STATUS.json) 区分本次离线修订、已收到的 R2 Mac 子路径 PASS、尚未执行的 R3 Mac 增量验收，以及仍未通过的完整 ZIP 回读。未集成、未部署。单篇恢复或本次离线测试通过，都不能作为关闭 Issue #31 的依据。

回执保留执行时的原始绝对路径；交付副本的相对链接见 [EVIDENCE_INDEX.md](EVIDENCE_INDEX.md)。

所有交付文件的 byte/SHA 清单见 [DELIVERY_MANIFEST.json](DELIVERY_MANIFEST.json)；该清单按约定不包含自身。
