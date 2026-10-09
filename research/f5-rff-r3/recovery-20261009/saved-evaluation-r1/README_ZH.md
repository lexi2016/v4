# RFF 已保存分数评价入口修复包

对应 [Issue #33](https://github.com/lexi2016/v4/issues/33)，基准提交 `4c5fb40122cec7a40036bfda5e4d9516d82dcd18`。

本包交付新入口源码与合成验收；真实命中率尚未计算，不能证明提升。新本机 binding 的独立验收与 parent release 仍需按 Issue #33 执行。本包没有形成或激活真实执行授权。

## 使用文件

- `after/`：完整可安装内容。将整个目录内容放入一个新的代码目录；准确 Mac 命令、准备新绑定、输出解释与回滚见 `after/README_ZH.md`。
- `patches/runtime.patch` 与 `patches/runtime.reverse.patch`：仅五个新增运行文件的正向/反向补丁，路径相对于新代码目录；完整 after 已包含这些文件，不重复应用正向补丁。
- `SOURCE_MAP_DELTA.json`：命名基准提交、新增源码及不变依赖的精确摘要；原 SOURCE_MAP 与历史 worker/binding/seal/registry 不变。
- `review/VERIFICATION.json`、完整日志及两份独立代码复核：142 项新合成测试通过，涵盖元数据绑定、原评价组合、worker 计数、官方登记与异常监控。
- `MANIFEST_SHA256.json`：包内所有文件（自身除外）的 SHA256、字节数和 Git blob SHA1。

## 交付和证据边界

专用分支为 `chat/issue33-rff-saved-evaluation-20261009-r1`，新增路径均在 `research/f5-rff-r3/recovery-20261009/saved-evaluation-r1/`。实际发布提交和读回核验随下载 ZIP 中的 `PUBLICATION.json` 提供；该回执在提交后生成，不写入它所描述的同一提交，避免自引用。下载 ZIP 的最终 manifest 会计入该回执。分支用于代码审阅，不表示研究 release。

`review/metric_parity.md`、`review/lifecycle_review.md` 与 `review/saved_eval_review_handoff.md` 是分项实现/诊断说明。最终独立结论以 `RUNNER_INDEPENDENT_REVIEW.md`、`WORKER_FRAMES_INDEPENDENT_REVIEW.md` 及其精确 SHA 范围为准。历史阶段的 RED 或尚待整合描述不替代最终验收。

原 PR #5 的 Mac 29/29 是已接受的既有证据，此次未重跑。此容器的原始 POSIX RSS backend 存在 PID namespace 不匹配；进程测试使用真实 spawn/信号/原 cleanup 与明确合成的 RSS 观测，不宣称已验证 Mac 完整 worker/L04。所有输入样本和测试 registry 均为临时合成数据；交付包仅含源码、JSON 元数据、说明和测试日志。
