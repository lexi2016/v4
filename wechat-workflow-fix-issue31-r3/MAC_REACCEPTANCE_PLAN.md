# Issue #31 R3 — Mac 增量复验范围

本页是新候选的复验计划；不是已执行的 Mac 回执。R2 的 Mac 反馈、17+3 项 targeted PASS 和 50 图缓存复用证据已经齐备，不重复索要或重跑这些旧范围。

## 候选准备

沿用 Mac 回传中已经验证过的 Python 3.12.14 环境，并记录实际 sys.executable 与版本；命令文档中的 python3 应解析到该环境，不需要另建 OCR 或采集入口。

- 沿用实际读取过的父级/项目 AGENTS，使用独立 Luna Max Writer 与不同身份的 Luna Max Reviewer。
- 在新的隔离目录准备候选。先逐文件校验 SOURCE_MANIFEST.json 的 before SHA，再应用 actual_diff.patch；校验 after SHA。不同 SHA 的当前文件必须据实际差异重做增量并独立复核。
- R3 patch 的 fetch/test before 来自固定 R2；runner before 来自 9735baa2 的当前 Mac snapshot。保持原 R1、R2 验收目录、正式源码和原 run 不变。
- 继续使用当前 Mac collector、现有 prepare/Vision 与 handoff。R3 不提供替换 collector 或 OCR 入口。

## 历史输入副本

使用已有且已验证的复制/路径重绑流程，准备新的隔离 working run。用不同父目录隔离，保留原 run basename `20261008_html_recovery_ZfZPPo1xSsfROmFZbaqSuw`，使其与冻结包 source_run_id 一致。它的 summary 与 manifest 路径必须指向该 working run 内的对应工件，并能由现有 prepare_ocr 正常解析。不要把指向旧绝对根的未经重绑副本当作已可运行的副本。

保留原冻结 run 的原始 summary、原始图片 CSV 和原始 raw HTML/图片/OCR 字节。需要路径重绑时，只允许 collector 的 html_path、image_manifest_path、ocr_text_path、image_checkpoint_path，以及 CSV 的 local_path 按同一旧根映射到新根；首次接纳时，其他字段、CSV 行顺序与列顺序保持一致。后续 prepare_ocr 只允许更新已经存在的 download_status、image_size、ocr_text_length 三列的值，而且要分别通过实际图像状态、解码尺寸和已验证 OCR 记录核验；不允许增删或重排列、行，URL/index/图片SHA/byte长度等稳定字段仍须一致。由新 adapter 对原/新文件独立核验，不使用未经读取的 COPY_REBIND_RECEIPT 内容作假设。

固定本地原 ZIP 的 expected SHA、package_id 和 input_digest 见收到的 Mac WRITER_RECEIPT.input_identity.original_frozen_package。expected SHA 必须来自这份外部固定回执，不能对当前 working copy 现算后当作历史锚点。若当前 summary/CSV 因路径重绑与包绑定的原始 SHA 不同，显式提供原 run 的两件原始文件；它们自身须精确匹配包中的原始 SHA。

## 新增必验范围

1. 含文字 + mmbiz 图片但 manifest 缺行必须拒绝；完整行应通过。重复 URL 有序去重；GIF/非 mmbiz 图与真实 collector 同口径。错序、多项、缺项仍拒绝。
2. 真实 runner 的 fetch 子进程必须含 --skip-ocr；显式受控接纳只写本次 source revalidation 证据。不得补造旧 ATTEMPT/PROMOTION，也不得以原summary自报 PASS 为凭据。
3. 可信原 ZIP 与可证明路径重绑的 working run 接纳后，默认 fetch 再运行应复用本次证据；不得调用网络采集或新增 OCR attempts。
4. 经实际 runner fetch 后调用既有 prepare_ocr，确认真实消费者能读取当前路径；BODY/raw HTML/图片和既有 OCR 文本 SHA 前后保持。R2 已通过的 Vision 50 图缓存结果仍是已有证据，不在这里声称重新跑引擎。
5. 错误外部 ZIP SHA、错误原summary/CSV SHA、正文漏图、非路径字段改动、非法路径/根外路径、图像字节篡改必须拒绝。保留失败日志和新回执。

## 结果与停止条件

新 Mac 独立回执必须分别列 TESTED、REVIEWED、BEHAVIOR_VERIFIED、INTEGRATED、DEPLOYED，并绑定最终代码 SHA、输入身份、实际argv、exit code、日志/工件SHA。仅 Linux 合成验证不能升级为 Mac 实际验证。若缺少原件或存在无法证明的路径变化，记录具体哪个原件/字段不匹配；无需重新索要已完整提供的 runner、collector 或旧Mac日志。

Drive 完整 ZIP 原字节回读仍是独立未通过项。此次对固定 R2 ZIP 的一次读取返回 HTTP403/code1010，未取得完整字节、未计算下载 SHA。沿用失败回执，不猜权限、不改共享设置、不进行同一方式反复重试。

本次交付和单篇恢复都不构成关闭 Issue #31 的依据。Issue 保持打开；未集成、未部署。

## 精确命令

使用 [R3_ACCEPTANCE_COMMANDS.md](evidence/writer/R3_ACCEPTANCE_COMMANDS.md) 中的精确入口和参数。WECHAT_WORKTREE 指包含 scripts/ 的 wechat 根目录；actual_diff.patch 应从其父目录应用，使补丁中的 wechat/scripts 路径对应。源文件前后 SHA 见 [SOURCE_MANIFEST.json](SOURCE_MANIFEST.json)。原件定位脚本会先断言整个 ZIP 的外部 expected SHA，再读取包内 source_intake_sha256 与 source_manifest_sha256，通过 rg 查找并计算候选文件 SHA；只输出匹配路径，不打印正文或图片。
