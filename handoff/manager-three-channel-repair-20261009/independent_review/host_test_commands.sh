"$V4_REVIEW_PYTHON" "$V4_HANDOFF/tools/run_scoped_tests.py" \
  --app-root "$V4_REVIEW_ROOT" \
  --junitxml "$V4_REVIEW_ROOT/three-channel-core-results.xml"

export V4_TEST_SOURCE_ROOT="$V4_REVIEW_ROOT"
export V4_TEST_PYTHON="$V4_REVIEW_PYTHON"

# 仅当新临时副本尚无 node_modules 时，引用已有测试依赖。
if [ ! -e "$V4_REVIEW_ROOT/apps/web/node_modules" ] && \
   [ ! -L "$V4_REVIEW_ROOT/apps/web/node_modules" ]; then
  ln -s "$V4_REVIEW_NODE_MODULES" "$V4_REVIEW_ROOT/apps/web/node_modules"
fi

(
cd "$V4_REVIEW_ROOT/apps/web"
"$V4_REVIEW_NODE" "$V4_REVIEW_NODE_MODULES/vitest/vitest.mjs" run \
  --config "$V4_HANDOFF/tools/vitest.config.mjs" \
  src/api/managerWorkspace.threeChannel.spec.ts \
  src/api/managerWorkspace.dailyAutomation.spec.ts
)
