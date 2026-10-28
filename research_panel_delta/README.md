# Existing daily research-panel R19 view

Target is `/research-panel/daily.html`, served by the same V4 API.
The original 450-asset tree is copied as opaque bytes; only daily.html changes, with r19-results.js and namespaced reuse of chart85.js added. Other449 assets retain exact SHA, including stock JSON and archives.
No Vue build or Vue source delta is published. Backend only adds the previously reviewed explicit `R19_FROZEN_151_20261027` profile. Default daily data/profile and pools stay unchanged.

The card initially makes no request. It exposes exact151 registration summary (144 results,7 no target bar), selected-stock same-origin API lookup, source/qualifications, actual stored common chart lines, original51 values and22 drawing records, and the accepted cross-date FBFB observation. Group absence is not native TDX rejection; mtime is not a proven signal date.

Target date is visible2026-10-27, independent from the outer daily archive date. Wrong dates, empty results, changed identities and malformed51/22 responses clear prior output. No default-profile fallback or market data fetching is used.

Targeted test: `test-r19-results.cjs`, using R19_WEB_PACKAGE, R19_STATIC_ROOT, R19_UI_FIXTURES and R19_UI_RESULT environment paths. Three actual151 representatives600715/000630/688808, confirmed empty600621 and D28 rejection. Canvas calls are exercised through the original chart code with a jsdom context; real browser acceptance remains separate.
