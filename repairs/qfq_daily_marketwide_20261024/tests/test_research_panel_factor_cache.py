from pathlib import Path
import json
import pytest
from ops import research_panel_factor_cache as cache

class Client:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []
        self.closed = False
    def get_rehab(self, code):
        self.calls.append(code)
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        return result
    def close(self):
        self.closed = True


def test_metadata_empty_error_retry_and_resume_are_distinct(tmp_path):
    client = Client([(0, []), (0, [dict(ex_div_date="2026-05-26", forward_adj_factorA=.77069, forward_adj_factorB=-.29046, backward_adj_factorA=1.29754)]), (-1, "BJ unsupported"), (-1, "BJ unsupported")])
    sleeps = []
    result = cache.collect_metadata(["002612.SZ", "001283.SZ", "920000.BJ"], cache_root=tmp_path, target=20261023,
                                     client_factory=lambda: client, retries=1, sleep=sleeps.append, monotonic=lambda: 0)
    assert result["symbols"]["001283.SZ"]["status"] == "EMPTY"
    assert result["symbols"]["002612.SZ"]["status"] == "OK"
    assert result["symbols"]["920000.BJ"]["status"] == "ERROR"
    assert result["status"] == "FAILED" and "completed_at" not in result
    assert client.closed

    assert .2 in sleeps
    other = Client([(0, [])])
    again = cache.collect_metadata(["001283.SZ", "002612.SZ"], cache_root=tmp_path, target=20261023,
                                    client_factory=lambda: other, sleep=lambda _: None)
    assert other.calls == []
    assert again["symbols"]["001283.SZ"]["queried_at"] == result["symbols"]["001283.SZ"]["queried_at"]


def test_same_asof_stale_empty_is_refreshed_and_bj_format_is_explicit_partial(tmp_path):
    client = Client([(0, [])])
    cache.collect_metadata(["001283.SZ"], cache_root=tmp_path, target=20261023, client_factory=lambda: client)
    checkpoint = tmp_path / "20261023/checkpoint.json"
    state = json.loads(checkpoint.read_text())
    state["symbols"]["001283.SZ"].update(queried_at="2000-01-01T00:00:00+00:00", capture_date=20000101)
    checkpoint.write_text(json.dumps(state))
    fresh = Client([(0, []), (-1, "ERROR. format of code BJ.830779 is wrong. (US.AAPL, HK.00700, SZ.000001)")])
    result = cache.collect_metadata(["001283.SZ", "830779.BJ"], cache_root=tmp_path, target=20261023,
                                    client_factory=lambda: fresh, min_interval=0)
    assert fresh.calls == ["SZ.001283", "BJ.830779"]
    assert result["status"] == "PARTIAL_EXPECTED_UNSUPPORTED"
    assert result["counts"]["UNSUPPORTED_MARKET"] == 1
    assert "completed_at" not in result and result["finished_at"]
    assert result["symbols"]["001283.SZ"]["asof_date"] == 20261023
    assert result["symbols"]["001283.SZ"]["capture_date"] == cache._capture_date()
    unsupported = result["symbols"]["830779.BJ"]
    assert unsupported["response"]["sha256"] == cache.sha(Path(unsupported["response"]["path"]))


def test_reviewed_entry_propagates_unexpected_errors_and_binds_original_universe(tmp_path):
    from ops.collect_research_panel_adjustment_metadata import execute
    source = tmp_path / "original_summary.json"
    source.write_text('{"original":"fixture"}')
    universe = tmp_path / "universe.json"
    universe.write_text(json.dumps(dict(target_date="20261023", target_count=1, items=[dict(ts_code="001283.SZ")],
                                        source_path=str(source), source_sha256=cache.sha(source))))
    def failed(codes, **kwargs):
        assert codes == ["001283.SZ"] and kwargs["max_age_seconds"] == 86400
        return dict(status="FAILED", counts=dict(ERROR=1), requested_codes_sha256=cache.canonical_sha(codes), finished_at=cache._now())
    code, receipt = execute(universe_path=universe, universe_sha256=cache.sha(universe), target=20261023,
                            cache_root=tmp_path / "cache", collector=failed)
    assert code == 2 and receipt["status"] == "FAILED"
    assert receipt["counts"]["ERROR"] == 1
    with pytest.raises(cache.QfqGateError, match="UNIVERSE_INPUT_SHA256_MISMATCH"):
        execute(universe_path=universe, universe_sha256="0" * 64, target=20261023, cache_root=tmp_path / "cache", collector=failed)


def test_duplicate_and_missing_factor_protocol_fail():
    row = dict(ex_div_date="2026-05-26", forward_adj_factorA=.77069, forward_adj_factorB=-.29046, backward_adj_factorA=1.29754)
    with pytest.raises(cache.QfqGateError, match="DUPLICATE"):
        cache._event_rows([row, row], 20261023, 20200101)
    with pytest.raises(cache.QfqGateError, match="AFFINE_MISSING"):
        cache._event_rows([dict(ex_div_date="2026-05-26")], 20261023, 20200101)


def test_forced_same_asof_revision_keeps_original_response_bytes(tmp_path):
    row = dict(ex_div_date="2026-05-26", forward_adj_factorA=.77069, forward_adj_factorB=-.29046, backward_adj_factorA=1.29754)
    first = Client([(0, [row])])
    one = cache.collect_metadata(["001283.SZ"], cache_root=tmp_path, target=20261023, client_factory=lambda: first, min_interval=0)
    original = one["symbols"]["001283.SZ"]["response"]
    before = Path(original["path"]).read_bytes()
    second = Client([(0, [{**row, "forward_adj_factorB": -.3}])])
    two = cache.collect_metadata(["001283.SZ"], cache_root=tmp_path, target=20261023, client_factory=lambda: second,
                                 force_refresh=True, min_interval=0)
    assert two["symbols"]["001283.SZ"]["response"]["sha256"] != original["sha256"]
    assert Path(original["path"]).read_bytes() == before
    assert first.closed and second.closed


def test_corrupt_cached_response_blocks_before_network(tmp_path):
    client = Client([(0, [])])
    result = cache.collect_metadata(["001283.SZ"], cache_root=tmp_path, target=20261023, client_factory=lambda: client)
    path = Path(result["symbols"]["001283.SZ"]["response"]["path"])
    path.write_text("corrupt")
    def forbidden():
        raise AssertionError("must validate cached response first")
    with pytest.raises(cache.QfqGateError, match="SOURCE_BINDING_FAILED"):
        cache.collect_metadata(["001283.SZ"], cache_root=tmp_path, target=20261023, client_factory=forbidden)


def test_context_error_and_interrupted_query_remain_explicit(tmp_path):
    def failed_context():
        raise ConnectionError("OpenD unavailable fixture")
    with pytest.raises(ConnectionError):
        cache.collect_metadata(["001283.SZ"], cache_root=tmp_path, target=20261023, client_factory=failed_context)
    checkpoint = json.loads((tmp_path / "20261023/checkpoint.json").read_text())
    assert checkpoint["context_error"]["error"] == "OpenD unavailable fixture"
    client = Client([RuntimeError("transient fixture"), (0, [])])
    result = cache.collect_metadata(["001283.SZ"], cache_root=tmp_path, target=20261023, client_factory=lambda: client,
                                    retries=1, min_interval=0, sleep=lambda _: None)
    assert result["symbols"]["001283.SZ"]["status"] == "EMPTY"
    assert result["symbols"]["001283.SZ"]["attempts"] == 2
    assert client.closed

