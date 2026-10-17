## Source excerpt: `infrastructure/scheduling/dispatcher.py`

Original source path: `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/futu-industry-us-20261016-r1/app/infrastructure/scheduling/dispatcher.py`

Original full-file SHA-256: `7e61cbb234246bd88c9325fb0641c4bbead10debed09b924298e406b06854668`

Release/worktree group: `us_digest`

Deployed US digest dispatcher release identity validation and fail-closed dispatch boundary.

### Full-source lines 43-78

```python

def validate_release_identity() -> dict[str, str]:
    """Fail before claims/transport when API and scheduler release pins diverge."""
    names = ("V35_APP_ROOT", "V35_RELEASE_ID", "V35_RELEASE_MANIFEST_PATH", "V35_RELEASE_MANIFEST_SHA256")
    env = {name: os.environ.get(name, "") for name in names}
    if any(not value for value in env.values()):
        raise ValueError("RELEASE_IDENTITY_MISSING")
    app = Path(env["V35_APP_ROOT"]); path = Path(env["V35_RELEASE_MANIFEST_PATH"])
    if (not app.is_absolute() or not path.is_absolute() or ".." in app.parts or ".." in path.parts
            or app != Path(__file__).resolve().parents[2]
            or not re.fullmatch(r"[0-9a-f]{64}", env["V35_RELEASE_MANIFEST_SHA256"])):
        raise ValueError("RELEASE_IDENTITY_INVALID")
    raw = SafeRoot(path.parent).read_bytes(path.name, max_bytes=16 * 1024 * 1024)
    if hashlib.sha256(raw).hexdigest() != env["V35_RELEASE_MANIFEST_SHA256"]:
        raise ValueError("RELEASE_MANIFEST_SHA_MISMATCH")
    payload = json.loads(raw)
    if (payload.get("schema_version") != "v4.release_candidate.v1"
            or payload.get("candidate", {}).get("app_root") != str(app)
            or payload.get("candidate", {}).get("release_id") != env["V35_RELEASE_ID"]):
        raise ValueError("RELEASE_MANIFEST_IDENTITY_MISMATCH")
    inventory = payload["application_inventory"]; entries = inventory["entries"]
    if (not isinstance(entries, list) or inventory.get("entry_count") != len(entries)
            or hashlib.sha256(json.dumps(entries, ensure_ascii=False, sort_keys=True,
                 separators=(",", ":")).encode()).hexdigest() != inventory.get("aggregate_sha256")):
        raise ValueError("RELEASE_INVENTORY_MISMATCH")
    by_path = {item["path"]: item for item in entries}
    if len(by_path) != len(entries):
        raise ValueError("RELEASE_INVENTORY_DUPLICATE")
    source = SafeRoot(app)
    for relative in _RUNTIME_IDENTITY_FILES:
        item = by_path.get(relative, {})
        content = source.read_bytes(relative, max_bytes=8 * 1024 * 1024)
        if (item.get("kind") != "file" or item.get("size") != len(content)
                or item.get("sha256") != hashlib.sha256(content).hexdigest()):
            raise ValueError("RELEASE_RUNTIME_BYTES_MISMATCH")
    return {"release_id": env["V35_RELEASE_ID"], "app_root": str(app),
            "release_manifest_path": str(path), "release_manifest_sha256": env["V35_RELEASE_MANIFEST_SHA256"]}

```

### Full-source lines 246-260

```python

def dispatch_due(
    request: DispatchRequest,
    catalog: RuntimeCatalog,
    executor: Executor,
    *,
    ledger: ExecutionLedger | None = None,
    dry_run: bool = False,
) -> DispatchReceipt:
    if catalog.safety.production_allowed or catalog.safety.buy_gate_updated or catalog.safety.orders_sent:
        raise ValueError("unsafe runtime catalog")
    try:
        identity = validate_release_identity()
    except (OSError, ValueError, KeyError, TypeError):
        # No claim, executor, or allegedly verified identity on failure.
        return _receipt(request, status="FAILED", run_id=uuid4().hex, failure_class="RELEASE_IDENTITY")

```
