# 61796 preview calendar repair — 2026-10-12

Scope: restore calendar navigation at the existing 61796 preview endpoint.
Baseline delivery commit: 93b632c2f5e59520f5c1337c3cfe581fc598b4a3.
Runtime source: /Users/lexi/Documents/Codex/2026-10-10/task/m18-6daed627-source/V5.
Only changed runtime file: /Users/lexi/Documents/Codex/2026-10-10/task/m18-publication/gateway.json.
Before SHA256: 8015cf68daeb609742fa763d9c948910aff03d34f5241d56ba107b4e6892f925.
After SHA256: c5064ef62208c375668c6ad005fba04622f5ee59b63fad637116eb963ee4f61c.

Failure: GET /api/v1/runs/date-list on 61796 returned HTTP 502 MODULE_UNAVAILABLE via hk_review.
Fix: add v4_date_directory on 8873 and bind only the date-list GET route. All other module/route definitions remain unchanged. No additional write routes.
Deployment: reload only the existing 61796 process, PID 13732 -> 71956, preserving startup arguments and frontend manifest. Original config and process identity backed up locally.

Independent reviewer preview_calendar_review:
REVIEWED PASS; TESTED PASS; date-list API BEHAVIOR_VERIFIED.
V5 virtual environment: validate_config passes; tests/test_api_gateway.py: 14 passed.
Live no-query request used by the frontend and date=20261008 / date=20261012 requests all return 200 and match corresponding 8873 response bytes; selected dates retained.
No P0/P1/P2 findings in this frozen scope.

Controller UI verification:
On http://127.0.0.1:61796, changed date input from 20261012 to 20261008 and back to 20261012; URL and displayed selected date updated correctly.
UI_VERIFIED for date selection. Screenshot retained locally as UI_61796_DATE_20261012.png.
Other preview stage-data read failures remain outside this calendar-only scope. Dependency on the existing 8873 date-list service is explicit.
Natural stage execution is not claimed by this receipt.
research_only=true; production_allowed=false; buy_gate_updated=false; orders_sent=false.
