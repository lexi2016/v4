# Issue #31 — 2026-10-09 Mac 实际验收回传

**本机验收已经实际执行；结论为 REVIEWED=FAIL。Issue #31 必须保持打开。**
本目录为固定 R2 提交 `6e1f34ab74741635f8b30c67887fa5fc07f0e6c2` 的 Mac 隔离验收与兼容修复输入，不是部署包，不表示已集成运行源码。

## 先读

1. [独立 Reviewer 结论](REVIEW_FINDINGS.md) 与 [机器回执](REVIEW_RECEIPT.json)。
2. [Writer 实际命令、来源 SHA、工件 SHA、回滚副本](evidence/WRITER_RECEIPT.json)。
3. [当前 Mac 源码和继承规则绑定](MAC_INPUT_BINDING.json)。此前缺少的实际 runner、外部 collector、父级 AGENTS 已补齐。
4. [针对真实本机基线的候选 diff](evidence/ACTUAL_DIFF.patch)。
5. [P1 最小复现调用方法](reviewer/R2_MAC_001_REPRO.md) 与 [可运行脚本](reviewer/reproduce_r2_mac_001.py)。脚本由独立 Reviewer 从已执行探针整理，支持候选路径参数；整理后未另行重跑。

## 结果与剩余问题

| 范围 | 实际结果 |
|---|---|
| Mac 环境 | macOS 26.6.2 / arm64 / Python 3.12.14 |
| 独立 targeted rerun | fetch recovery 17/17，appendix 3/3 PASS；不是完整 Linux 148 项套件的重复结果 |
| 真正 runner 子进程参数 | 已记录，含 `--skip-ocr` |
| 历史 run 日常恢复 | runner exit 1 / adapter exit 2，旧来源没有 R2 attempt / promotion 绑定；零网络请求，完整恢复未通过 |
| 真实 collector 保存 HTML + 原图缓存 | 50/50 原图复用，零网络；collector 的 downloaded_image_count 也计入 OK_REUSED，不能称为新下载 |
| prepare / Vision canary / full | 3/3 与 50/50 缓存复用，新增 OCR attempts=0；不声称重新跑了 OCR 引擎 |
| 冻结 | 新隔离包 PACKAGE_READY；本地 ZIP SHA 在 Writer receipt 中 |
| 附录真实 CLI + 合成输入 | 108 行 A81/BJ3/HK24 全保留，价格全为 null/CANNOT_CONFIRM，PARTIAL 汇总事实保留；未重新测量旧真实大表5125行 |
| Drive | 新包上传及 metadata 核对成功；完整 ZIP 下载 HTTP403/code1010，原字节回读 CANNOT_CONFIRM |
| REVIEWED | FAIL：P0=0、P1=1、P2=0 |
| BEHAVIOR_VERIFIED | PARTIAL；完整日常恢复 FAIL |
| INTEGRATED / DEPLOYED | 均否；正式源码和原 run 未改 |

## 必修 P1：有文字的 BODY 跳过图片完整性检查

候选 `wechat_article_fetch.py` 第62–77行，`_validate_article_body` 在正文含文字时提前返回，未比对正文图片与 manifest。独立复现中，正文带一张 mmbiz 图片但 manifest 零行，`_prepare_promotion` 仍接受，并记录 image_count=0。

同一函数的 image-only 路径还与真实 collector 的图片投影口径不一致：真实 collector 只取 mmbiz、排除 GIF、按 URL 有序去重；重复图片 URL 可能被候选错误拒绝。参见独立复现日志和 source_current/external/wechat_article_intake.py 第273–284行。

下一轮应统一所有 BODY 的有序去重图片投影，覆盖含文字漏图、重复 URL、GIF 等情况；另处理历史 run 的受控恢复兼容。不得伪造 promotion receipt、放宽来源身份或重新下载已验证图片来制造通过。仅修候选并交同范围独立 Reviewer；不要整树覆盖 Mac/R1。

## 回传资料边界

- `source_current/` 是本次验收前 Mac 实际源码的原字节快照；不是已应用 R2 的运行树。
- R2 的四个代码/测试文件 after SHA 与远程 manifest 一致；流程文档只在隔离副本移植了增量段落，保留本机真实路径，故文档 after SHA 与脱敏远程快照不同。
- `inherited_instructions/` 是实际读取的父级与项目规则快照；不把历史副本当当前运行入口。
- 未向 GitHub 上传文章正文、图片、OCR、市场面板、venv、完整仓库状态或凭证。
- 本目录提供结果与当前缺失源码，下一位 Chat 不再以“没有本机反馈”为阻塞；剩余事项已定位为具体兼容缺陷和传输缺口。

本次隔离包 Drive ID：`1kzaeWN8SqAvKKt7E4zhgFoehOYsBtNrW`，仅存于本地复核目录，未替换正式研究包。期望 ZIP SHA：`f335cc03ee936315f9f91d825235208bb25ee899a3d92a832dd57e4aee8de34a`，11,012,113 bytes；这是本地期望摘要，不能误称远端下载已匹配。详见 [完整回读失败回执](evidence/drive_readback/CANDIDATE_FULL_ZIP_READBACK_RECEIPT.json)。

RESEARCH_ONLY=true；production_allowed=false、buy_gate_updated=false、orders_sent=false。
