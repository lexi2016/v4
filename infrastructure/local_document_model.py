"""Pinned, no-lookup access to the shared local Qwen request transport.

This module deliberately owns no service, settings, queue, or model files.  It
loads the already deployed announcement transport by path and hash, then
reuses that transport's authenticated loopback client and model lock contract.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib
import json
from pathlib import Path
import sys
import time
from types import ModuleType, SimpleNamespace
from typing import Any, Mapping, Sequence


MODEL_ID = "qwen3_8_flash_next"
PROFILE_NAME = "decision_simple_facts"
REQUEST_TEMPERATURE = 0.0
ENABLE_THINKING = False
MAX_COMPLETION_TOKENS = 32768

PIPELINE_ROOT = Path(
    "/Users/lexi/Desktop/学习/agents调试/助手/qwen_flash_next_20261013/pipeline_canary"
)
RUNTIME_PYTHON = Path(
    "/Users/lexi/Desktop/学习/助手/local_llm/qwen3_8_flash_next/runtime/venv/bin/python"
)
SHARED_REQUEST_HELPER = PIPELINE_ROOT / "evidence/recent-day-20261014/recent_day_freeze.py"
PDF_PAGES_HELPER = Path(__file__).resolve().parents[1] / "v4/manager_workbench/inputs/pdf_pages.py"
PDF_EVIDENCE_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data/"
    "external_sources/zsxq_hourly/pdf_local/research/receipts"
)
PINNED_SOURCE_SHA256 = {
    "announcement_queue.py": "5e8158fc578c2e005204b984a95ada4429c15750f81a9c2fa58baa906cabc7b7",
    "batch_runner.py": "0d0c09139223d738a4fb918212b0c7dce3bbd17cd8dbd8a2dc74c7a86ef865cb",
    "automatic_canary_server.py": "c9d776d4fba5bd36da70f2a254f44205043ea24cfbd128e1710cbbd15c90756d",
    "build_length_canary.py": "d337b27e622b49ae38e0305dc729240901ce548d17f48c7b41776c9167f94a6d",
    "simple_fixed_facts.py": "f5b561b0f9be34b727df81b5002531bd955ce6e2b0949756c0b140d5ef2596a9",
    "recent_day_freeze.py": "43f70a0e57f81814a93f176079bfc5c20519dbda5b7a8f9e8062e3aa488c74b3",
}


class LocalModelError(RuntimeError):
    """A fail-closed request or binding error with a stable safe code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class PdfLookupForbidden(RuntimeError):
    """The model returned a lookup envelope; PDF work never performs lookup."""


@dataclass(frozen=True)
class SharedModules:
    queue: ModuleType
    runner: ModuleType
    canary: ModuleType


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def pinned_source_hashes() -> dict[str, str]:
    """Return current on-disk hashes only after every dependency matches its pin."""
    observed: dict[str, str] = {}
    for name, expected in PINNED_SOURCE_SHA256.items():
        path = PIPELINE_ROOT / name if name != "recent_day_freeze.py" else SHARED_REQUEST_HELPER
        if path.is_symlink() or not path.is_file():
            raise LocalModelError("PINNED_SHARED_SOURCE_UNAVAILABLE")
        actual = sha256_file(path)
        if actual != expected:
            raise LocalModelError("PINNED_SHARED_SOURCE_SHA_MISMATCH")
        observed[name] = actual
    if PDF_PAGES_HELPER.is_symlink() or not PDF_PAGES_HELPER.is_file():
        raise LocalModelError("PINNED_PDF_PAGES_HELPER_UNAVAILABLE")
    pdf_pages_sha = sha256_file(PDF_PAGES_HELPER)
    if pdf_pages_sha != "ec1d4990277868e42d6d3a7ff93972e80a89e44dcfaa7c9d9f656c32ae07a770":
        raise LocalModelError("PINNED_PDF_PAGES_HELPER_SHA_MISMATCH")
    observed["v4/manager_workbench/inputs/pdf_pages.py"] = pdf_pages_sha
    local_sources = {
        "infrastructure/local_document_model.py": Path(__file__),
        "infrastructure/pdf_research.py": Path(__file__).with_name("pdf_research.py"),
        "infrastructure/pdf_research_tools.py": Path(__file__).with_name("pdf_research_tools.py"),
        "ops/run_pdf_research_batch.py": Path(__file__).resolve().parents[1] / "ops/run_pdf_research_batch.py",
        "ops/run_pdf_research_sample.py": Path(__file__).resolve().parents[1] / "ops/run_pdf_research_sample.py",
    }
    for name, path in local_sources.items():
        if path.is_symlink() or not path.is_file():
            raise LocalModelError("PDF_LOCAL_SOURCE_UNAVAILABLE")
        observed[name] = sha256_file(path)
    return observed


def _import_pinned(name: str, expected_path: Path, expected_sha: str) -> ModuleType:
    existing = sys.modules.get(name)
    if existing is not None:
        try:
            actual_path = Path(existing.__file__).resolve()
        except (AttributeError, TypeError):
            raise LocalModelError("PINNED_SHARED_MODULE_IDENTITY_MISMATCH") from None
        if actual_path != expected_path.resolve() or sha256_file(expected_path) != expected_sha:
            raise LocalModelError("PINNED_SHARED_MODULE_IDENTITY_MISMATCH")
        return existing
    module = importlib.import_module(name)
    try:
        actual_path = Path(module.__file__).resolve()
    except (AttributeError, TypeError):
        raise LocalModelError("PINNED_SHARED_MODULE_IDENTITY_MISMATCH") from None
    if actual_path != expected_path.resolve() or sha256_file(expected_path) != expected_sha:
        raise LocalModelError("PINNED_SHARED_MODULE_IDENTITY_MISMATCH")
    return module


def load_shared_modules() -> SharedModules:
    """Load only the pinned existing queue and announcement request transport."""
    pinned_source_hashes()
    pipeline_text = str(PIPELINE_ROOT.resolve())
    if pipeline_text in sys.path:
        sys.path.remove(pipeline_text)
    sys.path.insert(0, pipeline_text)
    previous_dont_write_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        queue = _import_pinned(
            "announcement_queue",
            PIPELINE_ROOT / "announcement_queue.py",
            PINNED_SOURCE_SHA256["announcement_queue.py"],
        )
        _import_pinned(
            "simple_fixed_facts",
            PIPELINE_ROOT / "simple_fixed_facts.py",
            PINNED_SOURCE_SHA256["simple_fixed_facts.py"],
        )
        runner = _import_pinned(
            "batch_runner",
            PIPELINE_ROOT / "batch_runner.py",
            PINNED_SOURCE_SHA256["batch_runner.py"],
        )
        _import_pinned(
            "build_length_canary",
            PIPELINE_ROOT / "build_length_canary.py",
            PINNED_SOURCE_SHA256["build_length_canary.py"],
        )
        canary = _import_pinned(
            "automatic_canary_server",
            PIPELINE_ROOT / "automatic_canary_server.py",
            PINNED_SOURCE_SHA256["automatic_canary_server.py"],
        )
    finally:
        sys.dont_write_bytecode = previous_dont_write_bytecode
    if runner.MODEL_ID != MODEL_ID or canary.MODEL_ID != MODEL_ID:
        raise LocalModelError("SHARED_MODEL_ID_MISMATCH")
    if runner.SIMPLE_WORKFLOW_PROFILE != PROFILE_NAME:
        raise LocalModelError("SHARED_REQUEST_PROFILE_MISMATCH")
    return SharedModules(queue=queue, runner=runner, canary=canary)


def require_runtime_python(executable: str | Path | None = None) -> None:
    actual = Path(executable or sys.executable).resolve()
    if actual != RUNTIME_PYTHON.resolve():
        raise LocalModelError("PDF_RUNTIME_INTERPRETER_MISMATCH")


def build_request_material(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Read non-secret model/config identities and bind them to this schema."""
    if not isinstance(schema, Mapping) or schema.get("type") != "object":
        raise ValueError("PDF_REQUEST_SCHEMA_INVALID")
    modules = load_shared_modules()
    runner = modules.runner
    canary = modules.canary
    settings_path = Path(runner.OMLX_SETTINGS_PATH)
    model_settings_path = Path(runner.OMLX_MODEL_SETTINGS_PATH)
    if settings_path.is_symlink() or model_settings_path.is_symlink():
        raise LocalModelError("RUNTIME_SETTINGS_PATH_UNSAFE")
    try:
        settings_sha = sha256_file(settings_path)
        model_settings_sha = sha256_file(model_settings_path)
        runtime_limits = runner.load_runtime_limits()
        request_policy = canary._verified_simple_workflow_sampling_policy()
    except Exception as exc:
        raise LocalModelError("RUNTIME_BINDING_UNAVAILABLE") from exc
    schema_sha = sha256_bytes(canonical_json(dict(schema)))
    wrapper_sha = sha256_bytes(canonical_json({"json": dict(schema)}))
    material = {
        "model_id": MODEL_ID,
        "workflow_profile": PROFILE_NAME,
        "tools": [],
        "request_temperature": REQUEST_TEMPERATURE,
        "enable_thinking": ENABLE_THINKING,
        "request_schema_sha256": schema_sha,
        "request_schema_wrapper_sha256": wrapper_sha,
        "runtime_settings_sha256": settings_sha,
        "model_settings_sha256": model_settings_sha,
        "runtime_limits": runtime_limits,
        "max_completion_tokens": MAX_COMPLETION_TOKENS,
        "request_policy": request_policy,
    }
    return {
        **material,
        "configuration_sha256": sha256_bytes(canonical_json(material)),
        "runtime_settings_path": str(settings_path),
        "model_settings_path": str(model_settings_path),
        "runtime_python": str(RUNTIME_PYTHON.resolve()),
        "source_sha256": pinned_source_hashes(),
        "active_server_memory_settings": "CANNOT_CONFIRM",
        "evidence_root": str(PDF_EVIDENCE_ROOT),
    }


def verify_request_material(expected: Mapping[str, Any], observed: Mapping[str, Any]) -> None:
    fields = (
        "model_id",
        "workflow_profile",
        "tools",
        "request_temperature",
        "enable_thinking",
        "request_schema_sha256",
        "request_schema_wrapper_sha256",
        "runtime_settings_sha256",
        "model_settings_sha256",
        "runtime_limits",
        "max_completion_tokens",
        "request_policy",
        "configuration_sha256",
        "runtime_settings_path",
        "model_settings_path",
        "runtime_python",
        "source_sha256",
        "active_server_memory_settings",
        "evidence_root",
    )
    if not isinstance(expected, Mapping) or any(expected.get(key) != observed.get(key) for key in fields):
        raise LocalModelError("REQUEST_BINDING_MISMATCH")


def inspect_local_api_identity(*, api_key: str | None = None) -> dict[str, Any]:
    """Make one authenticated GET /v1/models request; never return its raw body."""
    modules = load_shared_modules()
    runner = modules.runner
    try:
        key = api_key if api_key is not None else runner.load_local_api_key()
        transport = runner.OmlxTransport(key, timeout_seconds=5.0)
        try:
            response = transport._client.get(
                runner.OMLX_BASE_URL + "/v1/models",
                headers=transport._headers(),
                timeout=5.0,
            )
            status_code = int(response.status_code)
            if status_code < 200 or status_code >= 300:
                return {
                    "status": "HTTP_UNAUTHORIZED" if status_code == 401 else "HTTP_ERROR",
                    "http_status": status_code,
                    "expected_model_id": MODEL_ID,
                    "model_ids": [],
                    "active_server_memory_settings": "CANNOT_CONFIRM",
                }
            payload = response.json()
        finally:
            transport.close()
    except Exception as exc:
        return {
            "status": "CANNOT_CONFIRM",
            "error_type": type(exc).__name__,
            "expected_model_id": MODEL_ID,
            "model_ids": [],
            "active_server_memory_settings": "CANNOT_CONFIRM",
        }
    rows = payload.get("data") if isinstance(payload, dict) else None
    model_ids = sorted(
        {
            row.get("id")
            for row in rows or []
            if isinstance(row, dict) and isinstance(row.get("id"), str)
        }
    )
    return {
        "status": "MATCH" if MODEL_ID in model_ids else "MODEL_ID_ABSENT",
        "http_status": status_code,
        "expected_model_id": MODEL_ID,
        "model_ids": model_ids,
        "active_server_memory_settings": "CANNOT_CONFIRM",
    }


def _no_lookup_transport_class(modules: SharedModules) -> type:
    class PdfNoLookupTransport(modules.canary.GatedStreamingTransport):
        def _call_simple_workflow_lookup(self, lookup_request: Any, on_event: Any) -> Any:
            del lookup_request, on_event
            raise PdfLookupForbidden("PDF_LOOKUP_FORBIDDEN")

    return PdfNoLookupTransport


def request_document_analysis(
    *,
    job: Any,
    messages: Sequence[Mapping[str, str]],
    schema: Mapping[str, Any],
    expected_binding: Mapping[str, Any],
    tool_context: Mapping[str, Any] | None = None,
    api_key: str | None = None,
    http_transport: Any | None = None,
) -> str:
    """Issue a pinned structured request, optionally running local PDF actions."""
    modules = load_shared_modules()
    observed = build_request_material(schema)
    evidence_root = Path(str(expected_binding.get("evidence_root", ""))).expanduser().absolute()
    if evidence_root.resolve(strict=False) != PDF_EVIDENCE_ROOT.resolve(strict=False):
        raise LocalModelError("PDF_EVIDENCE_ROOT_OUTSIDE_ALLOWLIST")
    verify_request_material(expected_binding, observed)
    runner = modules.runner
    key = api_key if api_key is not None else runner.load_local_api_key()
    transport_class = _no_lookup_transport_class(modules)
    transport = transport_class(
        key,
        evidence_root,
        expected_runtime_settings_sha256=str(expected_binding["runtime_settings_sha256"]),
        expected_model_settings_sha256=str(expected_binding["model_settings_sha256"]),
        runtime_settings_path=Path(expected_binding["runtime_settings_path"]),
        model_settings_path=Path(expected_binding["model_settings_path"]),
        http_transport=http_transport,
    )
    transport.begin_job(job)
    completion = None
    completions: list[Any] = []
    tool_receipts: list[dict[str, Any]] = []
    loop_started = time.monotonic()

    def request_turn(turn_messages: Sequence[Mapping[str, str]]) -> Any:
        result = transport.complete_batch(
            [dict(message) for message in turn_messages],
            tools=[],
            structured_outputs={"json": dict(schema)},
            workflow_profile=PROFILE_NAME,
        )
        if result.request_rounds != 1 or result.tool_receipts:
            raise LocalModelError("PDF_REQUEST_ROUND_OR_TOOL_POLICY_VIOLATION")
        completions.append(result)
        return result

    def aggregate_completion(final_text: str | None = None) -> Any:
        if not completions:
            return None
        first = completions[0]
        last = completions[-1]
        usage: dict[str, int] = {}
        for result in completions:
            for key, value in (result.usage or {}).items():
                if type(value) is int and value >= 0:
                    usage[key] = usage.get(key, 0) + value
        return SimpleNamespace(
            usage=usage,
            tool_receipts=list(tool_receipts),
            request_rounds=len(completions),
            started_at=first.started_at,
            finished_at=last.finished_at,
            wall_seconds=round(time.monotonic() - loop_started, 6),
            first_event_at=first.first_event_at,
            first_event_seconds=first.first_event_seconds,
            ttft_seconds=first.ttft_seconds,
            first_content_at=first.first_content_at,
            ttfc_seconds=first.ttfc_seconds,
            response_model=last.response_model,
            final_text_sha256=sha256_bytes((final_text or last.final_text).encode("utf-8")),
        )

    try:
        if tool_context is None:
            completion = request_turn(messages)
            transport.finish_job(status="SUCCEEDED", completion=completion)
            return completion.final_text

        from infrastructure import pdf_research_tools

        def web_call(name: str, arguments: Mapping[str, str]) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
            if name == "fetch_url":
                url = arguments.get("url")
                if not isinstance(url, str) or set(arguments) != {"url"}:
                    raise LocalModelError("PDF_WEB_TOOL_NOT_ALLOWED")
                return pdf_research_tools.fetch_public_official_url(url)
            if name != "web_search":
                raise LocalModelError("PDF_WEB_TOOL_NOT_ALLOWED")
            return modules.runner.OmlxTransport._call_web_tool(
                transport,
                name,
                dict(arguments),
                lambda _event: None,
            )

        action_result = pdf_research_tools.run_action_loop(
            messages,
            context=tool_context,
            response_schema=schema,
            request_turn=request_turn,
            web_call=web_call,
            on_tool_receipt=lambda receipt: tool_receipts.append(dict(receipt)),
        )
        final_text = canonical_json({"analysis_markdown": action_result["analysis_markdown"]}).decode("utf-8")
        transport._trace_meta["pdf_action_loop"] = {
            "status": "SUCCEEDED",
            "turns": action_result["turns"],
            "tool_actions": action_result["tool_actions"],
            "page_input_sha256": tool_context.get("page_input_sha256"),
        }
        transport.finish_job(status="SUCCEEDED", completion=aggregate_completion(final_text))
        return final_text
    except Exception as exc:
        code = getattr(exc, "code", None) or type(exc).__name__
        safe_code = str(code)[:96]
        if tool_context is not None:
            transport._trace_meta["pdf_action_loop"] = {
                "status": "FAILED",
                "failure_code": safe_code,
                "turns": len(completions),
                "tool_actions": len(tool_receipts),
                "page_input_sha256": tool_context.get("page_input_sha256"),
            }
        try:
            transport.finish_job(status="FAILED", code=safe_code, completion=aggregate_completion())
        except Exception:
            pass
        raise
    finally:
        transport.close()


class PdfCardTransportError(LocalModelError):
    def __init__(self, code: str, *, outcome_known: bool = False):
        super().__init__(code)
        self.outcome_known = outcome_known


def request_pdf_card(*, messages, schema, expected_binding, on_raw, on_progress,
                     on_dispatch=lambda: None, api_key=None, http_transport=None,
                     clock=time.monotonic) -> str:
    """One direct PDF-schema POST using the pinned shared authenticated client.

    The executor owns raw storage through callbacks. No announcement parser,
    queue, lookup envelope or external announcement source is changed.
    """
    require_runtime_python()
    observed = build_request_material(schema)
    verify_request_material(expected_binding, observed)
    modules = load_shared_modules()
    runner = modules.runner
    key = api_key if api_key is not None else runner.load_local_api_key()
    transport = runner.OmlxTransport(key, http_transport=http_transport)
    body = {'model': MODEL_ID, 'messages': [dict(m) for m in messages], 'stream': True,
            'stream_options': {'include_usage': True}, 'max_tokens': MAX_COMPLETION_TOKENS,
            'enable_thinking': ENABLE_THINKING, 'temperature': REQUEST_TEMPERATURE,
            'structured_outputs': {'json': dict(schema)}}
    import httpx
    last_progress = clock()
    answer, buffer, event_lines = [], b'', []
    finished = False
    saw_done = False

    def event(raw):
        nonlocal last_progress, finished, saw_done
        if raw.strip() == b'[DONE]':
            saw_done = True
            return
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError):
            raise PdfCardTransportError('PDF_STREAM_JSON_INVALID', outcome_known=True) from None
        if 'error' in value:
            error = value['error']
            code = error.get('code') if isinstance(error, dict) else None
            raise PdfCardTransportError('PDF_MODEL_ERROR:' + str(code or 'UNSPECIFIED')[:80], outcome_known=True)
        # Installed oMLX emits this reserved, content-free control frame before
        # prefill. Preserve its raw bytes, but neither treat it as model content
        # nor refresh the substantive-progress clock. Any extra payload falls
        # through to the normal strict error/model checks.
        if (value.get('model') == 'keepalive'
                and set(value) == {'id', 'object', 'created', 'model', 'choices'}
                and isinstance(value['id'], str) and value['id'].startswith('chatcmpl-')
                and value['object'] == 'chat.completion.chunk'
                and type(value['created']) is int and value['created'] == 0
                and isinstance(value['choices'], list) and len(value['choices']) == 1
                and value['choices'][0] == {'index': 0, 'delta': {'role': 'assistant', 'content': ''}, 'finish_reason': None}
                and type(value['choices'][0]['index']) is int):
            return
        if value.get('model') not in (None, MODEL_ID):
            raise PdfCardTransportError('PDF_RESPONSE_MODEL_ID_MISMATCH', outcome_known=True)
        for choice in value.get('choices', []):
            delta = choice.get('delta', {})
            if delta.get('tool_calls'):
                raise PdfCardTransportError('PDF_TOOL_REQUEST_FORBIDDEN', outcome_known=True)
            content = delta.get('content') or ''
            reasoning = delta.get('reasoning_content') or ''
            if not isinstance(content, str) or not isinstance(reasoning, str):
                raise PdfCardTransportError('PDF_STREAM_CONTENT_INVALID', outcome_known=True)
            if content or reasoning:
                last_progress = clock()
                on_progress({'kind': 'model_stream', 'characters': len(content) + len(reasoning)})
            if content:
                answer.append(content)
            reason = choice.get('finish_reason')
            if reason:
                if reason != 'stop':
                    raise PdfCardTransportError('PDF_COMPLETION_NOT_COMPLETE:' + str(reason), outcome_known=True)
                finished = True
    try:
        on_dispatch()
        with transport._client.stream('POST', transport._base_url + '/v1/chat/completions',
                headers=transport._headers(), json=body,
                timeout=httpx.Timeout(connect=10, read=90, write=30, pool=10)) as response:
            if not 200 <= response.status_code < 300:
                for block in response.iter_bytes():
                    on_raw(block)
                raise PdfCardTransportError('PDF_HTTP_STATUS:' + str(response.status_code), outcome_known=True)
            if response.headers.get('warning'):
                raise PdfCardTransportError('PDF_STRUCTURED_OUTPUT_WARNING', outcome_known=True)
            for block in response.iter_bytes():
                on_raw(block)
                if clock() - last_progress > 90:
                    raise PdfCardTransportError('PDF_TRANSPORT_NO_PROGRESS')
                buffer += block
                while b'\n' in buffer:
                    line, buffer = buffer.split(b'\n', 1)
                    line = line.rstrip(b'\r')
                    if line.startswith(b'data:'):
                        event_lines.append(line[5:].lstrip())
                    elif not line and event_lines:
                        event(b'\n'.join(event_lines))
                        event_lines = []
            if buffer.strip() or event_lines:
                raise PdfCardTransportError('PDF_STREAM_TRUNCATED')
        if not finished or not saw_done or not ''.join(answer).strip():
            raise PdfCardTransportError('PDF_STREAM_EOF_OUTCOME_UNCERTAIN')
        return ''.join(answer)
    except PdfCardTransportError:
        raise
    except httpx.TimeoutException:
        raise PdfCardTransportError('PDF_TRANSPORT_NO_PROGRESS') from None
    except Exception as exc:
        raise PdfCardTransportError('PDF_STREAM_INTERRUPTED:' + type(exc).__name__) from None
    finally:
        transport._client.close()


ANNOUNCEMENT_ROLES = {
    "announcement_reader",
    "announcement_reader_part",
    "announcement_reader_synthesis",
}


def pdf_priority_snapshot(path: Path | None = None) -> dict[str, Any]:
    from infrastructure import pdf_research
    state_path = path or (pdf_research.ANNOUNCEMENT_QUEUE_ROOT / "queue-state.json")
    try:
        if state_path.is_symlink() or not state_path.is_file():
            return {"status": "DEFER", "reason": "ANNOUNCEMENT_QUEUE_UNAVAILABLE"}
        before = state_path.stat()
        raw = state_path.read_bytes()
        after = state_path.stat()
        if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
            return {"status": "DEFER", "reason": "ANNOUNCEMENT_QUEUE_CHANGED_DURING_READ"}
        state = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {"status": "DEFER", "reason": "ANNOUNCEMENT_QUEUE_UNREADABLE"}
    if not isinstance(state, dict) or state.get("schema") != "v4.announcement-engine-queue/v1" or not isinstance(state.get("jobs"), dict):
        return {"status": "DEFER", "reason": "ANNOUNCEMENT_QUEUE_IDENTITY_UNCONFIRMED"}
    same_model_pending = 0
    for item in state["jobs"].values():
        if not isinstance(item, dict):
            return {"status": "DEFER", "reason": "ANNOUNCEMENT_JOB_IDENTITY_UNCONFIRMED"}
        status = item.get("status")
        if status in {"SUCCEEDED", "FAILED", "OVERSIZE", "MISSING_MATERIAL"}:
            continue
        if status not in {"PENDING", "RUNNING", "CLAIMED"}:
            return {"status": "DEFER", "reason": "ANNOUNCEMENT_JOB_STATUS_UNCONFIRMED"}
        model_id = item.get("model_id")
        if not isinstance(model_id, str) or not model_id.strip():
            return {"status": "DEFER", "reason": "ANNOUNCEMENT_JOB_IDENTITY_UNCONFIRMED"}
        if model_id != MODEL_ID:
            continue
        identity = item.get("identity")
        if not isinstance(identity, dict) or identity.get("role") not in ANNOUNCEMENT_ROLES:
            return {"status": "DEFER", "reason": "ANNOUNCEMENT_JOB_IDENTITY_UNCONFIRMED"}
        if status in {"RUNNING", "CLAIMED"}:
            return {"status": "DEFER", "reason": "SAME_MODEL_ANNOUNCEMENT_ACTIVE", "same_model_pending_count": same_model_pending}
        if status == "PENDING":
            same_model_pending += 1
    return {"status": "ALLOW", "same_model_pending_count": same_model_pending, "pending_is_advisory": True}
