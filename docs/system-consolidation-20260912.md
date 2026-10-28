# 系统整合 2026-09-12

本批只固定 8873 的可重建源码基线、同源比较和回退证据。没有业务算法迁移、市场原始数据复制、模型或 BUY 门修改，也没有 release 或 LaunchAgent 变更。

## 冻结范围

唯一源码仓库是 `/Users/lexi/Desktop/学习/v4_app`。选定运行范围包含 `apps/api`、`apps/web/src`、`domains`、`infrastructure`、`v4`、`ops`、`contracts`、`stage_center` 和受 Git 管理的 `upstreams/v3_shared_data` 代码。运行所需的 `stage_center` 与共享数据上游会被纳入字节校验；三个 upstream 符号链接只核对链接身份和目标字符串，不递归读取目标数据。

既有运行 release 是 `/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/20260911-v4app-cache-safe-deploy-v5/app`。本批把它作为只读对照对象。生成的 `apps/web/dist`、release-only manifest、runtime inventory 和外部 upstream 目标内容不在源码比较范围，相关门保持 `CANNOT_CONFIRM`，直到有独立 receipt。

历史 `/Users/lexi/Desktop/学习/v3.5` 仅作只读归档。本批不会把它作为运行时 fallback，也不复制其源码。

## 可重跑证据

```bash
/Users/lexi/Desktop/学习/runtime/venvs/v3.5-mac/bin/python ops/verify_source_release.py \
  --source-root "/Users/lexi/Desktop/学习/v4_app" \
  --release-root "/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/20260911-v4app-cache-safe-deploy-v5/app" \
  --receipt "/Users/lexi/Desktop/学习/agents调试/system_consolidation_20260912/source-release-compare.json" \
  --git-snapshot-dir "/Users/lexi/Desktop/学习/agents调试/system_consolidation_20260912/git-snapshot-after-writer"
```

校验 receipt 同时给出 Git commit/branch/status、文件数量、逐文件 SHA-256、树摘要、缺失/多余/不一致项以及链接目标。退出码 `0` 只代表选定范围 PASS；全 release 的部署状态仍按证据层单独判断。工具不会写 release、共享数据、服务配置或交易状态。

证据目录还包含本批开始前的干净 Git 状态和关键源码 SHA，以及四个相关 LaunchAgent plist 的原始备份。备份用于回退核对，不代表本轮已经启停或切换调度。

## 已知缺口

主控提供的当前 API 观察值是默认日期 `20260911`、预选池 A179/HK100 共 279 行且为 `PARTIAL`、`STAGE_0925` 20 行且标记 `SHARED_STAGE_CENTER_READ_ONLY`、manager 10 行且为 `PARTIAL`、review contract `v3_5.review_envelope.v1`。运行图的 app root 可核对，但缺 runtime inventory/dependency manifest 时总状态保持 `CANNOT_CONFIRM`。这些值用于后续依赖整合，不能由本批源码 receipt 代替。
