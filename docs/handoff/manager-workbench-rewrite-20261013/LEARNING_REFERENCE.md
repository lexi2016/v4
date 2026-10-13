# 学习规则与开发环境（冻结参考）

本文件只作学习参考；新模块不得运行或导入这里的旧经理代码。实际源文件身份来自本机canonical工作树，不证明活动运行版本。以下依赖/挂载字节允许远端chat在隔离环境复现新模块测试；不是全应用分发包。复制到临时测试环境的构建壳不进入正式V4代码或新长期服务，测试后关闭。若实际环境不支持现有版本，报告NOT_RUN及真实差异，不自行修改共享依赖。

公告既有规则版本为POSITIVE_OPERATING_RESEARCH_V1：严格正向候选由逐篇disposition、direction、evidence_sufficiency的合取筛出，再验证正文、资格、owner可用时间及reviewed_at不晚于cutoff。旧源码只验证/投影人工或agent明确判定，不存在金额或增长率自动阈值。本次自动Reader/Reviewer按共同合同重新实现语义判定，必须保存原文支持，不能把旧函数当真实阅读。

## v4/manager_research/announcement_processing.py

原文件SHA256：`8a66c5b53814567c9209070c8b62b490ce7f8c194cbfa551a0d32450e7654c3a`。

原行22–34：

```python
_HKEX_ID = re.compile(r"^HKEX:\d{5,20}$")
_CODE = re.compile(r"^HK\.\d{5}$")
_RULE_REVIEW_SCHEMA = "v4.manager_research.announcement_rule_review.v1"
_RULE_RECEIPT_SCHEMA = "v4.manager_research.announcement_rule_review_receipt.v1"
_RULE_VERSION = "POSITIVE_OPERATING_RESEARCH_V1"
_HK = ZoneInfo("Asia/Hong_Kong")
_RULE_DISPOSITIONS = {
    "SELECTED_EVENT", "SELECTED_PERFORMANCE", "CONDITIONAL_WATCH",
    "NOT_SELECTED", "NOT_ASSESSED",
}
_RULE_DIRECTIONS = {"POSITIVE", "NEGATIVE", "MIXED", "NEUTRAL", "UNKNOWN"}
_RULE_EVIDENCE = {"VERIFIED_EXISTING_FACTS", "INSUFFICIENT_EXISTING_FACTS"}
_WINDOW_INPUT_SCHEMA = "v4.manager_research.announcement_preopen_window_inputs.v1"
```

原行785–788：

```python
            positive = (event["disposition"] in {"SELECTED_EVENT", "SELECTED_PERFORMANCE"}
                and event["direction"] == "POSITIVE"
                and event["evidence_sufficiency"] == "VERIFIED_EXISTING_FACTS")
            if positive:
```

原行854–857：

```python
    positive = [event for event in events if event["disposition"] in {
        "SELECTED_EVENT", "SELECTED_PERFORMANCE"} and event["direction"] == "POSITIVE"
        and event["evidence_sufficiency"] == "VERIFIED_EXISTING_FACTS"]
    actual_positive = [row for row in actual_evaluations if row["status"] == "AVAILABLE_AT_AS_OF"]
```

## v4/manager_research/announcement_selection.py

原文件SHA256：`6cc3e4ddfc4848e684770b5bfc360abb585d112a311bc2a98978a5b56952b697`。

原行16–24：

```python
READ_SCHEMA = "v4.manager_research.announcement_stock_selection_read.v1"
DISPOSITIONS = {
    "SELECTED_EVENT",
    "SELECTED_PERFORMANCE",
    "CONDITIONAL_WATCH",
    "NOT_SELECTED",
    "NOT_ASSESSED",
}
SELECTED = {"SELECTED_EVENT", "SELECTED_PERFORMANCE"}
```

原行133–142：

```python
        if disposition in SELECTED and not raw.get("selection_basis") in {"OPERATING_EVENT", "PERFORMANCE_RESEARCH"}:
            raise ValueError("ANNOUNCEMENT_SELECTION_BASIS_INVALID")
        if disposition == "SELECTED_EVENT" and raw.get("selection_basis") != "OPERATING_EVENT":
            raise ValueError("ANNOUNCEMENT_SELECTION_BASIS_INVALID")
        if disposition == "SELECTED_PERFORMANCE" and raw.get("selection_basis") != "PERFORMANCE_RESEARCH":
            raise ValueError("ANNOUNCEMENT_SELECTION_BASIS_INVALID")
        if disposition not in SELECTED and raw.get("selection_basis") not in {
            "CONDITIONAL_WATCH", "NOT_SELECTED", "NOT_ASSESSED",
        }:
            raise ValueError("ANNOUNCEMENT_SELECTION_BASIS_INVALID")
```

原行356–365：

```python
    for group in groups.values():
        dispositions = {row["disposition"] for row in group["articles"]}
        if dispositions & SELECTED:
            status = "SELECTED"
        elif "CONDITIONAL_WATCH" in dispositions:
            status = "CONDITIONAL_WATCH"
        elif "NOT_ASSESSED" in dispositions:
            status = "NOT_ASSESSED"
        else:
            status = "NOT_SELECTED"
```

## pyproject.toml

原文件SHA256：`4f792160e360aa7947e20e2f8456a5136558dff43356ce89e529cbdef561492e`。

```toml
[project]
name = "v3-5"
version = "0.1.0"
description = "Independent V3.5 application foundation"
requires-python = ">=3.14"
dependencies = [
  "fastapi>=0.128,<1.0",
  "numpy>=2.3,<3",
  "pandas>=2.3,<4",
  "pyarrow>=22,<25",
  "requests>=2.32,<3",
  "uvicorn>=0.40,<1.0",
]

[dependency-groups]
dev = [
  "httpx>=0.28,<1.0",
  "pytest>=9.0,<10.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
# Keep warnings-as-errors, but tolerate the starlette 1.6 TestClient(httpx)
# deprecation until the suites migrate to the replacement client.
addopts = "-W error -W default::starlette.exceptions.StarletteDeprecationWarning"
```

## apps/web/package.json

原文件SHA256：`c19353356c407e397c4eeda0bf052c0229e6fb814c55de43eb60a43263306d2b`。

```json
{
  "name": "v3-5-web",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "test": "vitest run",
    "typecheck": "vue-tsc --noEmit",
    "build": "vite build"
  },
  "devDependencies": {
    "@testing-library/vue": "^8.1.0",
    "@types/node": "^24.0.0",
    "@vitejs/plugin-vue": "^6.0.0",
    "jsdom": "^28.0.0",
    "typescript": "^5.9.0",
    "vite": "^7.0.0",
    "vitest": "^4.0.0",
    "vue": "^3.5.0",
    "vue-tsc": "^3.1.0"
  }
}
```

## apps/web/tsconfig.json

原文件SHA256：`aeb4f907263b28da51895370935cecf1152aec0f142e191b90d5877e3b37aebe`。

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "strict": true,
    "skipLibCheck": true,
    "noEmit": true,
    "types": ["vitest/globals"]
  },
  "include": ["src/**/*.ts", "src/**/*.vue"]
}
```

## apps/web/vite.config.ts

原文件SHA256：`759c67c769f5f2553ec54eee08a1e2ecf958a6323006f0eb9228083b9dfde123`。

```typescript
import { defineConfig } from "vitest/config";
import { resolve } from "node:path";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  test: { environment: "jsdom" },
  build: {
    rollupOptions: {
      input: {
        main: resolve(__dirname, "index.html"),
        dailyResearchCommand: resolve(__dirname, "daily-research-command/index.html"),
        managerSelection: resolve(__dirname, "manager-selection/index.html"),
      },
    },
  },
});
```

## apps/web/src/manager-selection/main.ts

原文件SHA256：`769df8d97df6c27785cbaa248b80fb6cc447cfe3afbd627e32fe925d2065b843`。

```typescript
import { createApp } from "vue";

import ManagerSelectionView from "../views/ManagerSelectionView.vue";

createApp(ManagerSelectionView).mount("#manager-selection");
```

## apps/web/manager-selection/index.html

原文件SHA256：`dde06bee12772b83d670ca1d86569d7a2da6476e7972e24ade20dee3f3fcba2f`。

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta name="theme-color" content="#102033" />
    <title>经理选股工作台 · V4</title>
  </head>
  <body>
    <div id="manager-selection"></div>
    <script type="module" src="/src/manager-selection/main.ts"></script>
  </body>
</html>
```
