from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from infrastructure import local_document_model as local_model


def _binding(tmp_path: Path, schema: dict, *, model_settings: str = "model-settings") -> dict:
    runtime_path = tmp_path / "runtime-settings.json"
    model_path = tmp_path / "model-settings.json"
    runtime_path.write_text("runtime-settings", encoding="utf-8")
    model_path.write_text(model_settings, encoding="utf-8")
    evidence_root = tmp_path / "receipts"
    return {
        "model_id": local_model.MODEL_ID,
        "workflow_profile": local_model.PROFILE_NAME,
        "tools": [],
        "request_temperature": 0.0,
        "enable_thinking": False,
        "request_schema_sha256": local_model.sha256_bytes(local_model.canonical_json(schema)),
        "request_schema_wrapper_sha256": local_model.sha256_bytes(
            local_model.canonical_json({"json": schema})
        ),
        "runtime_settings_sha256": hashlib.sha256(b"runtime-settings").hexdigest(),
        "model_settings_sha256": hashlib.sha256(model_settings.encode()).hexdigest(),
        "runtime_limits": {"context_length": 32768},
        "max_completion_tokens": local_model.MAX_COMPLETION_TOKENS,
        "request_policy": {"sampling": "fixed"},
        "configuration_sha256": "a" * 64,
        "runtime_settings_path": str(runtime_path),
        "model_settings_path": str(model_path),
        "runtime_python": str(local_model.RUNTIME_PYTHON),
        "source_sha256": {"pinned": "b" * 64},
        "active_server_memory_settings": "CANNOT_CONFIRM",
        "evidence_root": str(evidence_root),
    }


def _sse(content: str) -> bytes:
    events = [
        {
            "model": local_model.MODEL_ID,
            "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": None}],
        },
        {
            "model": local_model.MODEL_ID,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 9, "completion_tokens": 3, "total_tokens": 12},
        },
        "[DONE]",
    ]
    return b"".join(
        ("data: " + (event if isinstance(event, str) else json.dumps(event)) + "\n\n").encode()
        for event in events
    )


def test_pinned_sources_and_runtime_interpreter_fail_closed() -> None:
    sources = local_model.pinned_source_hashes()
    assert sources["announcement_queue.py"] == local_model.PINNED_SOURCE_SHA256["announcement_queue.py"]
    assert sources["v4/manager_workbench/inputs/pdf_pages.py"] == "ec1d4990277868e42d6d3a7ff93972e80a89e44dcfaa7c9d9f656c32ae07a770"
    assert "infrastructure/pdf_research.py" in sources
    with pytest.raises(local_model.LocalModelError, match="PDF_RUNTIME_INTERPRETER_MISMATCH"):
        local_model.require_runtime_python("/tmp/not-the-approved-runtime/python")


def test_request_uses_actual_structured_schema_and_never_advertises_tools(tmp_path, monkeypatch) -> None:
    schema = {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
        "additionalProperties": False,
    }
    binding = _binding(tmp_path, schema)
    monkeypatch.setattr(local_model, "PDF_EVIDENCE_ROOT", Path(binding["evidence_root"]))
    monkeypatch.setattr(local_model, "build_request_material", lambda observed_schema: dict(binding))
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, content=_sse('{"ok":true}'), headers={"content-type": "text/event-stream"})

    job = SimpleNamespace(idempotency_key="d" * 64, attempt=1)
    result = local_model.request_document_analysis(
        job=job,
        messages=[{"role": "system", "content": "analyze"}, {"role": "user", "content": "source"}],
        schema=schema,
        expected_binding=binding,
        api_key="test-only-key",
        http_transport=httpx.MockTransport(handler),
    )

    assert result == '{"ok":true}'
    assert len(captured) == 1
    request = captured[0]
    body = json.loads(request.content)
    assert request.method == "POST"
    assert request.url.path == "/v1/chat/completions"
    assert body["model"] == local_model.MODEL_ID
    assert body["structured_outputs"] == {"json": schema}
    assert body["enable_thinking"] is False
    assert body["temperature"] == 0.0
    assert "tools" not in body
    assert request.headers["authorization"] == "Bearer test-only-key"


def test_pdf_context_runs_model_selected_local_action_loop(tmp_path, monkeypatch) -> None:
    schema = {
        "type": "object",
        "properties": {"analysis_markdown": {"type": "string"}},
        "required": ["analysis_markdown"],
        "additionalProperties": False,
    }
    binding = _binding(tmp_path, schema)
    evidence_root = Path(binding["evidence_root"])
    monkeypatch.setattr(local_model, "PDF_EVIDENCE_ROOT", evidence_root)
    monkeypatch.setattr(local_model, "build_request_material", lambda _schema: dict(binding))
    fake_modules = SimpleNamespace(runner=SimpleNamespace(), canary=SimpleNamespace())
    monkeypatch.setattr(local_model, "load_shared_modules", lambda: fake_modules)
    context = {
        "page_input_sha256": "d" * 64,
        "pages": [
            {
                "page_number": 1,
                "page_total": 1,
                "text": "Acme delivery",
                "text_sha256": hashlib.sha256(b"Acme delivery").hexdigest(),
            }
        ],
    }
    actions = [
        {"action": "read", "arguments": {"page_number": 1}},
        {"action": "final", "report": "Acme delivery is documented on page 1."},
    ]
    captured: list[tuple[list[dict[str, str]], dict[str, object]]] = []
    finalizations: list[dict[str, object]] = []

    class FakeTransport:
        def __init__(self, *_args, **_kwargs):
            self._trace_meta: dict[str, object] = {}

        def begin_job(self, _job):
            return None

        def complete_batch(self, messages, *, tools, structured_outputs, workflow_profile):
            captured.append((messages, {"tools": tools, "structured_outputs": structured_outputs, "workflow_profile": workflow_profile}))
            action = actions[len(captured) - 1]
            final_text = json.dumps(
                {"analysis_markdown": json.dumps(action, ensure_ascii=False, separators=(",", ":"))},
                ensure_ascii=False,
                separators=(",", ":"),
            )
            return SimpleNamespace(
                final_text=final_text,
                request_rounds=1,
                tool_receipts=[],
                usage={"total_tokens": 1},
                started_at="2026-10-19T00:00:00Z",
                finished_at="2026-10-19T00:00:01Z",
                first_event_at=None,
                first_event_seconds=None,
                ttft_seconds=None,
                first_content_at=None,
                ttfc_seconds=None,
                response_model=local_model.MODEL_ID,
            )

        def finish_job(self, **kwargs):
            finalizations.append(kwargs)

        def close(self):
            return None

    monkeypatch.setattr(local_model, "_no_lookup_transport_class", lambda _modules: FakeTransport)
    result = local_model.request_document_analysis(
        job=SimpleNamespace(idempotency_key="f" * 64, attempt=1),
        messages=[{"role": "system", "content": "research"}, {"role": "user", "content": "source"}],
        schema=schema,
        expected_binding=binding,
        tool_context=context,
        api_key="test-only-key",
    )

    assert json.loads(result) == {"analysis_markdown": actions[-1]["report"]}
    assert len(captured) == 2
    assert all(call_options["tools"] == [] for _messages, call_options in captured)
    assert all(call_options["structured_outputs"] == {"json": schema} for _messages, call_options in captured)
    assert all(call_options["workflow_profile"] == local_model.PROFILE_NAME for _messages, call_options in captured)
    assert "Acme delivery" in captured[1][0][-1]["content"]
    assert finalizations[0]["status"] == "SUCCEEDED"
    assert finalizations[0]["completion"].tool_receipts[0]["name"] == "read"


def test_binding_mismatch_is_rejected_before_transport_or_post(tmp_path, monkeypatch) -> None:
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    binding = _binding(tmp_path, schema)
    monkeypatch.setattr(local_model, "PDF_EVIDENCE_ROOT", Path(binding["evidence_root"]))
    changed = {**binding, "request_schema_sha256": "f" * 64}
    monkeypatch.setattr(local_model, "build_request_material", lambda observed_schema: changed)
    requests: list[httpx.Request] = []
    handler = httpx.MockTransport(lambda request: requests.append(request) or httpx.Response(500))

    with pytest.raises(local_model.LocalModelError, match="REQUEST_BINDING_MISMATCH"):
        local_model.request_document_analysis(
            job=SimpleNamespace(idempotency_key="e" * 64, attempt=1),
            messages=[{"role": "user", "content": "source"}],
            schema=schema,
            expected_binding=binding,
            api_key="test-only-key",
            http_transport=handler,
        )
    assert requests == []


def test_settings_change_fails_before_http_post(tmp_path, monkeypatch) -> None:
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    binding = _binding(tmp_path, schema)
    Path(binding["runtime_settings_path"]).write_text("changed", encoding="utf-8")
    monkeypatch.setattr(local_model, "PDF_EVIDENCE_ROOT", Path(binding["evidence_root"]))
    monkeypatch.setattr(local_model, "build_request_material", lambda observed_schema: dict(binding))
    requests: list[httpx.Request] = []
    handler = httpx.MockTransport(lambda request: requests.append(request) or httpx.Response(500))

    with pytest.raises(Exception, match="RUNTIME_SETTINGS_BINDING_MISMATCH"):
        local_model.request_document_analysis(
            job=SimpleNamespace(idempotency_key="f" * 64, attempt=1),
            messages=[{"role": "user", "content": "source"}],
            schema=schema,
            expected_binding=binding,
            api_key="test-only-key",
            http_transport=handler,
        )
    assert requests == []


def test_lookup_envelope_is_denied_without_external_request(tmp_path) -> None:
    modules = local_model.load_shared_modules()
    transport_class = local_model._no_lookup_transport_class(modules)
    requests: list[httpx.Request] = []
    transport = transport_class(
        "test-only-key",
        tmp_path / "receipts",
        http_transport=httpx.MockTransport(lambda request: requests.append(request) or httpx.Response(200)),
    )
    try:
        with pytest.raises(local_model.PdfLookupForbidden, match="PDF_LOOKUP_FORBIDDEN"):
            transport._call_simple_workflow_lookup({"operation": "search", "query": "ignored"}, lambda _event: None)
    finally:
        transport.close()
    assert requests == []


def test_parsed_lookup_envelope_is_denied_before_any_followup_request(tmp_path, monkeypatch) -> None:
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    binding = _binding(tmp_path, schema)
    monkeypatch.setattr(local_model, "PDF_EVIDENCE_ROOT", Path(binding["evidence_root"]))
    monkeypatch.setattr(local_model, "build_request_material", lambda observed_schema: dict(binding))
    envelope = {
        "action": "lookup",
        "lookup_request": {
            "operation": "search",
            "missing_fact": "A source fact",
            "reader_field": "document_type",
            "query": "ignored query",
            "url": "",
        },
        "reader_output": None,
    }
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            content=_sse(json.dumps(envelope)),
            headers={"content-type": "text/event-stream"},
        )

    with pytest.raises(local_model.PdfLookupForbidden, match="PDF_LOOKUP_FORBIDDEN"):
        local_model.request_document_analysis(
            job=SimpleNamespace(idempotency_key="g" * 64, attempt=1),
            messages=[{"role": "user", "content": "source"}],
            schema=schema,
            expected_binding=binding,
            api_key="test-only-key",
            http_transport=httpx.MockTransport(handler),
        )
    assert len(captured) == 1
    assert captured[0].method == "POST"
    assert captured[0].url.path == "/v1/chat/completions"


def _direct_pdf_transport(tmp_path, monkeypatch, *, stream=None, clock=lambda: 0, handler=None, raw_sink=None, progress_sink=None):
    from infrastructure import pdf_research_protocol as protocol
    binding = _binding(tmp_path, protocol.SCHEMA)
    monkeypatch.setattr(local_model, 'require_runtime_python', lambda: None)
    monkeypatch.setattr(local_model, 'build_request_material', lambda _schema: dict(binding))
    captured = []
    def default(request):
        captured.append(request)
        return httpx.Response(200, stream=stream) if stream is not None else httpx.Response(200, content=_sse('{"card":"direct"}'))
    raw = [] if raw_sink is None else raw_sink
    progress = [] if progress_sink is None else progress_sink
    text = local_model.request_pdf_card(messages=[{'role': 'user', 'content': 'source'}], schema=protocol.SCHEMA,
        expected_binding=binding, on_raw=raw.append, on_progress=progress.append,
        api_key='test-only-key', http_transport=httpx.MockTransport(handler or default), clock=clock)
    return text, captured, raw, progress


def test_direct_pdf_card_uses_same_auth_config_but_no_announcement_parser(tmp_path, monkeypatch):
    from infrastructure import pdf_research_protocol as protocol
    text, requests, raw, progress = _direct_pdf_transport(tmp_path, monkeypatch)
    assert text == '{"card":"direct"}'
    assert len(requests) == 1
    body = json.loads(requests[0].content)
    assert body['structured_outputs'] == {'json': protocol.SCHEMA}
    assert 'tools' not in body and body['temperature'] == 0 and body['enable_thinking'] is False
    assert requests[0].headers['authorization'] == 'Bearer test-only-key'
    assert b''.join(raw) == _sse('{"card":"direct"}')
    assert progress and all(x['kind'] == 'model_stream' for x in progress)


# Exact 186 bytes from the first real canary, retained as a local regression
# fixture; no model request or source text is included in this test module.
_REAL_NOOP_KEEPALIVE = b'data: {"id":"chatcmpl-d029ac06","object":"chat.completion.chunk","created":0,"model":"keepalive","choices":[{"index":0,"delta":{"role":"assistant","content":""},"finish_reason":null}]}\n\n'


def test_pdf_heartbeat_exact_real_control_preserves_raw_then_accepts_real_content(tmp_path, monkeypatch):
    assert hashlib.sha256(_REAL_NOOP_KEEPALIVE).hexdigest() == '9bea555ecf4c3abb2589d3486a56bb408374aa12701825ce59778b079210dc16'
    body = _REAL_NOOP_KEEPALIVE + _sse('{"card":"direct"}')
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            yield body[:37]
            yield body[37:186]
            yield body[186:]
    text, requests, raw, progress = _direct_pdf_transport(tmp_path, monkeypatch, stream=Stream())
    assert text == '{"card":"direct"}' and len(requests) == 1
    capture = tmp_path / 'raw-stream.sse'; capture.write_bytes(b''.join(raw))
    assert capture.read_bytes() == body
    assert progress == [{'kind': 'model_stream', 'characters': len(text)}]


def test_pdf_heartbeat_does_not_hide_genuine_wrong_model(tmp_path, monkeypatch):
    body = _REAL_NOOP_KEEPALIVE + _sse('answer').replace(local_model.MODEL_ID.encode(), b'wrong-real-model')
    raw = []
    with pytest.raises(local_model.PdfCardTransportError, match='PDF_RESPONSE_MODEL_ID_MISMATCH'):
        _direct_pdf_transport(tmp_path, monkeypatch, handler=lambda _request: httpx.Response(200, content=body), raw_sink=raw)
    assert b''.join(raw) == body


@pytest.mark.parametrize('mutation', ['content', 'reasoning', 'tool', 'function', 'error', 'finish', 'usage', 'extra', 'wrong_role', 'bool_index'])
def test_pdf_heartbeat_tagged_meaningful_or_foreign_payload_never_bypasses_checks(tmp_path, monkeypatch, mutation):
    value = json.loads(_REAL_NOOP_KEEPALIVE[len(b'data: '):])
    delta = value['choices'][0]['delta']
    if mutation == 'content': delta['content'] = 'not a control frame'
    if mutation == 'reasoning': delta['reasoning_content'] = 'hidden thought'
    if mutation == 'tool': delta['tool_calls'] = [{'name': 'lookup'}]
    if mutation == 'function': delta['function_call'] = {'name': 'lookup'}
    if mutation == 'error': value['error'] = {'code': 'real_runtime_error'}
    if mutation == 'finish': value['choices'][0]['finish_reason'] = 'stop'
    if mutation == 'usage': value['usage'] = {'completion_tokens': 1}
    if mutation == 'extra': value['unexpected_payload'] = 'meaningful'
    if mutation == 'wrong_role': delta['role'] = 'user'
    if mutation == 'bool_index': value['choices'][0]['index'] = False
    body = b'data: ' + json.dumps(value).encode() + b'\n\n'
    raw = []; progress = []
    code = 'PDF_MODEL_ERROR:real_runtime_error' if mutation == 'error' else 'PDF_RESPONSE_MODEL_ID_MISMATCH'
    with pytest.raises(local_model.PdfCardTransportError, match=code):
        _direct_pdf_transport(tmp_path, monkeypatch, handler=lambda _request: httpx.Response(200, content=body), raw_sink=raw, progress_sink=progress)
    assert b''.join(raw) == body and progress == []


def test_pdf_heartbeat_only_stream_is_not_a_successful_completion(tmp_path, monkeypatch):
    body = _REAL_NOOP_KEEPALIVE + b'data: [DONE]\n\n'
    raw = []; progress = []
    with pytest.raises(local_model.PdfCardTransportError, match='PDF_STREAM_EOF_OUTCOME_UNCERTAIN'):
        _direct_pdf_transport(tmp_path, monkeypatch, handler=lambda _request: httpx.Response(200, content=body), raw_sink=raw, progress_sink=progress)
    assert b''.join(raw) == body and progress == []


def test_pdf_heartbeat_noop_does_not_reset_substantive_90_second_budget(tmp_path, monkeypatch):
    current = [0]; raw = []; progress = []
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            for _ in range(4):
                current[0] += 31
                yield _REAL_NOOP_KEEPALIVE
    with pytest.raises(local_model.PdfCardTransportError, match='PDF_TRANSPORT_NO_PROGRESS'):
        _direct_pdf_transport(tmp_path, monkeypatch, stream=Stream(), clock=lambda: current[0], raw_sink=raw, progress_sink=progress)
    assert b''.join(raw) == _REAL_NOOP_KEEPALIVE * 3 and progress == []


def test_pdf_transport_allows_healthy_actual_progress_beyond_150_seconds(tmp_path, monkeypatch):
    current = [0]
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            for i in range(7):
                current[0] += 30
                yield ('data: ' + json.dumps({'model': local_model.MODEL_ID, 'choices': [{'delta': {'content': str(i)}, 'finish_reason': None}]}) + '\n\n').encode()
            yield b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
    text, requests, raw, progress = _direct_pdf_transport(tmp_path, monkeypatch, stream=Stream(), clock=lambda: current[0])
    assert text == '0123456' and current[0] == 210 and len(progress) == 7 and len(requests) == 1


def test_pdf_transport_comments_do_not_reset_90_second_actual_progress_budget(tmp_path, monkeypatch):
    current = [0]
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            for _ in range(4):
                current[0] += 31
                yield b': keepalive\n\n'
    with pytest.raises(local_model.PdfCardTransportError, match='NO_PROGRESS'):
        _direct_pdf_transport(tmp_path, monkeypatch, stream=Stream(), clock=lambda: current[0])


@pytest.mark.parametrize('body,code', [(b'data: {"error":{"code":"prefill_memory_exceeded"}}\n\n', 'prefill_memory_exceeded'),
    (b'data: {"choices":[{"delta":{"content":"partial"},"finish_reason":null}]}\n\n', 'EOF_OUTCOME'),
    (b'data: {"choices":[{"delta":{"tool_calls":[{}]},"finish_reason":null}]}\n\n', 'TOOL_REQUEST')])
def test_pdf_terminal_stream_failures_preserve_raw_without_followup(tmp_path, monkeypatch, body, code):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, content=body)
    with pytest.raises(local_model.PdfCardTransportError, match=code):
        _direct_pdf_transport(tmp_path, monkeypatch, handler=handler)
    assert len(requests) == 1
