#!/usr/bin/env bash
set -euo pipefail
SRC_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PATCH_STAGE="${1:?Pass a root containing staged apps/web/src/manager-selection/dailyChannels.ts}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/apps/web/src/manager-selection" "$TMP/apps/web/src/api"
cp "$SRC_ROOT/apps/web/src/manager-selection/announcementAnalysis.ts" "$TMP/apps/web/src/manager-selection/announcementAnalysis.ts"
cp "$PATCH_STAGE/apps/web/src/manager-selection/dailyChannels.ts" "$TMP/apps/web/src/manager-selection/dailyChannels.ts"
cp "$SRC_ROOT/tests/fixtures/managerAnnouncementAnalysis_compile_shim.ts" "$TMP/apps/web/src/api/managerAnnouncementAnalysis.ts"
tsc --strict --target ES2022 --lib ES2022,DOM --module CommonJS --moduleResolution Node \
  --outDir "$TMP/build" "$TMP/apps/web/src/manager-selection/announcementAnalysis.ts" \
  "$TMP/apps/web/src/manager-selection/dailyChannels.ts"
ANNOUNCEMENT_OWNER_DETAIL_JS="$TMP/build/manager-selection/announcementAnalysis.js" \
ANNOUNCEMENT_SHARED_DAILY_JS="$TMP/build/manager-selection/dailyChannels.js" \
  node --test "$SRC_ROOT/tests/test_announcement_frontend_r1.cjs"
