# Issue 31 R2 Mac 独立复核

**Verdict:** `REVIEWED=FAIL`；`TESTED=PASS`（17 项 fetch recovery、3 项 appendix targeted tests）；`BEHAVIOR_VERIFIED=PARTIAL`；完整日常恢复目标 `FAIL`。完整 ZIP 原字节回读为 `CANNOT_CONFIRM`。P0=0、P1=1、P2=0。

## P1 — 正文含文字时，图片清单缺项仍可被接受

[候选 wechat_article_fetch.py](/Users/lexi/Desktop/学习/v3_system/选股池/微信公众号/evidence/issue31_r2_mac_20261009/mac_actual/candidate/scripts/wechat_article_fetch.py:62) 的 `_validate_article_body` 在第 72–73 行遇到非空正文就返回，跳过 BODY 图片 URL 与 manifest 的比较。独立复现里，`js_content` 同时含正文和一张 mmbiz 图片，但输入 manifest 为零行；`_prepare_promotion` 仍接受该来源，`identity.image_count=0` 且 promoted image 数为 0。证据见 [article_body_promotion_repro_rerun.log](/Users/lexi/Desktop/学习/v3_system/选股池/微信公众号/evidence/issue31_r2_mac_20261009/reviewer/article_body_promotion_repro_rerun.log)。这会把遗漏图片的正文当成来源身份已验证并继续进入包/OCR路径。

同一函数对无文字正文逐项比较所有 `<img>`，但真实外部采集器只保留 mmbiz URL、排除 GIF 并按 URL 去重（`wechat_article_intake.py` 第 273–284 行）。因此合法的 image-only 正文若重复引用同一 URL，会被候选拒绝。复现见 [article_body_binding_repro.log](/Users/lexi/Desktop/学习/v3_system/选股池/微信公众号/evidence/issue31_r2_mac_20261009/reviewer/article_body_binding_repro.log)。

最小修订：所有 BODY（含有文字的 BODY）使用真实采集器相同的有序、去重 mmbiz 图片投影，再与 manifest 比对；回归覆盖缺失 manifest 行、重复 URL、GIF。

## 验收证据

- 已复核冻结差异 SHA-256 `d1de7a1bb64ed0756ee4dd9b35906a5f8c5ffa22af9dd939811b1d87441806e3` 和 Writer receipt SHA-256 `86c28fb160125d0766a6ac2169385460302a90158a1ddcf24c9a76afc72a56e8`；候选文件摘要与 `SOURCE_MANIFEST.json` 一致。正式业务源码及原 run 未修改。
- 独立副本 targeted tests：`test_wechat_article_fetch_recovery` 17/17 PASS；appendix 指定 3 项 PASS。命令与输出位于 [r2_fetch_recovery_tests.log](/Users/lexi/Desktop/学习/v3_system/选股池/微信公众号/evidence/issue31_r2_mac_20261009/reviewer/r2_fetch_recovery_tests.log) 和 [r2_appendix_regression_tests.log](/Users/lexi/Desktop/学习/v3_system/选股池/微信公众号/evidence/issue31_r2_mac_20261009/reviewer/r2_appendix_regression_tests.log)。
- 两项复跑均在 `evidence/issue31_r2_mac_20261009/reviewer/candidate/tests` 运行，Python 使用 `/Users/lexi/Desktop/学习/v3_system/选股池/微信公众号/evidence/wechat_fix_r1_mac_20261008/test_venv/bin/python`。环境变量分别将 `TMPDIR` 指向 `reviewer/tmp/fetch`、`reviewer/tmp/appendix`，并将 `PYTHONPATH` 指向独立副本的 `candidate/tests:candidate/scripts`；命令均为 `python -m unittest -v` 加上述测试名（完整 argv 记录在 `REVIEW_RECEIPT.json`）。
- 当前真实采集器脚本为 `/Users/lexi/.codex/skills/wechat-research-intake/scripts/wechat_article_intake.py`，SHA-256 `de9499c2e049bcf6d3da5ea6375831aece5eb2374e338e057f04e60dfd0c6058`。用已保存 HTML 和本地 50 图缓存复跑 CLI：50/50 manifest 与 promoted images 对齐、无网络请求、`prepare_ocr` exit 0。该证据仅证明保存输入/缓存复用路径。
- 独立副本上 `prepare_ocr`、OCR canary、OCR full 均 exit 0，分别复用 3/3 和 50/50 缓存，OCR attempts 为 0；没有声称本次运行了新 OCR。日志为 [runner_vision_reuse.log](/Users/lexi/Desktop/学习/v3_system/选股池/微信公众号/evidence/issue31_r2_mac_20261009/reviewer/runner_vision_reuse.log)。
- 默认 runner 对历史 run 的 fetch exit 1，子 adapter exit 2；子命令含 `--skip-ocr`，网络尝试为 0，历史 run 未完成 R2 身份/推广绑定，故未恢复。见 [runner_fetch.log](/Users/lexi/Desktop/学习/v3_system/选股池/微信公众号/evidence/issue31_r2_mac_20261009/reviewer/runner_fetch.log) 与 [runner_fetch_argv.jsonl](/Users/lexi/Desktop/学习/v3_system/选股池/微信公众号/evidence/issue31_r2_mac_20261009/reviewer/runner_fetch_argv.jsonl)。
- Appendix CLI 返回 `CANNOT_CONFIRM`，保留全部 108 行（A=81、BJ=3、HK=24），0 行有价格观测；当前 A-share PARTIAL receipt 事实保留，HK 前序 receipt 缺失。它没有把不完整覆盖误报为表现结果。
- 新候选 ZIP Drive metadata 与本地预期大小 11,012,113 bytes、SHA `f335cc03ee936315f9f91d825235208bb25ee899a3d92a832dd57e4aee8de34a` 对应；raw bytes 未取得，connector 下载返回 HTTP 403 / code 1010。因此完整包原字节回读 `CANNOT_CONFIRM`，不能升级为已验证。

## 最终状态

`REVIEWED=FAIL`：存在 P1 图片来源绑定缺口。`TESTED=PASS` 仅适用于上述 targeted suites 和指定缓存子路径。`BEHAVIOR_VERIFIED=PARTIAL`：采集器离线缓存、Vision 缓存复用和 appendix 失败披露得到验证；默认 runner 对历史 run 未完成恢复。完整 ZIP raw-byte delivery 仍为 `CANNOT_CONFIRM`。

全部独立日志、probe 与 receipt 保存在 `evidence/issue31_r2_mac_20261009/reviewer/`；本次没有修改候选源码、正式源码、原 run 或其他业务文件。
