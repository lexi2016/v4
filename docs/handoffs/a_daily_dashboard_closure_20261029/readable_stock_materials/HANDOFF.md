# C9 · 读图、双成功率与已收到资料

唯一目标：原固定V4页面按已确认第1稿先图后结论与资料；当前原式统计保持，新增只读全事件定位/用户批准的同分位描述性分层与开发图谱。Writer仅本目录和本批清单。实际现役/API/自然时段由Root分别回读，不以本交接替代。

已成：API小分片GET（不每GET读26/98MB包），247资料机械投影；002003总体56与同桶33完整案例，亏损/未成熟保留；D2总体25/55、D5总体17/54，同桶14/32、9/31。近250有效正收盘、五固定桶，历史每次仅该前缀。独立注册真实单股投影只运行一次，原统计/公式/池/历史缓存未改。股东19719/-3550与统计/披露日、财务原单位/原值及来源、31条目录可读，正文未取得如实显示。全文库默认不查询，只人工分页5篇，未改索引/排序/OCR。

Root IAB 已接受实际002003全阅读流程、56/33事件定位与恢复、原Canvas/51/22/缩放、单工具栏与完整成交量、1440及679无横溢。首次SSE同identity引用被替换的空图失败已修，失败原件保留。新增开发图谱40文件/733符号、10节点/12关系；source SHA/符号/接口/依赖可搜索，9/9 showcase通过。静态Main C8快照/API C9候选分列，不认定发布后现役；图谱自身不写release-manifest hash避免循环。

针对性证据：分层7 synthetic及单股56案例与20既存案例parity沿用；新增reader/SSE/absence控制5测试PASS，图谱2测试PASS，2JS语法PASS。初次pytest所有5断言通过但退出时触发另一批旧受保护临时目录清理错误；本批独立basetemp7测试exit0，不触碰旧目录。未重复旧图/全库/已通过UI。

`design-qa.md` 是源图+实际页面同图并排核对。合成图与Root IAB原件留研究产物目录；不把模拟图作为用户Canvas，也不为图形示意改变真实信号。P0/1/2未决0，最终仍需一次独立Reviewer验实际diff/数据/视觉。

## 恢复与发布

`prepare_c9.py --refresh-candidate` 只更新既有未激活API候选，不重建资料/不改现役；精确安装差异见 `EXACT_INSTALLED_DELTA.diff`。它把本批hunk三方合入当前C8 runtime，保留C6/C7与他方性能修复；task整文件不可冒充部署字节。`WRITER_RECEIPT.json` 与研究目录的 `CANDIDATES.json` 绑定最终SHA。

Root独审后写审查JSON：status=`REVIEWED_PASS_C9`、`publication_plan_sha256`、`api_manifest_sha256`。使用绝对PANEL_PYTHON，依次：

```text
PANEL_PYTHON control_c9.py --review /absolute/review.json --publish
PANEL_PYTHON control_c9.py --review /absolute/review.json --api
```

脚本严格校验原index/event与API plist CAS，再复用原owner原子save；API先正常bootout、等待launchctl真实absent，才同一已审plist bootstrap。不改Main，不强杀、不盲重试。回滚同命令加 `--rollback`：先API回退，再metadata回退（只在各自CAS一致时），保留每次前像和receipt。Root安装后核实际PID/release/GET/页面；自然15:40仍未验证。

`actual_check.py --serve` 仅复用原demo入口，候选app/static加已暂存index/event；无浏览器自动化/计算。Root IAB使用完通知关闭本批临时port；不能当长期服务/第二producer。`project_event_details.py` 是本次已注册单股的可复现投影，禁止因换入口重跑标签/公式或全247历史。

## 文件生命周期与公开备份

保留：6业务文件（router/reader/domain additive+3面板静态）、1图谱生成器、3针对性tests、9图谱静态文件、design-qa、此专属最小handoff。4脚本职责分别为准备/控制回滚/只读demo/一次受控投影。

已移出源码目录：失败旧headless CJS与旧demo脚本副本，保留研究目录failure_repro作为失败证据，不进入GitHub。清理候选临时服务须待Root用完；自己的pytest临时目录/编译缓存和中间合成副本可再生，可在验收后删除。保留原输入、成功/失败工件、checkpoint、正式候选/回滚前像，绝不清他人目录。

公开repo只含必要源码/tests/精简交接与静态图谱；不含材料分片、统计缓存、行情、PDF/OCR、plist、凭据、整套247HTML或用户研究包。Root部署通过后沿已有GitHub分支上传。订单四旗保持研究态；后续同口径批量只机器完整性/异常/checkpoint与一次交付核验，不逐股LLM复审。

同次独审4个P2：开发图谱常量URL解析同源后仍走原HTTP(S)guard；资料异步之前同步恢复同一正文库节点且保持成功目录顺序；publisher绑定原C8 Main owner SHA a281777b2b5120980151220d832d360498c8c53fcdd43d464bc7a52eae765abe；只在rollback且真实print113/couldnotfind时允许服务已absent恢复。新增4项定向测试PASS，普通停止失败/ownerSHA漂移均closed，无真实服务测试。初始失败及before原件保留，先前缓存推断已证伪。

生成Archify viewer随附原MIT许可 `research-panel/code-map/ARCHIFY_LICENSE.txt`，原字节SHA b799ab081703e7821ae5096d2c1abdf14bbdc75e8ea1c4045998c36ed6db9706。图谱总图spec/HTML复用已通过9/9，无新增渲染或测试。
