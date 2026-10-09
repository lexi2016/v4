const { defineComponent : _defineComponent } = vue;
const { mergeProps : _mergeProps } = vue;
const { ssrRenderAttrs : _ssrRenderAttrs, ssrInterpolate : _ssrInterpolate, ssrRenderList : _ssrRenderList } = ssr;

                                                                              

const __sfc__ = /*@__PURE__*/_defineComponent({
  __name: 'StageExecutionEvidencePanel',
  __ssrInlineRender: true,
  props: {
    evidence: { type: null, required: true }
  },
  setup(__props     ) {


function count(value                           ) { return typeof value === "number" && Number.isFinite(value) ? String(value) : "未记录／未绑定"; }
function detail(value         ) { return JSON.stringify(value, null, 2); }

return (_ctx     ,_push     ,_parent     ,_attrs     ) => {
  _push(`<section${
    _ssrRenderAttrs(_mergeProps({
      class: "execution-evidence",
      "aria-label": "阶段执行声明与选股身份"
    }, _attrs))
  } data-v-stage-evidence-fixture><h3 data-v-stage-evidence-fixture>执行尝试与已验证产物分列</h3><p data-v-stage-evidence-fixture>${
    _ssrInterpolate(_ctx.evidence.trade_date)
  } · ${
    _ssrInterpolate(_ctx.evidence.stage_id)
  } · ${
    _ssrInterpolate(_ctx.evidence.status)
  }</p><p data-v-stage-evidence-fixture>尝试模式（回执声明）：${
    _ssrInterpolate(_ctx.evidence.attempt_mode || "未记录")
  } / ${
    _ssrInterpolate(_ctx.evidence.due_status || "未记录")
  }；记录时间：${
    _ssrInterpolate(_ctx.evidence.recorded_at || "原回执未记录，不推断历史开始时间")
  }</p><p data-v-stage-evidence-fixture>执行状态（声明）：${
    _ssrInterpolate(_ctx.evidence.declared_status || "未记录")
  }；节点尝试：${
    _ssrInterpolate(count(_ctx.evidence.node_attempt_count))
  } · ${
    _ssrInterpolate(_ctx.evidence.node_outcome || "未记录")
  }</p>`)
  if (_ctx.evidence.first_failed_layer || _ctx.evidence.error) {
    _push(`<p data-v-stage-evidence-fixture>首次失败层：${
      _ssrInterpolate(_ctx.evidence.first_failed_layer || "未定位")
    }；${
      _ssrInterpolate(_ctx.evidence.error)
    }</p>`)
  } else {
    _push(`<!---->`)
  }
  _push(`<p data-v-stage-evidence-fixture>此处不独立认证自然／补跑血缘。选股身份匹配只验证对应产物引用；原回执自计算SHA不是运行认证。</p><div class="execution-markets" data-v-stage-evidence-fixture><!--[-->`)
  _ssrRenderList(_ctx.evidence.markets, (lane, market) => {
    _push(`<article data-v-stage-evidence-fixture><h4 data-v-stage-evidence-fixture>${
      _ssrInterpolate(market)
    } · ${
      _ssrInterpolate(lane.status || "未记录")
    }</h4><p data-v-stage-evidence-fixture>选股引用：${
      _ssrInterpolate(lane.selection_binding)
    }</p><p data-v-stage-evidence-fixture>回执计数：请求 ${
      _ssrInterpolate(count(lane.requested_rows))
    } / 来源 ${
      _ssrInterpolate(count(lane.source_rows ?? lane.observed_rows))
    } / 接受 ${
      _ssrInterpolate(count(lane.accepted_rows))
    } / 选择 ${
      _ssrInterpolate(count(lane.selected_rows))
    }</p><p data-v-stage-evidence-fixture>失败层：${
      _ssrInterpolate(lane.failure_layer || "未记录或未定位")
    }</p>`)
    if (lane.diagnostics) {
      _push(`<p data-v-stage-evidence-fixture>页调用 ${
        _ssrInterpolate(lane.diagnostics.pages_read ?? "未知")
      }；精确成交 ${
        _ssrInterpolate(lane.diagnostics.exact_time_count ?? "未知")
      }；接受成交 ${
        _ssrInterpolate(lane.diagnostics.accepted_tick_count ?? "未知")
      }；READ_ERROR ${
        _ssrInterpolate(lane.diagnostics.read_error_count ?? "未知")
      }。页调用不等于请求宇宙或有效响应页。</p>`)
    } else {
      _push(`<!---->`)
    }
    _push(`<details data-v-stage-evidence-fixture><summary data-v-stage-evidence-fixture>原失败原因、计数与身份（不改写历史）</summary><pre data-v-stage-evidence-fixture>${_ssrInterpolate(detail({ reasons: lane.reasons, diagnostics: lane.diagnostics, declared_identity: lane.declared_identity }))}</pre></details></article>`)
  })
  _push(`<!--]--></div><details data-v-stage-evidence-fixture><summary data-v-stage-evidence-fixture>绑定缺口与所读回执</summary><!--[-->`)
  _ssrRenderList(_ctx.evidence.cannot_confirm, (reason) => {
    _push(`<p data-v-stage-evidence-fixture>${_ssrInterpolate(reason)}</p>`)
  })
  _push(`<!--]--><p data-v-stage-evidence-fixture>候选宇宙：${
    _ssrInterpolate(_ctx.evidence.candidate_run_id || "未记录")
  } · ${
    _ssrInterpolate(_ctx.evidence.candidate_binding || "未核验")
  }</p><code data-v-stage-evidence-fixture>${
    _ssrInterpolate(_ctx.evidence.candidate_current_sha256)
  }</code><p data-v-stage-evidence-fixture>读取路径：${
    _ssrInterpolate(_ctx.evidence.receipt_path || "未绑定")
  }</p><code data-v-stage-evidence-fixture>观察到的原字节SHA：${
    _ssrInterpolate(_ctx.evidence.observed_sha256 || "未读取")
  }</code><p data-v-stage-evidence-fixture>历史坏行：${
    _ssrInterpolate(_ctx.evidence.historical_bad_row_status)
  }；未由未来诊断反填。</p></details></section>`)
}
}

})