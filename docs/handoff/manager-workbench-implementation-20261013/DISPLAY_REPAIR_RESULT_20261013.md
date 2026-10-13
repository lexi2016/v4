# Manager display repair V12 — 20261013

The existing saved run 84eafbbb71ba4767a591d1a4286fe061 now shows security names, saved numeric oversold reasons, and a separate US-mapping summary. HK.09927 is shown as 赛力斯, using the exact security-master evidence pinned by this run. The original saved snapshot and its product SHA remain unchanged.

- Source root: /Users/lexi/Desktop/学习/v4_app; worktree: /Users/lexi/.codex/worktrees/manager-workbench-rewrite-mac/v4_app.
- Baseline commit: 17821f6986b9c54a8542a3fbb80fbec2ce90876d; branch: codex/manager-workbench-data-closure-20261013.
- Source scope and before/after SHA: display-repair-implementation-r1.json (5 source files, 2 targeted tests).
- Independent implementation receipt: 477fd54f8eff269301c51bec61cccba72b3a9793ab20a0cf79dcbcf952a740c3. Python 3 targeted tests, 2 frontend tests, typecheck; actual saved-result TestClient checks passed. Writer broader tests/build are reported separately.
- Independent V12 packaging receipt: 84daa9d1d44f375aa255aa6872008a5542ebc746162b5feddb298128216b6d9b. Two package tests and actual dry run passed. Exact plan: 41d15931830c7ba039849f62637cb4dc0050da3cd9f2848efb5a188e787e72d7.
- Formal receipt: 545d7d2bdfaacc79d738db5b9fa76dace50f6d58ad261ab5a3ef59fa549c402e. API38112/scheduler38116 match V12; all8 after images match; original config retained. Manager HTML/JS/runtime/CSS match the candidate. Runtime uses Python3.14.6; pytest9.1.1.
- UI: actual browser reload, stock list/detail, expanded US reasons and screenshots; console errors0. Receipt display-repair-formal-ui-r1.json SHA1f69f745fdb618df97c0a3062b6045e0674a1638587f1643f8210de308bf7e70.
- Same original product f8e3fff21847118b010895fe288aa97e17e587ef937ed90c0ebac9c2df4dacbb. GET name enrichment is explicitly a display projection, not a resealed original result.

## Results of this existing 20 percent drawdown version

Oversold scope692: both conditions115, price only181, volume only145, neither221, unknown30. Assessed662;115 selected=17.37%. Conditions remain close<=80% of prior60-session maximum high and volume>=1.5 times prior5-session mean; windows exclude the tested day. It does not require a positive daily return or reversal confirmation.

US mapping:33 source symbols,37 saved records,14 relations,10 HK stocks; by US source symbol:0 selected,0 watch,4 rejected,29 unassessed. Rejected relations are AVGO→HK06088, COHR/LITE→HK06166, CIEN→HK00763, because the source return was not positive. Other paths preserve their exact review/source gaps. Total115 selected must not be described as US selections.

## Acceptance and boundary

IMPLEMENTED, TESTED, REVIEWED, INTEGRATED, DEPLOYED, API_VERIFIED, UI_VERIFIED, BEHAVIOR_VERIFIED. No new research run, collection or model call in this display-only batch; Stage/Close parallel bytes retained. Natural schedule acceptance remains unverified and is not required to prove this display fix. Raw snapshots, stock master, market data and dist are not uploaded. Deployment tests requiring Mac-local immutable fixtures are not claimed as portable CI.

The user subsequently requested a 40 percent drawdown threshold. That is a separately authorized follow-on change, not implemented or claimed in this V12 receipt. Old20% records remain immutable.
