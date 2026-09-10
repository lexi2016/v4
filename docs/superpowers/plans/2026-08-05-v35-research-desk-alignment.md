# V3.5 研报决策台对齐 V3 前端设计 方案

> **目标**：在 V3.5 用 Vue 忠实复刻 V3 研报决策台的**完整前端设计**（交互点 + 状态管理 + 数据流），同时利用 V3.5 的组件化/响应式优势重构，不复制 V3 巨型单文件（fupan_dashboard_v3.html 8235 行）。
> **状态**：`PLAN_WRITTEN / 待批准`

## 1. 背景与原则

- V3 研报决策台是 `fupan_dashboard_v3.html` 里的一个视图（`view=research`），晨盘/公众号是其子视图（`normalizeTopView` 把 morning/wechat 归并到 research）。
- V3 是 8235 行单文件（HTML+CSS+JS 全内联）。V3.5 必须用 Vue 组件化重构，**不复制巨型文件**。
- V3.5 后端 lane API 已就绪（`/api/v3/research/lane`，读取 V3 research-module 生成的 snapshot + 外围块，37 块数据，8/4 真实验证通过）。
- 保持 `production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。

## 2. 现状

| 文件 | 行数 | 状态 |
|---|---|---|
| `apps/api/v35_api/research_lane_router.py` | ~90 | ✅ 已实现 lane + dates 端点 |
| `infrastructure/v3_research_lane_source.py` | ~150 | ✅ 只读读取 V3 snapshot + 外围块 |
| `apps/web/src/views/ResearchView.vue` | 291 | ⚠️ 三栏布局初版，交互不完整 |
| `apps/web/src/api/research_lane.ts` | 36 | ✅ lane API 客户端 |
| `apps/web/src/styles/v3-research-lane.css` | 593 | ⚠️ 从 V3 提取，需精简 |

**已知缺口**（相对 V3 完整设计）：
1. 早盘新闻 tabs（`data-morning-filter`）未做
2. 来源列（zsxq/finance/ai/ocr/wechat#researchWechatSource）交互/滚动未做
3. 白毛 X 栏（`baimaoX`）未接入
4. research-events 事件流（EventSource + `_research_event`）未做
5. feed 8 类源合成（stock/zsxq/key/finance/ai/ocr/morning/workbench）不完整
6. 股票时间轴去重合并（compactStockTimelineEvents）未做

## 3. 对齐 V3 前端设计的组件化方案

### 3.1 视图与导航（对齐 V3 setView 机制）

V3.5 保持 App.vue 条件渲染（无 vue-router，与 V3 单页切换一致）。研报决策台作为 `researchActive` 子视图。

```
App.vue
  └── ResearchView.vue (researchActive=true 时显示)
        ├── ResearchStatusStrip.vue     ← 状态条（15 格 + 公众号按钮）
        ├── ResearchImpactList.vue      ← 左栏 股票层（impact 卡）
        ├── ResearchFeedPane.vue        ← 中栏 情报阅读（feed tabs + 列表）
        │     └── ResearchFeedCard.vue  ← 单一 feed 卡组件（morning/workbench/ai/finance/zsxq 复用）
        ├── ResearchSourceColumns.vue   ← 中栏下方 来源列（zsxq/finance/ai/ocr/wechat）
        ├── ResearchContextPane.vue     ← 右栏 来源状态（信号/时间线/质量）
        └── ResearchAppendix.vue        ← cannot_confirm 折叠区
```

**交互点对齐**（V3 源码行号 → V3.5 实现）：
| V3 交互 | V3 源码 | V3.5 实现 |
|---|---|---|
| feed tabs 过滤 | `[data-research-filter]` 行 7089 | `feedFilter` ref + computed 过滤 |
| 早盘新闻 tabs | `[data-morning-filter]` 行 7225 | `morningFilter` ref + computed |
| 公众号按钮滚动 | `[data-wechat-entry]` 行 6990 + `#researchWechatBtn` 行 8218 → `scrollResearchWechatIntoView` 行 3246 | 公众号按钮 `@click` 滚动到 `#researchWechatSource` |
| 原文链接 | feed 卡 `a.hourly-pill` | `<a target="_blank">` |
| 刷新强刷 | 行 8201（research 视图重置 filter） | `loadLatest()` 重拉 lane |

### 3.2 状态管理（对齐 V3 state）

V3.5 用 Vue 响应式 ref/computed 取代 V3 的全局 `state`：
| V3 state 字段 | V3.5 对应 |
|---|---|
| `researchLane` | `payload` ref（lane API 响应） |
| `baimaoX` / `wechatArticles` | 新增 baimao/wechat API 客户端 + ref（task13/14） |
| `researchFeedFilter` | `feedFilter` ref |
| `morningFilter` | `morningFilter` ref |
| `researchEventId` / `researchDate` | 从 `source_manifest.event_id` 派生 |
| `researchWechatScrollPending` | `scrollToWechat()` 直接滚动 |

### 3.3 数据流

```
lane API (/api/v3/research/lane?research_date=)
  → ResearchView payload ref
  → computed 派生：
      stockDaily → ResearchImpactList
      stockTimeline → compactStockTimelineEvents(去重合并) → impact 卡 timeline + 右栏时间线
      morning/workbench/ai/finance/zsxq → feedCards(8 类源) + ResearchFeedPane
      quality_summary → ResearchStatusStrip + ResearchContextPane 质量
      cannot_confirm → ResearchAppendix
```

### 3.4 数据派生逻辑（对齐 V3 函数）

| V3 函数 | V3.5 computed |
|---|---|
| `compactStockTimelineEvents`（行 6606，按 stock_code+source 去重合并） | `timelineByStock` computed |
| `feedItems` 8 类源合成（行 6703） | `feedCards` computed（已实现，需补 key/ocr 源） |
| `chipHtml` / `deskText`（标签映射） | `chipList` / `deskText` helper（已实现） |
| `sourceColumns` 各源截断 | `sourceColumns` computed（已实现，需补 ocr/wechat） |

### 3.5 待补齐的 V3.5 后端

| 端点 | 用途 | 状态 |
|---|---|---|
| `/api/v3/baimao/x/latest` | 白毛 X 栏 | task17 |
| `/api/v3/wechat/articles` | 公众号列 | task14 |
| `/api/v3/research/latest-event` | research-events 基线 | task12 补充 |
| `/api/v3/research/events` | EventSource 事件流 | task12 补充 |

## 4. 执行步骤（研报决策台，task12 完成版）

1. **拆组件**：把 ResearchView.vue 拆成 StatusStrip/ImpactList/FeedPane/FeedCard/SourceColumns/ContextPane/Appendix 组件（对齐 3.1）
2. **补交互**：早盘新闻 tabs（morningFilter）、来源列滚动、feed 8 类源（补 key/ocr）
3. **补后端**：research/latest-event + events 端点（从 lane snapshot 派生）
4. **精简 CSS**：把 v3-research-lane.css 的 593 行精简到只用到的类，按组件 scoped
5. **验证**：typecheck + build + 真实 8/4 数据渲染 + 交互测试（App.spec / ResearchView.spec）

## 5. 验收标准

- 研报决策台三栏布局与 V3 一致（状态条 15 格 + priority/feed/context + cannot_confirm）
- 所有交互点可点击生效（feed tabs、早盘新闻 tabs、公众号滚动、原文链接）
- 数据不占位（8 类源真实渲染）
- typecheck + build + 前端测试通过
- `production_allowed=false` 保持

## 6. 后续（对齐 V3 完整页面，task13-20）

- task13 早盘新闻：`data-morning-filter` 子视图
- task14 公众号：`wechatArticles` + 公众号列
- task15-18 交易信号/运行状态/白毛/复盘归因
- task19 四池 producer
- task20 App.vue 恢复 V3 完整区块布局
