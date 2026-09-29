"""apps.api.v35_api.review_router: manual_review (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __manual_generate_body(_v4_scope, /, date, *, bindings_path, bindings_sha256, review_root, transport, client_factory):
    """One server-pinned request, existing assembly/graph/writer and task lock.

    A small date-keyed attempt receipt prevents a browser retry after a charged
    failure or interrupted request. No background job or scheduler is created.
    Operator reconciliation is required for failed/unknown attempts; the HTTP
    surface never exposes replace, paths, credentials or a reset operation.
    """
    from infrastructure.owned_io import SafeRoot, LockAcquireTimeout
    from domains.research_review_generation.assembly import assemble_runtime
    from domains.research_review_generation import run_generation

    if not bindings_path or not bindings_sha256 or not review_root:
        raise _v4_global(_v4_scope, '_manual_error')(503, "GENERATION_NOT_CONFIGURED", "手动生成尚未绑定服务端配置。")
    try:
        path = _v4_global(_v4_scope, 'Path')(bindings_path)
        if not path.is_absolute() or ".." in path.parts:
            raise _v4_global(_v4_scope, 'ValueError')("binding path")
        raw = SafeRoot(path.parent).read_bytes(path.name, max_bytes=128 * 1024)
        if _v4_global(_v4_scope, 'hashlib').sha256(raw).hexdigest() != bindings_sha256:
            raise _v4_global(_v4_scope, 'ValueError')("binding digest")
        binding = _v4_global(_v4_scope, 'json').loads(raw)
        if (_v4_global(_v4_scope, 'set')(binding) != {"schema_version", "config_root", "review_root", "dates"}
                or binding["schema_version"] != "v4.manual_review_bindings.v1"
                or not _v4_global(_v4_scope, 'isinstance')(binding["dates"], _v4_global(_v4_scope, 'dict'))):
            raise _v4_global(_v4_scope, 'ValueError')("binding schema")
        if date not in binding["dates"]:
            raise _v4_global(_v4_scope, '_manual_error')(404, "DATE_NOT_CONFIGURED", "该日期没有单独批准的生成配置。")
        item = binding["dates"][date]
        if _v4_global(_v4_scope, 'set')(item) != {"config", "config_sha256", "source_manifest_sha256"}:
            raise _v4_global(_v4_scope, 'ValueError')("date binding")
        root = _v4_global(_v4_scope, 'Path')(binding["config_root"])
        output = _v4_global(_v4_scope, 'Path')(binding["review_root"])
        if (not root.is_absolute() or ".." in root.parts or not output.is_absolute()
                or ".." in output.parts or output != _v4_global(_v4_scope, 'Path')(review_root)):
            raise _v4_global(_v4_scope, 'ValueError')("root mismatch")
        # Validate every ancestry using the shared safe reader before assembly.
        SafeRoot(root).read_bytes(item["config"], max_bytes=128 * 1024)
        runtime = assemble_runtime(config_path=root / item["config"],
            config_sha256=item["config_sha256"],
            implementation_manifest_sha256=item["source_manifest_sha256"],
            transport=transport, client_factory=client_factory)
        if output != runtime.state_root / "reviews":
            raise _v4_global(_v4_scope, 'ValueError')("reader/writer root mismatch")
        asof = _v4_global(_v4_scope, 'datetime').fromisoformat(runtime.configuration["data_as_of"])
        if asof.tzinfo is None or asof.astimezone(_v4_global(_v4_scope, 'ZoneInfo')("Asia/Shanghai")).strftime("%Y%m%d") != date:
            raise _v4_global(_v4_scope, '_manual_error')(422, "CONFIG_DATE_MISMATCH", "生成配置的事实日期与所选日期不一致。")
    except _v4_global(_v4_scope, 'HTTPException'):
        raise
    except _v4_global(_v4_scope, 'Exception'):
        # Do not relay config paths, arbitrary SDK messages or credential data.
        raise _v4_global(_v4_scope, '_manual_error')(503, "GENERATION_BINDING_INVALID", "服务端生成绑定未通过校验。") from None

    identity = {"date": date, "config_sha256": item["config_sha256"],
                "source_manifest_sha256": item["source_manifest_sha256"]}
    io = SafeRoot(runtime.state_root)
    relative = f"manual_generation/{date}.json"

    def existing() -> dict[str, Any] | None:
        result = _v4_global(_v4_scope, 'load_daily_research_review')(date, review_root=output)
        if result.get("status") == "READY":
            return {"status": "ALREADY_EXISTS", "trade_date": date,
                    "artifact_sha256": result.get("artifact_sha256", ""), **_v4_global(_v4_scope, '_SAFETY_FLAGS')}
        return None

    def save(status: str) -> None:
        value = {"schema_version": "v4.manual_review_attempt.v1", **identity,
                 "status": status, **_v4_global(_v4_scope, '_SAFETY_FLAGS')}
        io.write_bytes(relative, (_v4_global(_v4_scope, 'json').dumps(value, sort_keys=True) + "\n").encode())

    ready = existing()
    if ready is not None:
        return ready
    try:
        # Uses the existing SafeRoot kernel lock; generation still obtains its
        # own public same-date lock and never receives replace=True.
        with io.kernel_lock(f"manual_generation/{date}.lock", timeout=0):
            ready = existing()
            if ready is not None:
                return ready
            try:
                previous = _v4_global(_v4_scope, 'json').loads(io.read_bytes(relative, max_bytes=8192))
            except _v4_global(_v4_scope, 'FileNotFoundError'):
                previous = None
            if previous is not None:
                raise _v4_global(_v4_scope, '_manual_error')(409, "ATTEMPT_REQUIRES_REVIEW", "该日期已有生成尝试，请核对记录后再处理；未重复请求模型。")
            save("RUNNING")
            try:
                result = run_generation(date, review_root=output, runtime=runtime)
                save("SUCCEEDED")
                return {"status": result["status"], "trade_date": date,
                        "artifact_sha256": result["artifact_sha256"], **_v4_global(_v4_scope, '_SAFETY_FLAGS')}
            except _v4_global(_v4_scope, 'Exception'):
                ready = existing()  # Another caller of the existing CLI may have won.
                if ready is not None:
                    save("ALREADY_EXISTS")
                    return ready
                save("FAILED")
                raise _v4_global(_v4_scope, '_manual_error')(502, "GENERATION_FAILED", "生成未完成；请核对本地记录，未自动重试。") from None
    except LockAcquireTimeout:
        raise _v4_global(_v4_scope, '_manual_error')(409, "GENERATION_RUNNING", "该日期正在生成，请勿重复提交。") from None
    except _v4_global(_v4_scope, 'HTTPException'):
        raise
    except _v4_global(_v4_scope, 'Exception'):
        raise _v4_global(_v4_scope, '_manual_error')(503, "GENERATION_STATE_UNAVAILABLE", "生成状态无法安全确认，请核对本地记录。") from None
