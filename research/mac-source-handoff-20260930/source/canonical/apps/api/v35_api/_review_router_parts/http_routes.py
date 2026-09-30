"""apps.api.v35_api.review_router: http_routes (review candidate, not deployment)."""
from ._namespace import read_global as _v4_global


def _create_review_router_body(_v4_scope, /, data_root, review_root, *, generation_bindings_path, generation_bindings_sha256, intraday_root, historical_prefix_root, historical_prefix_binding_path, _generation_transport, _generation_client_factory):
    # Route handlers are registered by FastAPI while this function is running.
    # Bind annotation names from the live facade so annotations resolve to the
    # same request/model types used by the public module after extraction.
    ManualReviewRequest = _v4_global(_v4_scope, 'ManualReviewRequest')
    Request = _v4_global(_v4_scope, 'Request')
    Any = _v4_global(_v4_scope, 'Any')
    router = _v4_global(_v4_scope, 'APIRouter')(prefix="/api/v3", tags=["review"])

    @router.post("/review/generate")
    async def generate(body: ManualReviewRequest, request: Request) -> dict[str, Any]:
        origin = request.headers.get("origin")
        if origin:
            parsed = _v4_global(_v4_scope, 'urlsplit')(origin)
            if parsed.scheme not in {"http", "https"} or parsed.netloc != request.url.netloc or parsed.scheme != request.url.scheme:
                raise _v4_global(_v4_scope, '_manual_error')(403, "ORIGIN_REFUSED", "仅允许同源研究面板触发生成。")
        return await _v4_global(_v4_scope, 'run_in_threadpool')(_v4_global(_v4_scope, '_manual_generate'), body.date,
            bindings_path=generation_bindings_path, bindings_sha256=generation_bindings_sha256,
            review_root=review_root, transport=_generation_transport,
            client_factory=_generation_client_factory)

    @router.get("/review")
    def review(date: str = _v4_global(_v4_scope, 'Query')(..., pattern=r"^\d{8}$")) -> dict[str, Any]:
        try:
            _v4_global(_v4_scope, 'datetime').strptime(date, "%Y%m%d")
        except _v4_global(_v4_scope, 'ValueError') as error:
            raise _v4_global(_v4_scope, 'HTTPException')(status_code=422, detail="date must be a real calendar date") from error

        native_hk, native_present = _v4_global(_v4_scope, '_native_hk_review')(data_root, date)
        if native_present:
            # A local exact-date ReviewStore artifact is authoritative.  An
            # invalid present artifact fails closed; it must not be replaced
            # by a less authoritative bridge result.
            hk_payload = native_hk
        elif _v4_global(_v4_scope, '_HAS_HK_REVIEW_CORE'):
            hk_source = _v4_global(_v4_scope, 'load_hk_close_review')(date, data_root)
            hk_payload = _v4_global(_v4_scope, '_hk_parent')(date, hk_source)
        else:
            # Compatibility for the pre-T183 checkout: preserve the existing
            # ReviewStore response shape while the candidate supplies the
            # Review Core bridge implementation.
            hk_payload = _v4_global(_v4_scope, 'close_review')(_v4_global(_v4_scope, 'ReviewStore')(data_root), date)["market_reviews"]["HK"]

        strict_review_core = _v4_global(_v4_scope, '_HAS_REVIEW_EVIDENCE_LAYERS') and _v4_global(_v4_scope, 'review_core_a_share_bundle_required')(
            data_root, date
        )
        bundle_error = ""
        partial_stage_rows: list[dict[str, Any]] = []
        partial_stage_refs: list[dict[str, Any]] = []
        if strict_review_core:
            try:
                a_payload = _v4_global(_v4_scope, 'load_review_core_a_share_review')(date, data_root)
            except _v4_global(_v4_scope, 'Exception') as error:
                a_payload = None
                bundle_error = f"REVIEW_CORE_BUNDLE_INVALID: {_v4_global(_v4_scope, 'type')(error).__name__}: {error}"
        else:
            a_share_reviews = _v4_global(_v4_scope, 'AShareReviewStore')(data_root)
            try:
                a_payload = a_share_reviews.read_review(date)
            except _v4_global(_v4_scope, 'ValueError'):
                a_payload = None
            if a_payload is not None and a_payload.get("source_role") != "V3_5_NATIVE_CLOSE_MODEL":
                a_payload = None
            if a_payload is None:
                partial_stage_rows, partial_stage_refs = _v4_global(_v4_scope, '_read_exact_stage_review_rows')(data_root, date)
                if partial_stage_rows:
                    a_payload = _v4_global(_v4_scope, '_partial_stage_review')(
                        date,
                        partial_stage_rows,
                        partial_stage_refs,
                    )
        envelope = _v4_global(_v4_scope, 'review_envelope')(date, a_review=a_payload, hk_review=hk_payload or {})
        a_document = envelope["market_reviews"]["A"]
        if bundle_error:
            a_document["cannot_confirm"] = [bundle_error]
            envelope["review_core_bundle"] = {
                "status": "CANNOT_CONFIRM",
                "source_role": "REVIEW_CORE_BUNDLE_V1",
                "trade_date": date,
                "cannot_confirm": [bundle_error],
            }
        elif strict_review_core:
            envelope["review_core_bundle"] = {
                "status": "READY",
                "source_role": "REVIEW_CORE_BUNDLE_V1",
                "trade_date": date,
                "source_sha256": _v4_global(_v4_scope, 'str')(a_payload.get("source_sha256") or "")
                if _v4_global(_v4_scope, 'isinstance')(a_payload, _v4_global(_v4_scope, 'Mapping'))
                else "",
            }
            a_document["review_surface"] = {
                "tier": "V3_RICH_READY",
                "status": _v4_global(_v4_scope, 'str')(a_document.get("status") or "READY"),
                "trade_date": date,
                "source_role": "REVIEW_CORE_BUNDLE_V1",
                "source_refs": _v4_global(_v4_scope, 'deepcopy')(a_document.get("source_evidence") or []),
            }
        if _v4_global(_v4_scope, '_HAS_REVIEW_EVIDENCE_LAYERS'):
            envelope["review_evidence_layers"] = _v4_global(_v4_scope, 'load_review_evidence_layers')(
                data_root,
                date,
                envelope["market_reviews"]["A"],
            )
        # The daily research review is an optional exact-date read-only
        # projection.  Its source root is explicit (argument or
        # V4_DAILY_REVIEW_ROOT); missing configuration remains visible as
        # CANNOT_CONFIRM and never falls back to latest.json.
        from domains.intraday_research import read_intraday_day
        try:
            envelope["intraday_research"] = read_intraday_day(
                date, intraday_root=_v4_global(_v4_scope, 'Path')(intraday_root) if intraday_root else None,
                review_root=_v4_global(_v4_scope, 'Path')(review_root) if review_root else None)
        except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'KeyError'), _v4_global(_v4_scope, 'TypeError')):
            envelope["intraday_research"] = {"status": "CANNOT_CONFIRM", "slots": [],
                "cannot_confirm": ["INTRADAY_BOUNDARY_REFUSED"], **_v4_global(_v4_scope, '_SAFETY_FLAGS')}
        envelope["research_review"] = _v4_global(_v4_scope, 'load_daily_research_review')(
            date,
            review_root=review_root,
        )
        # The historical prefix surface is an explicit, fixed research asset.
        # A missing runtime binding remains visible as CANNOT_CONFIRM and
        # never falls back to the daily panel/current/latest pointer.
        envelope["hk_prefix_research"] = _v4_global(_v4_scope, '_read_hk_prefix_research_asset')(
            date,
            root_value=historical_prefix_root or _v4_global(_v4_scope, 'os').environ.get("V4_HK_PREFIX_RESEARCH_ROOT"),
            binding_value=(
                historical_prefix_binding_path
                or _v4_global(_v4_scope, 'os').environ.get("V4_HK_PREFIX_RESEARCH_BINDING_PATH")
            ),
        )
        hk_document = (
            hk_payload.get("model_selection_review")
            if _v4_global(_v4_scope, 'isinstance')(hk_payload, _v4_global(_v4_scope, 'Mapping'))
            else None
        )
        envelope["reference_snapshot"] = _v4_global(_v4_scope, 'bool')(
            (hk_document or {}).get(
                "reference_snapshot",
                hk_payload.get("reference_snapshot", False)
                if _v4_global(_v4_scope, 'isinstance')(hk_payload, _v4_global(_v4_scope, 'Mapping'))
                else False,
            )
        )
        return envelope

    return router
