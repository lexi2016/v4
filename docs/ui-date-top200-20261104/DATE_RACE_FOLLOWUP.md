# 独审 P2 日期竞态返修

仅增量修复 `50679d0d1833318df968a22fba8b57bc66598632` 的日期请求链。

可复现顺序：A 收盘自动今日 → focus 触发日历读取且响应保持 pending →
选历史 → 点击今日。旧实现因 `restoringDate` 合并所有请求，吞掉明确今日操作；
旧请求又因用户意图变化丢弃，最终历史日期留在 URL，内部却已标为自动模式。

现在显式“今日”允许发起新日历请求。请求版本保证旧响应不覆盖最新请求，
旧请求的 finally 也不会提前释放新请求的 busy 状态。自动 focus/pageshow
仍合并进行中的读取；历史查询保持原行为。

新增 `honors today while an older focus calendar request is pending` 回归：
修复前确证失败 `expected 2 to be 3`；修复后验证第三次日历请求发出、旧响应先回
不移动日期、不释放新请求锁、新响应返回后显示今日并清除 `date`，保留 A view。

验证命令（cwd `apps/web`）：

```
npm test -- src/App.spec.ts -t 'daily date navigation and independent A close view|opens the UI-only A-share pool Top200'
npm run build
```

结果：8 项日期/App 回归 PASS，build PASS；main bundle `main-DiGAxLDa.js`。
面板、数据归因、HK 与布局既有 PASS 复用，未重跑。原全仓 typecheck/旧 App
缺口不变。失败日志 `date-race-before.log`、成功日志 `date-race-after.log` 与
`build-r3.log` 保存在同批 `ui_repair` 目录。

r2 未激活且保持不可变；本次生成新的 r3 候选。独审增量复核与部署由主控处理。
