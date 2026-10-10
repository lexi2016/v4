# M04/M15：7115f652 Mac 实测回执

候选：`7115f65267a1496d0ca8214cc14130f8c2b65d87`；父提交 `4a8063eb3ac4bdbbb30bd7659c5a38c4b32e6d28`；原 tree `cb35ab854c2002d59938b697039584e0b07b3094`。
本轮基于原授权分支头 `cdd430e4dcd8d3e8c5949baff21a4831b4689444` 提交最小差异，保留外部身份问题包。

## 实际结果

- 隔离快照 `/Users/lexi/Documents/Codex/2026-10-10/task-2/candidate`：608 个必要文件先全部通过 Git blob SHA 核对；595 复用本机精确字节，13 通过既有 GitHub 连接器补齐。它是源码快照，不是完整 git checkout。直接 clone 曾因 DNS 失败退出 128。
- MacOS 26.6.2 / Python 3.13.12。完整原 canonical 的七项 producer 依赖 SHA 全匹配。系统 Python 3.9.6 不适配候选类型注解；默认 `/var` 临时路径触发原 symlink 门，使用现有物理 TMPDIR 后继续，未放松安全检查。
- 六组完整回归：**59 项，58 通过，1 error，退出 1**。唯一 error 是 `test_ordinary_auto_get_serves_committed_owner_response_without_computation` 在本地 socket bind 被沙箱拒绝：`PermissionError: [Errno 1] Operation not permitted`。未扩大权限；完整套件不签 PASS。
- 最终 producer＋三个映射用例：**9/9，退出 0**。
- 独立 Reviewer 用不同 agent 身份复跑三个映射用例：**3/3，退出 0，6.391s**。行业无显式 ticker、同句 AVGO 直接关系、跨中文逗号不冒认直接关系，均核原经理持久化与独立 `action=read` 的同 run ID、计划 SHA 和 diagnostics；`natural_verified=false`。
- 以上为**合成工程输入**。独立结论限于该范围的 BEHAVIOR_VERIFIED；真实新材料、普通 HTTP、本轮 UI 和自然接续未通过验收，不据此关闭 M04/M15。

## 最小修正及 SHA

初次 direct 正例失败的原因：合成正文中的中文逗号将公司主体与 AVGO 分为两个原 parser clause，原算法正确不跨句认定关系。只修正合成正例为同一主体关系句，并保留原正文为负例。原算法、producer 及门禁未改。

| 文件 | 修改后 SHA256 | Git blob |
|---|---|---|
| `V5/tests/test_archive_article_v2.py` | `4b4900947bbe83dbc39b966ec84503e481c84f4d32cf389c500c34f07760a10b` | `bbe4e0a5f3802afc8e3dac1ca27004797628ad33` |
| `V5/producers/archive-acquisition-v2/manifest.json` | `d6fee52a848fd6cb7a8428f9da96977d44e2bd01306298383c324fb26a2363a5` | `8ca74eb707e1aa0d29a26a4f0a1984e890fee86f` |

606 个未改文件继续匹配候选 blob。Reviewer 核对原 manifest blob `07cebf773a604cf7fe6b39cd8e0f2d36958b7450` 与新字节，确认仅改 `new_source_sha256` 中测试文件的一项值，历史 `static_review_changes` 保留。原 manager parser/relation 文件保持固定字节。

## 可复现命令

以下全部在 `/Users/lexi/Documents/Codex/2026-10-10/task-2/candidate/V5` 执行。共同环境：

```sh
export TMPDIR=/private/var/folders/mw/045dzcpj70x3m5nnfwj6lmnm0000gn/T
export V5_ARCHIVE_PRODUCER_SOURCE_ROOT=/Users/lexi/Documents/Codex/2026-10-02/task/V4_SOURCE_SYNC_20261005/payload/handoff/v4-running-source-20261005/canonical
export PYTHONPATH=src:tests
```

六组命令（退出 1，59 项）：

```sh
/Users/lexi/.local/bin/python3.13 -B -m unittest test_archive_acquisition_producer test_archive_article_v2 test_current_us_research test_manager_archive_reader test_us_mapping_scope test_manager_plan -v
```

最终 producer＋聚焦命令（退出 0，9 项）：

```sh
/Users/lexi/.local/bin/python3.13 -B -m unittest test_archive_acquisition_producer test_archive_article_v2.ArticleV2ChainTests.test_industry_material_mapping_needs_no_explicit_us_or_etf_ticker test_archive_article_v2.ArticleV2ChainTests.test_explicit_us_relation_reaches_original_direct_mapping_and_same_run test_archive_article_v2.ArticleV2ChainTests.test_symbol_in_following_clause_is_not_attributed_to_hk_issuer -v
```

独立 Reviewer 执行相同聚焦命令但不含 `test_archive_acquisition_producer`（退出 0，3 项）。各回归是不同覆盖范围，数量不相加。

## 真实输入与采集阻塞

只读核 `current-us-8a667188` 现有输入：20261009 US payload SHA256 `928cd4ae8089a792ea1a3cfab490c9217c4249d6c29c11aeaa9cee879f0fb4e3` 与 manifest/receipt 一致；native HK identity run `2624664162720b55c473d083`，693 行，artifact SHA256 `2726ae16fc3718a8b5cfb5eda0434f52efc72fd4434d0d244f6244ed1bd65f36` 与 manifest/receipt 一致。

这些是可复用来源，不能替代新文章取得证据。该项目快照没有 v3 acquisition receipt、同 run pages/recent/summary 和可证明同批原 builder archive 输入。旧 V1 归档 2058 条缺 retrieved_at/available_at，未补造时间、身份或关系，未运行真实 article-v2 导入。

进一步检查既有已授权采集链：官方 CLI 可执行，原 analyzer、refetch root、selector panel 存在。只读 `/Users/lexi/Documents/Codex/2026-08-13/v35-019ff682/shared-research-runtime/npm/node_modules/.bin/zsxq-cli doctor` **退出 5**，`Authentication: keychain error: exit status 152`。未读取凭据值，未升级权限；在此停止 topics 请求、新采集和原 builder 调用。此为现有认证不可用的具体阻塞，不以“暂无 v3 文件”作为唯一停止理由。`article_id/dedupe_key` 原 builder 输入问题仍 **OPEN**，由原外部问题包处理。

V4、现役61796、四键三股和其他任务文件未改；未部署、未启动浏览器、未执行交易。

## 本机证据索引

根：`/Users/lexi/Documents/Codex/2026-10-10/task-2`

- `MAC_RUN_REPORT.md`：Writer 完整命令、SHA、输入核对、初始失败说明。
- `mac-m04-m15-regression-final.log`：六组 59 项原始结果。
- `mac-m04-m15-targeted-final.log`：最终 9 项。
- `review/mac-review.md`、`review/mac-review-focused.log`：独立三项及精确差异核验。
- `acquisition-readiness.log`：认证 readiness 退出 5。
- `candidate-tree.json`、`source-commit-identity.json`：来源身份。
