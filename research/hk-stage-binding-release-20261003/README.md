# 港股阶段绑定：已验适配的发布阻断

唯一目标：让已有 Stage-only builder 能构造包含本次已验 runner 的候选，接着由本机 Luna 完成发布和原入口验收。不要重写选股、数据采集、页面或日历。

## 已完成，直接复用

- 原会话已完成资格/日线/Top100恢复；旧ECONNREFUSED不是当前待修。
- 原stage_binding_candidate独立20项PASS。
- 本轮canonical仅改 `_build_hk_stage_binding`，函数与已审候选逐字节一致；新增测试与旧候选同SHA。
- 本轮独立12项PASS，服务解释器Python3.14.6。
- 用原配置双root、原绑定入口读取20261002，取得100唯一股票，绑定20260930来源池、signal_date=20260929。来源三SHA与Writer一致；只读，未采集/未写selection。
- 回执见 `evidence/independent_integration_review_20261003.json`。只证明当前绑定，不能追认历史cutoff或自然运行。

## 当前唯一发布阻断

`ops/build_release_candidate.py --stage-service-candidate --stage-overlay-path stage_center/runner.py` 进入 `build_stage_service_candidate`，创建目录前调用 `require_stage_overlay_source_hashes`。

`ops/stage_service_overlay_contract.py` 的 `STAGE_SERVICE_RELEASE_CLOSURE_SHA256['stage_center/runner.py']` 固定为：

`648fe7af52df1b4eba31802361f9af2d03decbbebb3286ecc7a5dc0b06523205`

本轮已独立验收canonical runner实际SHA：

`7e6e958df4d64a8f7324d96bb09548f29c9da3ba206a4548420fa021da47d34f`

原独立通过候选为f4c9043c948212b9d586b86a5b0c5c4924d7ffcd0bbc3d99c237988d508c9e20。两者都被旧pin拒绝。这是发布身份未随已验源码更新，不是新增绑定逻辑失败。

## 给Chat的最小任务

优先仅更新 `ops/stage_service_overlay_contract.py` 中这一个 runner pin，绑定包内已验字节，保留其余pin与SHA校验逻辑。不要改成动态信任当前源码，不加绕过开关，不借此更新整个闭包。

复用 `tests/test_stage_service_overlay_closure.py` 验证新pin匹配、错误字节仍拒绝。仅当固定fixture确需适配才提交最小测试差异并说明；不扩到全仓。返回一份最小patch及精确前/后SHA。

候选重建、候选相对活动R1的实际差异、原入口导入/绑定和服务切换由Mac Luna接续；Chat没运行的环境明确NOT_RUN。打包完成仍须核其只包含预期overlay，不把canonical整树覆盖到活动R1。任何另一个闭包不匹配明确返回，不无差别刷新pins。

## 来源与状态

源码切片在 `canonical/`，变更与独立回执在 `evidence/`，文件身份在SOURCE_MANIFEST.json。本包不是完整应用，不应整树部署。

活动stage仍是20261002-hk-open-stage-r1，runner 50da5908c98330df9ad3dee6d44ad1042f559883815507be28a4257bf0f03f67；plist SHA9cfeef77dc9293ad93fc1a56abe182e65b99f446181282e452f94c325303cf57。新候选尚未创建，DEPLOYED=NO。

Issue21页面/导航候选继续后排；不碰API/经理/公告/US/A股规则/Vibe8910。RESEARCH_ONLY=true，production_allowed=false，buy_gate_updated=false，orders_sent=false。无历史输入不补造selection，NATURAL_SLOT_UNVERIFIED保留。
