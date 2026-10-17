## Source excerpt: `tests/test_runtime_dispatcher.py`

Original source path: `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/futu-industry-us-20261016-r1/app/tests/test_runtime_dispatcher.py`

Original full-file SHA-256: `2d4427e7a7c5f389480b0b0639b9eed7efb26dc1989820a8424786b369e0aa90`

Release/worktree group: `us_digest`

Existing missing/mismatched release identity and runtime inventory hash tests.

### Full-source lines 371-388

```python

@pytest.mark.parametrize("field", ["V35_APP_ROOT", "V35_RELEASE_ID", "V35_RELEASE_MANIFEST_PATH", "V35_RELEASE_MANIFEST_SHA256"])
def test_release_identity_missing_rejects_before_claim(tmp_path, monkeypatch, field):
    monkeypatch.delenv(field)
    executor = FakeExecutor(); ledger = ExecutionLedger(tmp_path / "ledger")
    receipt = dispatch_due(DispatchRequest("20260914", "20260914", "20260914", "1200", DispatchMode.LIVE),
                           load_workload_catalog(), executor, ledger=ledger)
    assert receipt.status == "FAILED" and receipt.failure_class == "RELEASE_IDENTITY"
    assert executor.calls == [] and not list((tmp_path / "ledger").rglob("*.json"))

@pytest.mark.parametrize("field,value", [("V35_APP_ROOT", "/not/current/release"), ("V35_RELEASE_ID", "wrong-release"),
                                        ("V35_RELEASE_MANIFEST_SHA256", "0"*64)])
def test_release_identity_mismatch_rejects_before_executor(tmp_path, monkeypatch, field, value):
    monkeypatch.setenv(field, value); executor = FakeExecutor()
    receipt = dispatch_due(DispatchRequest("20260914", "20260914", "20260914", "1200", DispatchMode.LIVE),
                           load_workload_catalog(), executor, ledger=ExecutionLedger(tmp_path / "ledger"))
    assert receipt.status == "FAILED" and receipt.failure_class == "RELEASE_IDENTITY"
    assert not executor.calls


```

### Full-source lines 412-420

```python

def test_manifest_inventory_bad_runtime_hash_rejected(tmp_path, approved_release_binding, monkeypatch):
    path = Path(approved_release_binding["V35_RELEASE_MANIFEST_PATH"])
    obj = json.loads(path.read_bytes()); entries = obj["application_inventory"]["entries"]
    entries[0]["sha256"] = "1" * 64
    obj["application_inventory"]["aggregate_sha256"] = hashlib.sha256(json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    raw = json.dumps(obj).encode(); path.write_bytes(raw); monkeypatch.setenv("V35_RELEASE_MANIFEST_SHA256", hashlib.sha256(raw).hexdigest())
    executor = FakeExecutor()
    receipt = dispatch_due(DispatchRequest("20260914", "20260914", "20260914", "0700", DispatchMode.LIVE), load_workload_catalog(), executor)
    assert receipt.failure_class == "RELEASE_IDENTITY" and not executor.calls

```
