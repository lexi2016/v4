# Mac Work：只验 BI-01 公告实例身份

本包只修 Issue #17 BI-01，接续 #8。**不是已部署修复。不要覆盖活动服务，不采集、不改生产数据、BUY 或 Stage。** runtime.patch 只改一个函数中的 ID；before/after 同时保留完整 workspace_announcements.py 和未改的 eastmoney_run_history.py。旧冻结包不变。

## 适用前像与三方边界

1. 产品前像 A：`95426ac3db39f6d86ec2031617c4ac180d40868e` 的 `research/manager-r9-consumer-r1-20260930/final_business_20260930/after/app/`。不是 main，也不是 bdc 的旧公告文件。完整 SHA 在 `SOURCE_PINS.json`。
2. 本包后像 B：仅将 event_id 改为原 digest 的 `[source, issuer code, art_code, body_sha256]`。不改变同版本去重、capture occurrences、时钟、来源/正文校验。eastmoney_run_history.py 前后完全相同；API6726/95426 的其它改动都必须保留。
3. Mac 实物 C：当前源码、候选 release、活动 API 各有自己的 owner、磁盘字节和解释器；它们不能由 A 或 bdc 推定。先读取 C 的完整 SHA，与 A/B 逐文件比较。若 C!=A，禁止用 B 整文件覆盖：在独立副本按 A→B 的单个 diff 做三方移植，保留 C 已有 API6726 与 Mac 修复，再记录移植后 SHA。冲突无法确认则保留差异作为输入缺口，不安装。scheduler 15:55 与 17:20 owner 也不互相代替。

无需数据库迁移或历史删除。原产品保存 source/code/art_code/body_sha256，普通读时重新投影 ID。已有离线导出/旧页面缓存需重新读回，不能宣称旧缓存已迁移。art_code 已保留逻辑聚合信息，无新增 logical_event_id 字段或其它合同字段。

## 一次定向离线复跑

使用 **实际服务的 Python 3.14.6** 路径建立独立测试环境或调用其已有 pytest；**不必降级 Python**。本次云端为 Python 3.12.14，不能替代 Mac 3.14.6 验收。Node 要支持原生 TypeScript 类型擦除（本次 Node 24.19.0）；依赖仅放在隔离测试目录。

先取得本 PR 固定提交以及 TEST_SOURCE_LOCK.json 的四个 fetch_refs。源码锁只用固定 Git blob，API6726 两文件按原 r3b_input + integration_actual_diff 精确重建，并核 SHA；不是把旧 workspace 当新源码。空 py.typed 与测试用 PDF license 按原 DEPENDENCY_MANIFEST 固定 SHA 补齐，未绕过 vendor 校验。

```bash
# 在本交付仓库根目录；设置绝对路径，不指向活动应用或正式数据目录。
PACK="$PWD/research/issue17-bi01-20261001"
PY_SERVICE=/absolute/path/to/service/python3.14
"$PY_SERVICE" --version  # 验收应记录 Python 3.14.6
"$PY_SERVICE" -m venv /tmp/bi01-work-venv
/tmp/bi01-work-venv/bin/python -m pip install pytest==9.1.1
mkdir /tmp/bi01-work-node
cp "$PACK/tests/package.json" "$PACK/tests/package-lock.json" /tmp/bi01-work-node/
npm ci --prefix /tmp/bi01-work-node --cache /tmp/bi01-work-npm-cache --ignore-scripts
/tmp/bi01-work-venv/bin/python "$PACK/tools/replay.py" \
  --output /tmp/bi01-work-after --jsdom /tmp/bi01-work-node/node_modules/jsdom
```

输出目录必须全新，已有则换一个名字，不删除复用。应为 **5 passed**、receipt.exit_code=0、source_unchanged=true；原 TS validator 通过三实例、拒绝真重复；原 DOM renderer 三个完整正文可读。可单独加 `--image before` 复现：预期 1 failed/4 passed，报 EASTMONEY_HK_DOCUMENT_IDENTITY_INVALID。这是预期红例，不是部署失败。仅跑这 5 例，不重跑旧 14/27/33 套件。

本 replay 验固定源码依赖闭包，不代表整套 API 装配。对 C 的独立副本应用前，先比对 SOURCE_PINS 的两文件前像及 preserve；完全一致时在副本 app 根执行 `git apply --check /绝对路径/runtime.patch`，再 `git apply /绝对路径/runtime.patch`，核 after SHA。C 不一致走上述三方流程。禁止对活动 app 执行这些命令。

移植后在实际候选副本上复跑同一测试，指向候选原模块而不是 replay 的冻结 app：设置 `BI01_APP`、`PYTHONPATH` 为候选绝对 app 路径，并在 PYTHONPATH 追加 replay 输出的 `support`；`BI01_JSDOM` 指向测试 jsdom。使用上述 3.14.6 环境运行 `python -m pytest -q -s -p no:cacheprovider -c /dev/null "$PACK/tests"`。测试只写 pytest 临时 Store，网络连接由 conftest 禁止。记录 candidate SHA、解释器、日志和加载模块路径；不得以这里的 fixture 代替实际发行人资格验收。

Mac 后续在独立、无采集的验收环境验证普通 GET → 完整 validateManagerWorkspace → 原页面，与活动源/候选绑定分开记录。本次仅执行真实公告 lane 的生产 validator 和 jsdom 原渲染器；尚未执行完整 HTTP、整页浏览器、真实 provider、自然运行、Mac runtime。不要把本补丁据此标为全工作台通过，也不要顺手修 BI-02/日历/R3A/Stage。

## 最小回退

本次不激活服务，失败就保留日志并弃用独立候选。精确 B 的独立副本可先 `git apply --reverse --check runtime.patch` 再 reverse；或仅恢复已备份的该文件并核 A SHA。对于三方移植 C，恢复本次移植前备份的 C 字节，绝不拿 A 覆盖 C。历史 Store、原始材料及 capture occurrences 不回滚、不删。任何之后的部署/服务切换另需授权，按对应 owner 原 manifest/plist 回退，不把其它 release 当回退点。
