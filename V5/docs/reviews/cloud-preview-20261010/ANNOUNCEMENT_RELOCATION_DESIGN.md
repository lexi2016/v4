# 公告跨机只读导入合同与最小路径映射设计

状态：SOURCE_AUDIT / DESIGN_ONLY。基于5d5e7d65c6704fc9a5f8dd36678eecc67e33ba1d，只读审计；未实施适配、未导入、未运行测试、未读取/上传Mac原件。下述是原reader的必要传输合同，不是已获授权的数据清单，也不扩展01—18或P0—P5。

## 1. 实际调用链和身份阻断

文件前缀A=`V5/vendor/announcement_revision_baseline/`，M=`V5/vendor/manager_plan_baseline/`，V=`V5/src/v5_shadow/`。

| 源码位置 | 实际行为和迁移影响 |
|---|---|
| V/announcement_offline_reader.py:49、90、119—136 | 独立-I/-B子进程；按binding.revision_manifest_sha256选择revision owner；binding.root当前既是物理根也是逻辑身份，manager_binding.owner_root必须等于str(root)。SafeRoot仅允许root和root.parent.parent。直接改root到/workspace会失败 |
| A/ops/run_v5_decision_revision.py:116—173 | 再核decision_revision原文件SHA；revision_root必须等于self.root且必须是parent_root/decision_revisions/revision_id；每次_verify_evidence重新读取真正父根，不接受只留revision副本 |
| A/ops/run_v5_decision_revision.py:23—41 | _parent调用verify_recovery，读取父analysis、owner receipt和父handoff；比较原语义product SHA与receipt文件SHA，再调用原产品/审核/注册校验 |
| A/ops/run_v5_offline_analysis.py:21—60 | recovery_receipt及OFFLINE_RECOVERY的derived_root必须等于父逻辑根；source_root必须与original/v5_owner_identity.private_root一致；校验BLOCKED policy、forbidden_roots、所有original_files/recovered_files；调用正文terminal校验 |
| A/ops/run_v5_decision_revision.py:158—173 | revision保存的parent_analysis/parent_owner_receipt必须与父根字节相同；source_recovery_receipt须同SHA；revision.source_files必须等于父recovered_files且每件核SHA；三件inputs及Reviewer的decision_revision原绑定必须一致 |
| A/ops/run_v5_private_announcement.py:33、38、285 | _absolute做expanduser/abspath；_no_symlink逐祖先检查；_check_state_tree直接os.walk并拒绝树中任何link |
| A/infrastructure/owned_io.py:28、67、103 | SafeRoot以真实root从/开始O_NOFOLLOW/dir-fd读取，校验普通文件、大小、root inode身份；不能只靠字符串检查替代 |
| A/v4/manager_research/workspace_announcements.py:1765、1851、1965、2085 | _handoff_root会Path(store.root).resolve(strict=True)；terminal/handoff直接Path读取、遍历和resolve；bodies文件集合必须精确相等。因此只映射SafeRoot不够 |
| A/v4/manager_research/store.py:73—83、116 | 构造器Path(root)，要求jobs/products/receipts目录；_read按relative_to(self.root)经SafeRoot读。当前worker把ensure_directory换成只检查存在，不能临时写目录 |
| V/announcement_offline_reader.py:32—46、147—175 | 从M/workspace_announcements提取四个原consumer函数，保留A的较新terminal validator；不能用M整文件覆盖A。analysis读回比解码对象、产品文件SHA前后再核，最后校验原binding未变 |

A manifest PIN=da392a57bf93dd9a5b4355d934e267a7c5c4fe495e90779364627e8a8f118d8a；manager consumer descriptor PIN=61f288f00095ce0e60adf20598123e702d855462ac7d7216334ecfd1064933f5。普通非revision owner还有独立PIN/identity路径，不混入本合同。源码SHA索引见announcement-relocation-source-index.json。

## 2. 两个原逻辑根、一个物理映射

定义P=decision_revision.parent_root，R=decision_revision.revision_root，r=decision_revision.revision_id，u=父recovery_receipt.source_run_id，t/p=原target/publication。必须先证明R=P/decision_revisions/r、u与binding.evidence_run_id一致；不能用经理run 5b4...代替公告evidence run。

导入后仅在授权私有位置创建物理树P'，R'=P'/decision_revisions/r，保留完整相对布局。只需要精确前缀P→P'，不接受任意路径替换或第二个不同映射。原source_root是来源身份；本reader读取original/副本，不要求访问/复制原source_root整个目录。原forbidden_roots只参与逻辑隔离比较，不映射成可访问根。

外层传输封套（新本地描述，不写进原件）必须记录：schema版本、原逻辑P/R及revision_id、物理P'、原binding文件SHA、revision文件SHA、recovery文件SHA、父产品语义SHA及文件SHA、父receipt文件SHA、target/publication/evidence run、原app/consumer PIN、每件(role,parent或revision,relative_path,bytes,sha256)、整个封套SHA。原件尚未取得，以上实际值及最终展开文件数量均UNRESOLVED，不写占位假值。

原逻辑路径必须来自核过外部预期SHA的原binding/revision/recovery三件，并相互一致；不能信任上传目录名字或仅自声明SHA。封套记录的是接收/映射，不是新审核通过证明、不改变PIT/获取时间、不生成Reviewer。原validate_registered_handoff只证明字节与声明审核谱系，不认证平台Reviewer身份；独立审核身份仍由原交接证据证明。

## 3. 最小必要文件白名单（集合规则，等待原清单展开）

先经用户授权取得少量身份/清单文件，在不执行owner、不采集的情况下解析；随后按以下并集展开精确路径/长度/SHA。任何manifest列入校验的文件都不能以“正文已有副本”为由删掉；若集合很大，报告其实际必要体积，而非搬整棵Mac目录。不能用已知392计数、4363文件摘要替代枚举。包内无凭据、Keychain、环境、会话、其他批次和其他业务树。

**父根P：**

1. `recovery_receipt.json`、`OFFLINE_RECOVERY.json`、`transport_policy.json`、`original/v5_owner_identity.json`。
2. 对recovery_receipt.original_files每个键n，必须有`original/n`及其原SHA；对recovered_files每个键n，必须有`n`及原SHA。两张表完整保留，不抽样。
3. `workspace_announcements/t/eastmoney_date_catalog/YYYYMMDD/analysis.v1.json`及同目录`owner_import_receipt.v1.json`（YYYYMMDD严格取原publication去横线）。
4. 下述H(P)和T(P)；即使未包含于recovered_files，也因实际读路径必需。

**修订根R：**

1. `manager_binding.v1.json`、`decision_revision.json`、`decision_revision_owner_identity.json`、`offline_import_readback.json`。
2. `parent_analysis.v1.json`、`parent_owner_import_receipt.v1.json`、`source_recovery_receipt.json`，与真正父件分别逐字/原SHA绑定。
3. `inputs/semantic_catalog.json`、`inputs/reviewer_output.json`、`inputs/article_decisions.json`，严格按revision.input_files；输入三键集合必须精确一致。
4. revision.source_files全部相对路径及原SHA（必须等于父recovered_files），不只正文文件。
5. 本根`workspace_announcements/t/eastmoney_date_catalog/YYYYMMDD/analysis.v1.json`及`owner_import_receipt.v1.json`。
6. H(R)、T(R)。另需本根jobs/products/receipts空目录结构使只读store构造成功；这是目录结构要求，不要求复制其他经理任务，也不生成产品/回执。

**H(X)：** E(X)=`X/announcement_agent_runs/u/evidence/`。必须有`handoff_manifest.v1.json`和原_HANDOFF_FILES十件：`catalog_read.json`、`body_corpus.json`、`body_corpus_manifest.json`、`body_batch_receipt.json`、`capture_receipt.json`、`semantic_catalog.json`、`reader_output.json`、`reviewer_output.json`、`article_decisions.json`、`analysis_product.json`。article_decisions的原NOT_ASSESSED例外只能按该根原manifest条件执行，不能套用到EXPLICIT_DISPOSITIONS的revision。所有原file SHA、语义product SHA及审核绑定继续原校验。

**T(X)：** E(X)/body_batch必须存在；`bodies/<art_code>.json`必须与原catalog/manifest文章ID集合精确相等，不多不少，含失败文章。对BODY_CAPTURE_FAILED且保留非空pages的文章，另需`article_receipts/<art_code>.json`和每页`receipts/<sha256(request_url UTF-8)>.json`；页序、文本/reference hash、时间与来源主体均依原validator。失败且pages为空时函数直接返回，不因此额外要求article/page receipt，除非原recovered_files已列入。其他raw/PDF/image文件若在原original_files/recovered_files中仍必须传；单凭引用URL不发网络补齐、不扩大通配目录。

并集去重按“逻辑根+相对路径”，不能把父/子同名不同内容覆盖。拒绝绝对相对项、..、反斜杠/NUL、symlink/hardlink、特殊文件、重名归档条目与大小越界。接收端用固定目录FD/O_NOFOLLOW展开，逐文件比SHA，不从原件运行代码。无法获得上述manifest即不能生成最终授权文件白名单；当前只有确定性集合规则。

## 4. 最小适配候选：只在V5隔离worker内

现有配置没有合法的重定位开关。不要改JSON内owner_root/derived_root/revision_root/parent_root，不改SHA/time/Reviewer，不伪建/Users，不用symlink/bind mount/chroot/权限扩大，也不绕过父验证。只把传给原owner的root改成云端路径仍会失败。

候选限定一个V5只读路径适配辅助模块及announcement_offline_reader中可选接入。未实施。原则为“逻辑Path参与原identity/str/relative_to/parent/forbidden比较，物理P'只用于白名单IO”。不是在解析JSON后重写字段，也不是绕过verify_recovery。

必要接点必须同时覆盖：

- worker先以物理FD读原binding并核外部SHA，解析逻辑R/P；保留逻辑身份供原owner。请求摘要同时绑定原件SHA和封套SHA，不能把新封套SHA当原binding SHA。
- 局部数据Path适配保留逻辑字符串、join/parent/relative_to和原父子关系；read_bytes/read_text/stat/is_file/is_dir/iterdir/resolve只能通过P'受控FD读取白名单。resolve检查真实物理无link后返回等价逻辑路径；不得直接用继承Path的方法漏读/Users。Path(store.root)/Path(evidence)不得剥掉适配。
- SafeRoot构造只将已准入逻辑数据根落到P'对应物理目录，保留原O_NOFOLLOW/大小/inode规则；其外部owner.root仍逻辑。_no_symlink/_check_state_tree的实际探测定向到物理树，保留逻辑forbidden比较。
- 挂接范围仅上述已固定owner、store、workspace_announcements的worker模块/函数；不全局改pathlib.Path、os.open、os.walk或builtins.open，不更换vendor源码，不触碰源码APP_ROOT/_verify_app/calendar读取。未覆盖的新数据IO一律拒绝而不是fallback到本机路径。
- 原网络/进程/写入audit拒绝继续存在；允许源码/标准库原读范围不扩张。_write_once仍只验证既存identity字节，缺件不得创建。校验前后每件SHA不变；不执行adopt/create/prepare/register/import/capture等写命令，仅原readback/consumption。

这是需要负测和独审的设计，不是现成映射开关；若不能在这些局部接点保持Path语义和原校验等价，应停止该候选，不能退而放宽门禁。原数据到达前不承诺具体映射实现已可用。

## 5. 后续验证计划（本轮均未运行）

1. 合成父+revision完整原合同，直接逻辑位置读与重定位读内容相等、原件全树SHA不变；分别明确合成，不冒真实392。
2. 错P/R父子关系、错binding/revision/recovery SHA、父根缺失、只给revision副本、错父产品/receipt、Reviewer revision不符均拒绝。
3. 删任一original/recovered/handoff/正文/保留页回执、bodies多/少一件、改页URL/时间/文本/来源主体均拒绝；FAILED保留FAILED，不提升COMPLETE。
4. Path构造丢映射、resolve逃逸、../绝对项、相邻前缀、symlink/目录换根/hardlink、读取未列文件和源码路径映射尝试均拒绝；无/Users创建、无全局Path补丁、无网络/写入。
5. 原cutoff/target/publication、默认上一交易日、迟到CURRENT_RECOVERY和显式历史拒绝不变；核请求摘要和封套摘要不同职责。
6. 原件授权后先展开准确清单并逐SHA收齐，再只读验证；随后按原工作包做真实三策略同run保存/API/UI，独立审核和Mac验收不因映射通过而免除。

到此准备结束，等待用户上传授权及原件。没有新增通用平台、调度器、第二producer或替代18模块的工作清单。
