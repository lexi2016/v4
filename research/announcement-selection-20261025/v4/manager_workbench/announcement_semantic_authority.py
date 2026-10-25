"""Read-only FIRST receipt binding under an explicit controller-owned descriptor.

This authenticates local custody and linked bytes, not business facts or a
cryptographic reviewer identity. Only the preassigned independent reviewer may
issue the post-response semantic verdict. No discovery, execution or publication
is performed here; missing authority never upgrades mechanical success.
"""
from __future__ import annotations

from copy import deepcopy
import ast
import builtins
import hashlib
import json
from pathlib import Path
import re
from types import SimpleNamespace

from .announcement_delivery import read as read_delivery
from .announcement_preprocessing import SEMANTIC_CONTRACT, SEMANTIC_CONTRACT_VERSION
from .engines.announcement import _validate_reader
from .engines import announcement as reader_contract

DESCRIPTOR_SCHEMA = "v4.manager_workbench.first_semantic_descriptor.v1"
PRE_RUN_SCHEMA = "v4.manager_workbench.first_semantic_pre_run.v1"
DISPATCH_SCHEMA = "v4.manager_workbench.first_semantic_dispatch.v1"
RECEIPT_SCHEMA = "v4.manager_workbench.first_semantic_acceptance.v1"
REGISTRATION_SCHEMA = "v4.manager_workbench.first_semantic_registration.v1"
_SHA = re.compile(r"^[0-9a-f]{64}$")
_IDENTITY = ("date", "market", "article_id", "source_sha256", "body_sha256", "prompt_sha256",
             "model_id", "configuration_sha256", "rules", "role", "stage")
_SELF = "v4/manager_workbench/announcement_semantic_authority.py"
_VALIDATOR = "v4/manager_workbench/engines/announcement.py"
_REQUIRED_CODE = {_SELF, _VALIDATOR, "v4/manager_workbench/announcement_preprocessing.py",
                  "ops/run_manager_flash_announcements.py", "v4/manager_workbench/announcement_update.py",
                  "v4/manager_workbench/announcement_test.py"}
_CAPTURE_LIMIT = 256 * 1024 * 1024
# Previously frozen genuine implementations, not hashes supplied by the receipt.
PURE_SOURCE_PINS = {
    "batch_runner.py": "0d0c09139223d738a4fb918212b0c7dce3bbd17cd8dbd8a2dc74c7a86ef865cb",
    "simple_fixed_facts.py": "f5b561b0f9be34b727df81b5002531bd955ce6e2b0949756c0b140d5ef2596a9",
    "build_length_canary.py": "d337b27e622b49ae38e0305dc729240901ce548d17f48c7b41776c9167f94a6d",
    "recent_day_freeze.py": "43f70a0e57f81814a93f176079bfc5c20519dbda5b7a8f9e8062e3aa488c74b3",
}


def _pure_functions(raw, name, seeds, dependencies=None):
    """Compile an exact original pure-function closure, never its entry point.

    Only four previously pinned source files are accepted. No module discovery,
    sys.path/sys.modules mutation, model import or CLI/prepare function occurs.
    """
    _require(name in PURE_SOURCE_PINS and _sha(raw) == PURE_SOURCE_PINS[name], "PURE_SOURCE_CHANGED")
    dependencies = dependencies or {}
    tree = ast.parse(raw, filename=name)
    definitions = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            definitions[node.name] = node
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for child in ast.walk(target):
                    if isinstance(child, ast.Name):
                        definitions[child.id] = node
    selected, loaded = set(), set(seeds)
    pending = list(seeds)
    while pending:
        symbol = pending.pop()
        node = definitions.get(symbol)
        if node is None or id(node) in selected:
            continue
        selected.add(id(node))
        runtime_node = deepcopy(node)
        # Postponed type annotations are not runtime dependencies. In
        # particular, do not execute the runner's unused dataclass executors.
        for child in ast.walk(runtime_node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                child.returns = None
            elif isinstance(child, ast.arg):
                child.annotation = None
            elif isinstance(child, ast.AnnAssign):
                child.annotation = ast.Constant(None)
        names = {n.id for n in ast.walk(runtime_node) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
        pending.extend(names - loaded)
        loaded.update(names)
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            nodes.append(node)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            aliases = [a for a in node.names if (a.asname or a.name.split(".")[0]) in loaded
                       and a.name not in dependencies]
            if aliases:
                copy = deepcopy(node); copy.names = aliases; nodes.append(copy)
        elif id(node) in selected:
            nodes.append(node)
    def original_import(module, globals=None, locals=None, fromlist=(), level=0):
        if module in dependencies:
            return dependencies[module]
        return builtins.__import__(module, globals, locals, fromlist, level)
    namespace = {"__name__": "first_authority_frozen_pure", "__file__": name,
                 "__builtins__": {**vars(builtins), "__import__": original_import}, **dependencies}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), name, "exec"), namespace)
    return SimpleNamespace(**namespace)


def load_pure_projection_sources(sources):
    """Exact existing builder/projector functions from explicit frozen bytes."""
    _require(set(sources) == set(PURE_SOURCE_PINS), "PURE_DEPENDENCIES_UNBOUND")
    facts = _pure_functions(sources["simple_fixed_facts.py"], "simple_fixed_facts.py", ["extract_fixed_facts", "PROTOCOL"])
    runner = _pure_functions(sources["batch_runner.py"], "batch_runner.py",
        ["build_source_unit_map", "build_messages", "build_simple_workflow_schema", "project_simple_workflow_output",
         "_validate_batch_output", "_validate_json_schema", "_simple_workflow_pit_provenance",
         "SIMPLE_WORKFLOW_RANGE_PROFILE", "SIMPLE_WORKFLOW_RANGE_CITATION_PROTOCOL"], {"simple_fixed_facts": facts})
    length = _pure_functions(sources["build_length_canary.py"], "build_length_canary.py", ["make_batch"], {"runner": runner, "batch_runner": runner})
    helper = _pure_functions(sources["recent_day_freeze.py"], "recent_day_freeze.py",
        ["_messages_for_article", "_recent_day_system_prompt"], {"batch_runner": runner, "build_length_canary": length})
    return runner, length, helper


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _require(condition, code):
    if not condition:
        raise ValueError("FIRST_AUTHORITY_" + code)


class FirstSemanticAuthority:
    """All roots, pre-run pins and consumer binding come from the trusted owner.

    The pre-run contract is sealed after genuine input/report preparation and
    before execution. Its hash is in the owner's frozen context, avoiding a
    self-hash cycle. Receipt/registration are later require-absent publications
    in the state root, never additions to the immutable source manifest.
    """
    def __init__(self, descriptor, *, state_io, capture_io, authority_io, code_io, context_binding):
        self.descriptor = deepcopy(descriptor)
        self.state, self.capture, self.authority, self.code = state_io, capture_io, authority_io, code_io
        self.context_binding = deepcopy(context_binding)
        _require(isinstance(descriptor, dict) and descriptor.get("schema") == DESCRIPTOR_SCHEMA, "DESCRIPTOR_INVALID")
        self.job_id = descriptor.get("job_id")
        _require(re.fullmatch(r"[0-9a-f]{32}", str(self.job_id)), "JOB_INVALID")
        _require(isinstance(context_binding, dict) and context_binding.get("run_id")
                 and all(_SHA.fullmatch(str(context_binding.get(k, "")))
                         for k in ("context_sha256", "source_manifest_sha256")), "CONTEXT_UNBOUND")

    @staticmethod
    def _read(io, ref):
        raw = io.read_bytes(ref)
        value = json.loads(raw)
        _require(isinstance(value, dict), "OBJECT_REQUIRED")
        return value, raw

    def _pinned(self, io, binding, *, kind="ordinary", expected_bytes=None):
        _require(isinstance(binding, dict) and _SHA.fullmatch(str(binding.get("sha256", ""))), "PIN_INVALID")
        if kind == "capture":
            _require(binding["artifact_ref"] == "products/" + binding["sha256"] + ".json"
                     and type(expected_bytes) is int and 0 < expected_bytes <= _CAPTURE_LIMIT, "CAPTURE_SIZE_UNBOUND")
            raw = io.read_bytes(binding["artifact_ref"], max_bytes=_CAPTURE_LIMIT)
            _require(len(raw) == expected_bytes, "CAPTURE_SIZE_CHANGED")
        else:
            _require(kind == "ordinary", "ARTIFACT_KIND_INVALID")
            raw = io.read_bytes(binding["artifact_ref"])
        _require(_sha(raw) == binding["sha256"], "PIN_CHANGED")
        value = json.loads(raw)
        _require(isinstance(value, dict), "OBJECT_REQUIRED")
        return value

    def _pre_run(self, prepared_io=None):
        d = self.descriptor
        c = self._pinned(self.authority, d["pre_run"])
        dispatch = self._pinned(self.authority, d["dispatch"])
        _require(c.get("schema") == PRE_RUN_SCHEMA and c.get("job_id") == self.job_id
                 and c.get("market") == "HK_CONNECT" and re.fullmatch(r"[0-9]{8}", str(c.get("target_date")))
                 and re.fullmatch(r"HK\.[0-9]{5}", str(c.get("symbol")))
                 and all(_SHA.fullmatch(str(c.get(k, ""))) for k in ("source_sha256", "body_sha256")), "PRE_RUN_INVALID")
        roots = {"state": self.state, "capture": self.capture, "authority": self.authority, "code": self.code}
        _require(c.get("roots") == {k: str(io.root) for k, io in roots.items()}, "ROOT_BINDING_CHANGED")
        _require(Path(__file__).resolve() == self.code.root / _SELF, "LOADED_CODE_CHANGED")
        _require(not any(self.state.root == io.root or self.state.root in io.root.parents or io.root in self.state.root.parents
                         for io in (self.capture, self.authority, self.code)), "ROOT_OVERLAP")
        ids = c["identities"]
        _require(isinstance(ids, dict) and all(isinstance(ids.get(k), str) and ids[k].strip() for k in
                     ("controller", "writer", "executor", "reviewer", "reviewer_execution_id"))
                 and ids["reviewer"] not in {ids["controller"], ids["writer"], ids["executor"]}, "REVIEWER_NOT_INDEPENDENT")
        _require(dispatch.get("schema") == DISPATCH_SCHEMA and dispatch.get("job_id") == self.job_id
                 and all(dispatch.get(k) == v for k, v in ids.items())
                 and dispatch.get("receipt_initially_absent") is True
                 and dispatch.get("registration_initially_absent") is True, "DISPATCH_CHANGED")
        _require(c.get("semantic_contract_version") == SEMANTIC_CONTRACT_VERSION
                 and c.get("semantic_contract_sha256") == _sha(SEMANTIC_CONTRACT.encode()), "POLICY_CHANGED")
        _require(c.get("budget") == {"expected_requests": 1, "max_attempts": 1, "prior_attempts": 0}
                 and all(type(v) is int for v in c["budget"].values()), "BUDGET_CHANGED")
        prefix = "announcement_flash/jobs/" + self.job_id
        _require(c.get("outputs") == {"receipt_ref": prefix + "/semantic-authority/receipt.json",
                 "registration_ref": prefix + "/semantic-authority/registration.json"}, "OUTPUT_NAMESPACE_CHANGED")
        codes = c["code_identity"]
        _require(isinstance(codes, dict) and _REQUIRED_CODE.issubset(codes), "CODE_UNBOUND")
        for ref, expected in codes.items():
            _require(_SHA.fullmatch(str(expected)) and _sha(self.code.read_bytes(ref)) == expected, "CODE_CHANGED")
        io = prepared_io if prepared_io is not None else self.state
        _require(c["input"]["artifact_ref"] == prefix + "/input.json"
                 and c["report"]["artifact_ref"] == prefix + "/preprocessing-report.json", "INPUT_REFERENCE_CHANGED")
        inp, report = self._pinned(io, c["input"]), self._pinned(io, c["report"])
        _require(all(v.get("job_id") == self.job_id and v.get("target_date") == c["target_date"] for v in (inp, report))
                 and report.get("schema") == "v4.manager_workbench.announcement_preprocessing.v1"
                 and report.get("accounting_closed") is True and report.get("capture_product") == c["capture"], "INPUT_REPORT_CHANGED")
        entries = report["execution_manifest"]
        _require(isinstance(entries, list) and len(entries) == 1 and report.get("first_article_id") == c["article_id"]
                 and all(type(report["counts"].get(k)) is int for k in ("expected_model_requests", "model_required_articles"))
                 and report["counts"]["expected_model_requests"] == report["counts"]["model_required_articles"] == 1,
                 "FIRST_SCOPE_CHANGED")
        expected = {k: c[k] for k in ("article_id", "source_sha256", "body_sha256", "symbol")}
        _require(all(entries[0].get(k) == v for k, v in expected.items())
                 and entries[0].get("primary_disposition") == "MODEL_ORDINARY"
                 and type(entries[0].get("part_count")) is int and type(entries[0].get("expected_requests")) is int
                 and entries[0].get("part_count") == 0 and entries[0].get("expected_requests") == 1
                 and any(all(e.get(k) == v for k, v in expected.items()) for e in report["catalogue"]), "ARTICLE_SCOPE_CHANGED")
        _require(type(c["capture_row_index"]) is int, "CAPTURE_ROW_INVALID")
        capture = self._pinned(self.capture, c["capture"], kind="capture", expected_bytes=c["capture_sizes"]["capture"])
        row = capture["rows"][c["capture_row_index"]]
        origin_ref = c["capture_origin"]
        _require(type(origin_ref["row_index"]) is int, "CAPTURE_ORIGIN_ROW_INVALID")
        origin = self._pinned(self.capture, origin_ref, kind="capture", expected_bytes=c["capture_sizes"]["origin"])
        _require(row == origin["rows"][origin_ref["row_index"]], "CAPTURE_ORIGIN_CHANGED")
        source = self._pinned(self.capture, c["source"])
        body = source["body_text"]
        _require(c["source"]["sha256"] == c["source_sha256"] == row.get("source_sha256")
                 and row.get("body_artifact_ref") == c["source"]["artifact_ref"]
                 and source.get("body_complete") is True and row.get("body_complete") is True
                 and source.get("body_text_sha256") == c["body_sha256"] == row.get("body_text_sha256")
                 and isinstance(body, str) and body and row.get("body_text") == body
                 and _sha(body.encode()) == c["body_sha256"]
                 and c["article_id"].rsplit(":", 1)[-1] == row.get("art_code")
                 and {i.get("code") for i in row["source_issuer_codes"]} == {c["symbol"]}, "SOURCE_CHANGED")
        _require(isinstance(c["source_objects"], list) and c["source_objects"], "SOURCE_OBJECTS_UNBOUND")
        for binding in c["source_objects"]:
            _require(_SHA.fullmatch(str(binding.get("sha256", "")))
                     and _sha(self.capture.read_bytes(binding["artifact_ref"])) == binding["sha256"], "SOURCE_OBJECT_CHANGED")
        material = self._pinned(self.authority, c["request_material"])
        config = material["configuration_material"]
        _require(isinstance(config, dict) and _sha(_encoded(config)) == material["configuration_sha256"],
                 "REQUEST_CONFIGURATION_CHANGED")
        # The original producer has no top-level model/completion aliases. Its
        # authenticated configuration is authoritative; aliases cannot replace
        # missing configuration or override it.
        _require(config.get("model_id") == "qwen3_8_flash_next"
                 and type(config.get("max_completion_tokens")) is int
                 and config["max_completion_tokens"] == 32768
                 and all(k not in material or (type(material[k]) is type(config[k]) and material[k] == config[k])
                         for k in ("model_id", "max_completion_tokens"))
                 and _encoded(config["runtime_limits"]) == _encoded(material["runtime_limits"])
                 and type(config["runtime_limits"].get("completion_max_tokens")) is int
                 and config["runtime_limits"]["completion_max_tokens"] == config["max_completion_tokens"]
                 and all(config.get(k) == material[k] for k in ("runtime_settings_sha256", "model_settings_sha256"))
                 and config["runtime_limits"].get("model_settings_sha256") == material["model_settings_sha256"],
                 "REQUEST_EFFECTIVE_IDENTITY_CHANGED")
        _require(_sha(material["prompt"].encode()) == material["prompt_sha256"]
                 and SEMANTIC_CONTRACT in material["prompt"]
                 and config.get("semantic_contract_version") == SEMANTIC_CONTRACT_VERSION
                 and config.get("validation_contract_sha256") == codes[_VALIDATOR] == material["validation_contract_sha256"]
                 and config.get("system_prompt_sha256") == material["prompt_sha256"]
                 and config.get("base_prompt_sha256") == _sha(material["prompt"].removesuffix("\n\n" + SEMANTIC_CONTRACT).encode())
                 and config.get("request_temperature") == 0.0 and config.get("enable_thinking") is False
                 and config.get("request_policy") == material["sampling_policy"]
                 and _sha(_encoded(material["sampling_policy"])) == material["sampling_policy_sha256"]
                 and _sha(_encoded(material["schema"])) == material["schema_sha256"] == config.get("request_schema_sha256")
                 and _sha(_encoded({"json": material["schema"]})) == material["schema_wrapper_sha256"]
                    == config.get("request_schema_wrapper_sha256"), "REQUEST_CONTRACT_CHANGED")
        # Preserve the original report contract verbatim, including its None
        # top-level completion value for the genuine original-shaped envelope.
        from ops.run_manager_flash_announcements import _classification_contract
        expected_processing = _classification_contract(material, SimpleNamespace(MODEL_ID=config["model_id"]))
        _require(_encoded(report["processing_contract"]) == _encoded(expected_processing), "PROCESSING_CONTRACT_CHANGED")
        _require(inp.get("capture_product") == c["capture"], "INPUT_CAPTURE_CHANGED")
        sources = {}
        _require(set(c["projection_sources"]) == set(PURE_SOURCE_PINS), "PURE_DEPENDENCIES_UNBOUND")
        for name, binding in c["projection_sources"].items():
            _require(binding.get("sha256") == PURE_SOURCE_PINS[name], "PURE_SOURCE_IDENTITY_CHANGED")
            sources[name] = self.authority.read_bytes(binding["artifact_ref"])
        runner, length, helper = load_pure_projection_sources(sources)
        _require(material["source_code_sha256"].get("batch_runner.py") == PURE_SOURCE_PINS["batch_runner.py"]
                 and material["source_code_sha256"].get("recent_day_freeze.py") == PURE_SOURCE_PINS["recent_day_freeze.py"]
                 and material.get("parser_sha256") == PURE_SOURCE_PINS["simple_fixed_facts.py"]
                 and material["source_code_sha256"].get(_VALIDATOR) == codes[_VALIDATOR], "EXECUTION_PURE_DEPENDENCIES_CHANGED")
        contract = SimpleNamespace(reader_schema=reader_contract.READER_SCHEMA, read_prompt=reader_contract.READ_PROMPT,
            prompt_version=reader_contract.PROMPT_VERSION, validate_reader=_validate_reader, source_sha256=codes[_VALIDATOR])
        profile, citation = runner.SIMPLE_WORKFLOW_RANGE_PROFILE, runner.SIMPLE_WORKFLOW_RANGE_CITATION_PROTOCOL
        _require(material["schema"] == runner.build_simple_workflow_schema(contract, citation)
                 and material["prompt"] == helper._recent_day_system_prompt(contract, profile) + "\n\n" + SEMANTIC_CONTRACT,
                 "ORIGINAL_WIRE_CONTRACT_CHANGED")
        # This existing pure source-reader does not create a report, queue or job.
        from ops.run_manager_flash_announcements import _source_article
        article = _source_article(row, c["capture_row_index"], capture, c["capture"], self.capture, runner, inp["membership_gate"])
        unit_map = runner.build_source_unit_map(body, c["body_sha256"])
        article["fixed_fact_ledger"] = runner.simple_fixed_facts.extract_fixed_facts(body, unit_map, article["article_metadata"])
        batch = length.make_batch([article], "V4_FLASH_" + _sha(c["article_id"].encode())[:16])
        messages = helper._messages_for_article(article, contract, material["prompt"], profile)
        _require(c["projection_pit_annotation"] == runner._simple_workflow_pit_provenance(article)["annotation"], "PIT_PROJECTION_CHANGED")
        return c, material, body, (runner, contract, article, batch, messages, unit_map)

    def preflight(self, *, prepared_io=None):
        """Owner calls before dispatch; verifies absent output slots and no reset.

        prepared_io may be the frozen source state before its lossless copy into
        isolated runtime state. It never supplies a post-run result or receipt.
        """
        try:
            c, _, _, _ = self._pre_run(prepared_io)
            for ref in c["outputs"].values():
                try:
                    self.state.read_bytes(ref)
                except FileNotFoundError:
                    continue
                raise ValueError("FIRST_AUTHORITY_ALREADY_REVIEWED_OR_REGISTERED")
            try:
                queue, _ = self._read(self.state, "announcement_flash/queue/queue-state.json")
            except FileNotFoundError:
                queue = {"jobs": {}}
            _require(not any(j.get("identity", {}).get("article_id") == c["article_id"]
                             and j.get("identity", {}).get("body_sha256") == c["body_sha256"]
                             for j in queue["jobs"].values()), "ALREADY_ATTEMPTED")
        except (OSError, KeyError, TypeError, IndexError, AttributeError) as exc:
            raise ValueError("FIRST_AUTHORITY_PREFLIGHT_EVIDENCE_INVALID") from exc

    def _actual(self, c, material, body, prepared):
        runner, contract, article, batch, messages, unit_map = prepared
        queue, _ = self._read(self.state, "announcement_flash/queue/queue-state.json")
        matching = [(k, j) for k, j in queue["jobs"].items() if j.get("identity", {}).get("article_id") == c["article_id"]
                    and j.get("identity", {}).get("body_sha256") == c["body_sha256"]]
        _require(len(matching) == 1, "QUEUE_SCOPE_CHANGED")
        key, item = matching[0]
        _require(item.get("idempotency_key") == key and item.get("status") == "SUCCEEDED"
                 and type(item.get("attempt_count")) is int and type(item.get("max_attempts")) is int
                 and item.get("attempt_count") == item.get("max_attempts") == 1 and len(item["attempts"]) == 1
                 and type(item["attempts"][0].get("number")) is int
                 and item["attempts"][0].get("number") == 1 and item["attempts"][0].get("status") == "SUCCEEDED", "ATTEMPT_CHANGED")
        refs = {"input_path": f"jobs/{key}/input.json", "raw_path": f"jobs/{key}/attempt-0001.raw",
                "validated_path": f"jobs/{key}/attempt-0001.validated.json"}
        _require(all(item.get(k) == v for k, v in refs.items()), "QUEUE_REFERENCE_CHANGED")
        payload = self._pinned(self.state, {"artifact_ref": "announcement_flash/queue/" + refs["input_path"], "sha256": item["payload_sha256"]})
        _require(item["identity"] == {k: payload.get(k) for k in _IDENTITY}
                 and _sha(_encoded(item["identity"])) == key, "QUEUE_IDENTITY_CHANGED")
        _require(all(payload.get(k) == c[k] for k in ("article_id", "source_sha256", "body_sha256"))
                 and all(payload.get(k) == material[k] for k in ("prompt_sha256", "configuration_sha256"))
                 and payload.get("model_id") == material["configuration_material"]["model_id"]
                 and payload.get("market") == "HK" and payload.get("article_body") == body
                 and payload["article_metadata"].get("symbol") == c["symbol"]
                 and payload["article_metadata"] == article["article_metadata"]
                 and payload.get("fixed_fact_ledger") == article["fixed_fact_ledger"]
                 and payload.get("validated_article_batch") == batch
                 and payload.get("source_unit_map_sha256") == unit_map["source_unit_map_sha256"]
                 and payload.get("messages") == messages
                 and payload.get("bounded_execution") == {"job_id": self.job_id, "report_sha256": c["report"]["sha256"]}
                 and not any(k in payload for k in ("execution_extension_sha256", "semantic_recovery_of", "recovery_of")), "PAYLOAD_CHANGED")
        raw = self.state.read_bytes("announcement_flash/queue/" + refs["raw_path"])
        result = self._pinned(self.state, {"artifact_ref": "announcement_flash/queue/" + refs["validated_path"], "sha256": item["validated_sha256"]})
        _require(_sha(raw) == item["raw_sha256"] and all(item["attempts"][0].get(k) == item[k]
                 for k in ("raw_sha256", "validated_sha256")), "RESULT_SHA_CHANGED")
        wire = json.loads(raw)
        _require(wire.get("action") == "complete" and wire.get("lookup_request") is None
                 and len(result["results"]) == 1 and result["results"][0].get("article_id") == c["article_id"], "RESULT_SCOPE_CHANGED")
        reader = result["results"][0]["reader_output"]
        raw_reader = wire["reader_output"]
        projected, _ = runner.project_simple_workflow_output(wire, batch, contract,
            expected_source_unit_map_sha256_by_article={c["article_id"]: unit_map["source_unit_map_sha256"]},
            citation_protocol=runner.SIMPLE_WORKFLOW_RANGE_CITATION_PROTOCOL, preserve_model_changes=True)
        valid, errors = runner._validate_batch_output(_encoded(projected).decode(), batch, contract)
        _require(not errors and set(valid) == {c["article_id"]}
                 and _encoded(projected) == self.state.read_bytes("announcement_flash/queue/" + refs["validated_path"]),
                 "APPROVED_PROJECTION_CHANGED")
        _validate_reader(body, c, reader)
        _require(all(reader.get(k) == raw_reader.get(k) for k in
                     ("disposition", "selection_basis", "direction", "evidence_sufficiency", "reason"))
                 and all(reader.get(k) == c[k] for k in ("source_sha256", "body_sha256"))
                 and reader["risk_notes"] == raw_reader["risk_notes"] + [c["projection_pit_annotation"]], "MODEL_JUDGMENT_CHANGED")
        normalize = lambda text: re.sub(r"\s+", "", text)
        _require(all(isinstance(note, str) and normalize(note) and normalize(note) in normalize(body)
                     for note in raw_reader["risk_notes"]), "RISK_EXTRACT_CHANGED")
        for field in ("changes", "impact", "confirmation_conditions", "counter_evidence"):
            _require([e["claim"] for e in reader[field]] == [e["claim"] for e in raw_reader[field]], "MODEL_CLAIM_CHANGED")
        for field in ("facts", "changes", "impact", "confirmation_conditions", "counter_evidence"):
            for evidence in reader[field]:
                match = re.fullmatch(r"article_body\[codepoint:(\d+):(\d+)\]", evidence["locator"])
                _require(match and 0 <= int(match[1]) < int(match[2]) <= len(body)
                         and body[int(match[1]):int(match[2])] == evidence["quote"], "SOURCE_QUOTE_CHANGED")
        trace = f"announcement_flash/evidence/streams/{key}/attempt-0001/"
        request, request_raw = self._read(self.state, trace + "round-01.request-input.json")
        stream, stream_raw = self._read(self.state, trace + "stream-receipt.json")
        sse = self.state.read_bytes(trace + "round-01.raw.sse")
        expected_request = {"model": material["configuration_material"]["model_id"], "messages": messages, "stream": True,
            "stream_options": {"include_usage": True}, "max_tokens": material["configuration_material"]["max_completion_tokens"],
            "structured_outputs": {"json": material["schema"]}, "enable_thinking": False, "temperature": 0.0}
        _require(_encoded(request) == _encoded(expected_request), "ORIGINAL_REQUEST_WIRE_CHANGED")
        _require(request.get("messages") == payload.get("messages")
                 and request.get("structured_outputs") == {"json": payload["structured_output_schema"]}
                 and payload["structured_output_schema"] == material["schema"]
                 and payload["messages"][0].get("content") == material["prompt"]
                 and request.get("model") == material["configuration_material"]["model_id"] and request.get("temperature") == 0.0
                 and request.get("enable_thinking") is False and request.get("stream") is True
                 and request.get("max_tokens") == material["configuration_material"]["max_completion_tokens"], "ACTUAL_REQUEST_CHANGED")
        _require(stream.get("idempotency_key") == key and type(stream.get("attempt")) is int and stream.get("attempt") == 1
                 and stream.get("model_id") == material["configuration_material"]["model_id"] and stream.get("status") == "RESPONSE_RECEIVED"
                 and type(stream.get("request_rounds")) is int and stream.get("request_rounds") == 1
                 and len(stream["rounds"]) == 1 and stream.get("tool_receipts") == []
                 and type(stream["rounds"][0].get("round")) is int and stream["rounds"][0].get("round") == 1
                 and stream.get("final_text_sha256") == _sha(raw)
                 and stream["rounds"][0].get("request_input_sha256") == _sha(request_raw)
                 and stream["rounds"][0].get("raw_sse_sha256") == _sha(sse)
                 and all(stream.get(k) == material[k] and stream.get(k + "_status") == "MATCH"
                         for k in ("runtime_settings_sha256", "model_settings_sha256")), "STREAM_BINDING_CHANGED")
        text, done = [], False
        for line in sse.decode().splitlines():
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                done = True
                continue
            event = json.loads(data)
            for choice in event.get("choices", []):
                content = choice.get("delta", {}).get("content")
                if isinstance(content, str):
                    text.append(content)
        _require(done and "".join(text).encode() == raw, "RAW_STREAM_CHANGED")
        delivered, binding = read_delivery(self.state, self.job_id)
        _require(delivered and delivered.get("target_trade_date") == c["target_date"]
                 and delivered.get("preprocessing_report_sha256") == c["report"]["sha256"]
                 and delivered.get("capture_product") == c["capture"] and len(delivered["articles"]) == 1, "DELIVERY_CHANGED")
        article = delivered["articles"][0]
        _require(all(article.get(k) == c[k] for k in ("article_id", "source_sha256", "body_sha256", "symbol"))
                 and article.get("queue_key") == key and article.get("result_sha256") == item["validated_sha256"]
                 and article.get("result_ref") == item["validated_path"] and article.get("state") == "SUCCEEDED"
                 and article.get("source_coverage") == "COMPLETE_ARTICLE"
                 and all(article.get(k) == reader[k] for k in ("disposition", "direction", "selection_basis", "reason")), "DELIVERY_RESULT_CHANGED")
        return {"queue_key": key, "payload_sha256": item["payload_sha256"], "raw_sha256": _sha(raw),
                "validated_sha256": item["validated_sha256"], "request_sha256": _sha(request_raw),
                "stream_sha256": _sha(stream_raw), "sse_sha256": _sha(sse), "delivery_sha256": binding["sha256"]}

    def __call__(self, job_id, report_sha256):
        pending = {"job_id": job_id, "report_sha256": report_sha256, "eligible": False,
                   "status": "BLOCKED", "checkpoint_state": None, "semantic_review_sha256": None,
                   "quarantined_results": [], "reason": "FIRST_SEMANTIC_AUTHORITY_UNREVIEWED"}
        try:
            _require(job_id == self.job_id, "CONSUMER_JOB_CHANGED")
            c, material, body, prepared = self._pre_run()
            _require(report_sha256 == c["report"]["sha256"], "CONSUMER_REPORT_CHANGED")
            try:
                registration, _ = self._read(self.state, c["outputs"]["registration_ref"])
            except FileNotFoundError:
                return pending
            _require(registration.get("schema") == REGISTRATION_SCHEMA
                     and registration.get("job_id") == self.job_id
                     and registration.get("controller") == c["identities"]["controller"]
                     and registration.get("pre_run_sha256") == self.descriptor["pre_run"]["sha256"]
                     and registration.get("context_binding") == self.context_binding
                     and registration.get("receipt_ref") == c["outputs"]["receipt_ref"], "REGISTRATION_CHANGED")
            receipt = self._pinned(self.state, {"artifact_ref": registration["receipt_ref"], "sha256": registration["receipt_sha256"]})
            actual = self._actual(c, material, body, prepared)
            expected = {"schema": RECEIPT_SCHEMA, "pre_run_sha256": self.descriptor["pre_run"]["sha256"],
                "dispatch_sha256": self.descriptor["dispatch"]["sha256"], "context_binding": self.context_binding,
                "job_id": job_id, "target_date": c["target_date"], "market": c["market"],
                "reviewer": c["identities"]["reviewer"], "reviewer_execution_id": c["identities"]["reviewer_execution_id"],
                "actual_calls": 1, "input_sha256": c["input"]["sha256"], "report_sha256": report_sha256,
                "capture_sha256": c["capture"]["sha256"],
                **{k: c[k] for k in ("article_id", "source_sha256", "body_sha256", "symbol")}, **actual}
            _require(all(receipt.get(k) == v for k, v in expected.items())
                     and type(receipt.get("actual_calls")) is int, "RECEIPT_BINDING_CHANGED")
            _require(receipt.get("verdict") in {"PASS", "FAIL", "CANNOT_CONFIRM"}
                     and receipt.get("source_faithfulness") in {"PASS", "FAIL", "CANNOT_CONFIRM"}, "VERDICT_INVALID")
            accepted = receipt["verdict"] == receipt["source_faithfulness"] == "PASS"
            return {**pending, "target_date": c["target_date"], "delivery_sha256": actual["delivery_sha256"],
                "checkpoint_state": "SUCCEEDED" if accepted else "SEMANTIC_REVIEW_FAILED",
                "semantic_review_sha256": registration["receipt_sha256"],
                "reason": None if accepted else "FIRST_INDEPENDENT_SEMANTIC_REVIEW_NOT_PASSED",
                "quarantined_results": [] if accepted else [{"queue_key": actual["queue_key"], "result_sha256": actual["validated_sha256"]}]}
        except (OSError, KeyError, TypeError, IndexError, AttributeError) as exc:
            raise ValueError("FIRST_AUTHORITY_EVIDENCE_INVALID") from exc
