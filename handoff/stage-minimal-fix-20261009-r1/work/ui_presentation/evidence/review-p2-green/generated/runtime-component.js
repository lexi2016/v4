const { defineComponent : _defineComponent } = vue;
const { mergeProps : _mergeProps } = vue;
const { ssrRenderAttr : _ssrRenderAttr, ssrRenderAttrs : _ssrRenderAttrs, ssrInterpolate : _ssrInterpolate, ssrRenderList : _ssrRenderList } = ssr;

const { computed } = vue;
                                                                              

const __sfc__ = /*@__PURE__*/_defineComponent({
  __name: 'StageExecutionEvidencePanel',
  __ssrInlineRender: true,
  props: {
    evidence: { type: null, required: true }
  },
  setup(__props     ) {

const props = __props;

function counter(value         )                {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value : null;
}
function quoteText(requested               , source               , declaredMissing          ) {
  if (requested === null || source === null) {
    return `行情 ${source ?? "未知"} / ${requested ?? "未知"} 只；缺口数量未知`;
  }
  const missing = requested - source;
  if (missing < 0 || (declaredMissing != null && counter(declaredMissing) !== missing)) {
    return `行情计数待核对（来源 ${source}；请求 ${requested}）`;
  }
  return `行情 ${source} / ${requested} 只，缺 ${missing} 只`;
}
function resultBinding(market        ) {
  const binding = props.evidence.selection_artifact_bindings?.[market]?.status;
  const legacy = props.evidence.markets?.[market]?.selection_binding;
  if (binding === "SELECTION_TRIO_CONFLICT" || legacy === "SELECTION_IDENTITY_CONFLICT" || legacy === "SELECTION_COUNT_CONFLICT") {
    return "结果与运行记录的身份冲突，待核对";
  }
  if (binding === "BOUND_TO_VERIFIED_SELECTION_TRIO") return "结果与原执行记录已绑定";
  if (binding === "SELECTION_TRIO_MATCHES_CURRENT_RECEIPT_HISTORY_UNBOUND") return "结果引用相符，历史记录未绑定";
  return "执行记录尚未完整绑定";
}
const marketViews = computed(() => {
  const markets = props.evidence.stage_id === "STAGE_1545_1555" ? ["HK_CONNECT"] : ["A_SHARE", "HK_CONNECT"];
  return markets.map(market => {
    const lane = props.evidence.markets?.[market];
    const hasSummary = Object.prototype.hasOwnProperty.call(props.evidence, "selection_results");
    const result = props.evidence.selection_results?.[market];
    const selected = counter(hasSummary ? result?.selected_rows : lane?.selected_rows);
    const available = hasSummary
      ? (result?.status === "RESULT_AVAILABLE" && selected !== null && selected > 0)
        || (result?.status === "VERIFIED_EMPTY_RESULT" && selected === 0)
      : lane?.selection_binding === "BOUND_TO_VERIFIED_SELECTION" && selected !== null;
    const preselectionBlocked = market === "HK_CONNECT" && (
      lane?.failure_layer === "PRESELECTION_INPUT"
      || lane?.reasons?.some(reason => reason.includes("HK D1 status must be STRICT_0_2_READY"))
    );
    const requested = counter(hasSummary ? (available ? result?.requested_rows : null) : lane?.requested_rows);
    const source = counter(hasSummary ? (available ? result?.source_rows : null) : (lane?.source_rows ?? lane?.observed_rows));
    return {
      market, name: market === "A_SHARE" ? "A股" : "港股通",
      headline: available ? (selected === 0 ? "已保存空结果（0 只）" : `已计算 ${selected} 只`)
        : preselectionBlocked ? "预选池未就绪，未进入算法" : "选股结果待核对",
      quote: quoteText(requested, source, hasSummary && available ? result?.missing_quote_rows : undefined),
      countSource: hasSummary ? (available ? "选股产物计数" : "行情计数未绑定") : "回执记录计数",
      binding: resultBinding(market),
      blockedAttemptWithSavedResult: available && preselectionBlocked,
    };
  });
});
const modeText = computed(() => {
  const mode = props.evidence.attempt_mode;
  if (!mode) return "未记录";
  if (mode === "NATURAL") return "自然触发（NATURAL）";
  if (mode === "RECOVERY") return "补跑（RECOVERY）";
  return `其他方式（${mode}）`;
});
const historyText = computed(() => {
  const binding = props.evidence.receipt_history_binding;
  if (binding === "OWNER_HISTORY_SHA_BOUND") return "已核对";
  if (binding === "OWNER_HISTORY_CONFLICT") return "身份冲突，待核对";
  return !binding || binding === "OWNER_HISTORY_NOT_RECORDED" ? "未记录" : "待核对";
});
const recordTimeText = computed(() => {
  if (!props.evidence.recorded_at) return "原回执未记录";
  return props.evidence.receipt_history_binding === "OWNER_HISTORY_SHA_BOUND"
    && props.evidence.record_time_status === "OWNER_WRITE_CLOCK_RECORDED"
    ? props.evidence.recorded_at : "待核对";
});
function detail(value         ) { return JSON.stringify(value, null, 2); }

return (_ctx     ,_push     ,_parent     ,_attrs     ) => {
  _push(`<section${
    _ssrRenderAttrs(_mergeProps({
      class: "execution-evidence",
      "aria-label": "阶段选股结果与运行记录"
    }, _attrs))
  } data-v-stage-evidence-fixture><h3 data-v-stage-evidence-fixture>本阶段选股结果</h3><p data-v-stage-evidence-fixture>${
    _ssrInterpolate(_ctx.evidence.trade_date)
  } · ${
    _ssrInterpolate(_ctx.evidence.stage_id)
  }</p><div class="execution-markets" data-v-stage-evidence-fixture><!--[-->`)
  _ssrRenderList(marketViews.value, (lane) => {
    _push(`<article${
      _ssrRenderAttr("data-market", lane.market)
    } data-v-stage-evidence-fixture><h4 data-v-stage-evidence-fixture>${
      _ssrInterpolate(lane.name)
    }</h4><p class="execution-result" data-v-stage-evidence-fixture><strong data-v-stage-evidence-fixture>${
      _ssrInterpolate(lane.headline)
    }</strong></p><p data-v-stage-evidence-fixture>${
      _ssrInterpolate(lane.quote)
    }<small class="execution-count-source" data-v-stage-evidence-fixture>${
      _ssrInterpolate(lane.countSource)
    }</small></p>`)
    if (lane.blockedAttemptWithSavedResult) {
      _push(`<p data-v-stage-evidence-fixture>当前回执：预选池未就绪，未进入算法。</p>`)
    } else {
      _push(`<!---->`)
    }
    _push(`<p data-v-stage-evidence-fixture>${_ssrInterpolate(lane.binding)}</p></article>`)
  })
  _push(`<!--]--></div><h4 data-v-stage-evidence-fixture>运行记录与验收</h4><dl class="execution-facts" data-v-stage-evidence-fixture><div data-v-stage-evidence-fixture><dt data-v-stage-evidence-fixture>运行方式（回执声明）</dt><dd data-v-stage-evidence-fixture>${
    _ssrInterpolate(modeText.value)
  }</dd></div><div data-v-stage-evidence-fixture><dt data-v-stage-evidence-fixture>原执行方历史记录</dt><dd data-v-stage-evidence-fixture>${
    _ssrInterpolate(historyText.value)
  }</dd></div><div data-v-stage-evidence-fixture><dt data-v-stage-evidence-fixture>记录时间</dt><dd data-v-stage-evidence-fixture>${
    _ssrInterpolate(recordTimeText.value)
  }</dd></div><div data-v-stage-evidence-fixture><dt data-v-stage-evidence-fixture>自然时段验收</dt><dd data-v-stage-evidence-fixture>尚未验证</dd></div></dl><p data-v-stage-evidence-fixture>执行过程与自然时段仍需独立验收。</p><details data-v-stage-evidence-fixture><summary data-v-stage-evidence-fixture>查看运行与来源详情</summary><pre data-v-stage-evidence-fixture>${
    _ssrInterpolate(detail(_ctx.evidence))
  }</pre></details></section>`)
}
}

})