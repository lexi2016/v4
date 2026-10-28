"""Fail-closed provenance checks for the fixed V4 executor registry.

The runtime catalog describes workload identity.  This module verifies the
separate executable owner in ``FixedExecutorRegistry`` without importing or
running it.  The governance audit consumes the resulting snapshot; it must
never promote a catalog command merely because its module happens to exist.
"""
from __future__ import annotations

import ast
import hashlib
import stat
from pathlib import Path
from typing import Any, Mapping

from ops.migration.runtime_execution_ast import (
    canonical_catalog_command as _canonical_catalog_command,
    catalog_matches_handler as _catalog_matches_handler,
    direct_run_calls as _direct_run_calls,
    frozen_executor_contract_matches as _frozen_executor_contract_matches,
)


def _catalog_command(module: str, *arguments: str) -> tuple[str, ...]:
    return ("python", "-m", module, *arguments)


SPECIAL_EXECUTOR_CATALOG_COMMANDS = {
    "morning_news_0830": _catalog_command(
        "scripts.run_scheduled_morning_news",
        "--trade-date", "{business_date}",
    ),
    "zsxq_0830": _catalog_command(
        "ops.run_zsxq_0830",
        "--data-root", "{data_root}",
        "--date", "{business_date}",
        "--slot", "{slot}",
    ),
}
_REGISTRY_FACADE_PATH = Path("infrastructure/scheduling/executor_registry.py")
_REGISTRY_CHILD_SPECS = (
    (Path("infrastructure/scheduling/executor_registry_common.py"), "infrastructure.scheduling.executor_registry_common",
     ("_audited_peripheral_degradation", "_audited_peripheral_timeout_reuse", "_bounded", "_collector_not_materialized_result", "_default_runner")),
    (Path("infrastructure/scheduling/executor_registry_research.py"), "infrastructure.scheduling.executor_registry_research",
     ("_hourly_research", "_us_market_digest", "_zsxq_0830", "_morning_news_0830", "_research_preselection_refresh", "_baimao_x_refresh", "_stage_workbench", "_hk_auction_0920")),
    (Path("infrastructure/scheduling/executor_registry_preselection.py"), "infrastructure.scheduling.executor_registry_preselection",
     ("_verified_formal_pool_reuse", "_preselection_pools")),
    (Path("infrastructure/scheduling/executor_registry_review.py"), "infrastructure.scheduling.executor_registry_review",
     ("_daily_materialize", "_decoded_stdout", "_safe_lane_status", "_research_panel_runtime_evidence", "_research_panel_daily", "_wechat_preselection_sync", "_review_core_pool_pipeline", "_run_stage_center_milestone", "_run_close_review_node", "_a_share_close_review", "_hk_connect_close_review")),
)
_COMMON_HELPERS = frozenset(_REGISTRY_CHILD_SPECS[0][2])
_REGISTRY_FACADE_METHODS = frozenset({"__init__", "_hk_0_2_runtime_error", "_run", "_failure_result", "__call__"})
_REGISTRY_MOVED_METHODS = frozenset(name for _path, _module, names in _REGISTRY_CHILD_SPECS for name in names)
_REGISTRY_METHOD_OWNER = {name: module for _path, module, names in _REGISTRY_CHILD_SPECS for name in names if name not in _COMMON_HELPERS}
def _safe_repo_path(repo_root: Path, relative: Path) -> Path | None:
    root = Path(repo_root).absolute()
    if root.is_symlink() or root.resolve(strict=False) != root:
        return None
    relative = Path(relative)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        return None
    candidate = root
    for part in relative.parts:
        candidate /= part
        try:
            if candidate.is_symlink():
                return None
        except OSError:
            return None
    try:
        candidate.resolve(strict=False).relative_to(root)
    except (OSError, ValueError):
        return None
    return candidate
def _module_file(module: str, repo_root: Path) -> Path | None:
    if not isinstance(module, str) or not module or any(not part or part in {".", ".."} for part in module.split(".")) or "/" in module or "\\" in module:
        return None
    return _safe_repo_path(repo_root, Path(*module.split(".")).with_suffix(".py"))
def _runner_module_present(command: Any, repo_root: Path) -> bool:
    return (
        isinstance(command, list) and len(command) >= 3 and command[:2] == ["python", "-m"]
        and isinstance(command[2], str)
        and (path := _module_file(command[2], Path(repo_root))) is not None
        and path.is_file() and not path.is_symlink()
    )
def _runner_contract_complete(command: Any) -> bool:
    contracts = {
        "ops.run_hkconnect_0915_0920_capture": ["--data-root", "{data_root}", "--shared-data-root", "{shared_data_root}", "--shared-package-root", "{shared_package_root}", "--trade-date", "{business_date}", "--futu-python", "{shared_futu_python}"],
        "ops.run_hourly_research": ["--data-root", "{data_root}", "--date", "{business_date}", "--target-date", "{target_date}", "--slot", "{slot}", "--mode", "{mode}"],
        "ops.build_close_review": ["--data-root", "{data_root}", "--date", "{business_date}"],
        "ops.materialize_preselection": ["--trade-date", "{business_date}", "--selector", "{selector_panel}", "--fupan", "{fupan_pool}", "--stage7", "{stage7_pool}", "--research-preview", "{research_preview}", "--hk", "{hk_pool}", "--wechat-rows", "{wechat_rows}", "--wechat-manifest", "{wechat_manifest}"],
        "ops.materialize_stage_workbench": ["--data-root", "{data_root}", "--date", "{business_date}", "--stage", "{stage_id}"],
        "ops.build_a_share_close_review": ["--data-root", "{data_root}", "--date", "{business_date}", "--panel-pointer", "{panel_pointer}"],
        "ops.run_zsxq_0830": ["--data-root", "{data_root}", "--date", "{business_date}", "--slot", "{slot}"],
    }
    return isinstance(command, list) and len(command) >= 3 and isinstance(command[2], str) and command[3:] == contracts.get(command[2])
def _runner_command_complete(command: Any, repo_root: Path, workload_id: str | None = None) -> bool:
    if not _runner_module_present(command, repo_root):
        return False
    if workload_id in SPECIAL_EXECUTOR_CATALOG_COMMANDS:
        return False
    return _regular_executor_provenance(workload_id, command, repo_root) is not None if workload_id is not None else _runner_contract_complete(command)
def _registry_imports_are_legal(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names = ("." * node.level + (node.module or "") + "." + alias.name for alias in node.names)
        else:
            continue
        if any("executor_registry" in name.replace("-", "_") for name in names):
            return False
    return True
def _registry_source_bundle(repo_root: Path) -> tuple[str, str] | None:
    root = Path(repo_root)
    specs = ((_REGISTRY_FACADE_PATH, ()),) + tuple((path, names) for path, _module, names in _REGISTRY_CHILD_SPECS)
    sources: dict[Path, tuple[bytes, ast.Module]] = {}
    for relative, expected_names in specs:
        path = _safe_repo_path(root, relative)
        if path is None or not path.is_file() or path.is_symlink():
            return None
        try:
            raw = path.read_bytes()
            tree = ast.parse(raw.decode("utf-8"), filename=str(relative))
        except (OSError, UnicodeError, SyntaxError):
            return None
        if relative != _REGISTRY_FACADE_PATH and not _registry_imports_are_legal(tree):
            return None
        sources[relative] = (raw, tree)
    facade_tree = sources[_REGISTRY_FACADE_PATH][1]
    classes = [node for node in facade_tree.body if isinstance(node, ast.ClassDef) and node.name == "FixedExecutorRegistry"]
    if len(classes) != 1:
        return None
    if any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in _REGISTRY_MOVED_METHODS for node in facade_tree.body):
        return None
    registry_class = classes[0]
    class_methods = [node.name for node in registry_class.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if set(class_methods) != _REGISTRY_FACADE_METHODS or len(class_methods) != len(set(class_methods)) or set(class_methods) & _REGISTRY_MOVED_METHODS:
        return None
    imported_children = {alias.name for node in facade_tree.body if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module is None for alias in node.names}
    if {path.stem for path, _module, _names in _REGISTRY_CHILD_SPECS} - imported_children:
        return None
    child_methods: list[ast.FunctionDef] = []
    for relative, expected_names in specs[1:]:
        definitions = [node for node in sources[relative][1].body if isinstance(node, ast.FunctionDef)]
        if len(definitions) != len(expected_names) or {node.name for node in definitions} != set(expected_names) or len({node.name for node in definitions}) != len(definitions):
            return None
        child_methods.extend(next(node for node in definitions if node.name == name) for name in expected_names if name not in _COMMON_HELPERS)
    registry_class.body.extend(child_methods)
    try:
        synthetic = ast.unparse(facade_tree)
    except (AttributeError, RecursionError, ValueError):
        return None
    digest = hashlib.sha256()
    for relative, (raw, _tree) in sorted(sources.items(), key=lambda item: item[0].as_posix()):
        tag = relative.as_posix().encode("utf-8")
        digest.update(len(tag).to_bytes(4, "big")); digest.update(tag)
        digest.update(len(raw).to_bytes(8, "big")); digest.update(raw)
    return synthetic, digest.hexdigest()
def _read_registry_source_with_sha(repo_root: Path) -> tuple[str | None, str | None]:
    bundle = _registry_source_bundle(Path(repo_root))
    return bundle if bundle is not None else (None, None)
def _registry_tree(source: str) -> ast.Module | None:
    try:
        return ast.parse(source)
    except SyntaxError:
        return None
def _registry_class(source: str) -> ast.ClassDef | None:
    tree = _registry_tree(source)
    if tree is None:
        return None
    matches = [
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "FixedExecutorRegistry"
    ]
    # Python binds a duplicate top-level class to the last definition; fail closed.
    return matches[0] if len(matches) == 1 else None
def _registry_method(source: str, method_name: str) -> ast.FunctionDef | None:
    # Python binds duplicate class-body handlers to the last one; fail closed.
    registry_class = _registry_class(source)
    if registry_class is None:
        return None
    matches = [
        child
        for child in registry_class.body
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
        and child.name == method_name
    ]
    return matches[0] if len(matches) == 1 else None
def _ast_matches(node: ast.AST, expression: str) -> bool:
    try:
        expected = ast.parse(expression, mode="eval").body
    except SyntaxError:
        return False
    return ast.dump(node, include_attributes=False) == ast.dump(
        expected, include_attributes=False
    )

def _direct_assignment(method: ast.FunctionDef, name: str) -> ast.Assign | None:
    return next(
        (
            statement for statement in method.body
            if isinstance(statement, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == name
                    for target in statement.targets)
        ),
        None,
    )


def _is_workload_error_raise(statement: ast.stmt) -> bool:
    return isinstance(statement, ast.Raise) and statement.exc is not None and any(
        isinstance(node, ast.Name) and node.id == "WorkloadExecutionError"
        for node in ast.walk(statement.exc)
    )


def _body_has_reachable_raise(body: list[ast.stmt]) -> bool:
    for statement in body:
        if _is_workload_error_raise(statement):
            return True
        if isinstance(statement, (ast.Return, ast.Break, ast.Continue)):
            return False
    return False


def _status_test(node: ast.AST, variable: str) -> bool:
    return (
        isinstance(node, ast.Compare)
        and len(node.ops) == 1
        and isinstance(node.ops[0], ast.NotEq)
        and len(node.comparators) == 1
        and _ast_matches(node.comparators[0], '"SUCCEEDED"')
        and _ast_matches(node.left, f'{variable}["status"]')
    )


def _has_reachable_status_guard(
    method: ast.FunctionDef,
    variable: str,
    *,
    after_line: int = -1,
    before_line: int | None = None,
) -> bool:
    return any(
        isinstance(statement, ast.If)
        and statement.lineno > after_line
        and (before_line is None or statement.lineno < before_line)
        and _status_test(statement.test, variable)
        and _body_has_reachable_raise(statement.body)
        for statement in method.body
    )


def _has_reachable_if(
    method: ast.FunctionDef,
    expression: str,
    *,
    after_line: int = -1,
    before_line: int | None = None,
) -> bool:
    return any(
        isinstance(statement, ast.If)
        and statement.lineno > after_line
        and (before_line is None or statement.lineno < before_line)
        and _ast_matches(statement.test, expression)
        and _body_has_reachable_raise(statement.body)
        for statement in method.body
    )


def _no_return_before(method: ast.FunctionDef, line: int) -> bool:
    return not any(
        isinstance(statement, ast.Return) and statement.lineno < line
        for statement in method.body
    )


def _morning_registry_contract(source: str) -> bool:
    method = _registry_method(source, "_morning_news_0830")
    if method is None:
        return False
    expected_assignments = {
        "module": '"scripts.run_scheduled_morning_news"',
        "modules": "[module]",
        "entry": 'self.shared_package_root / "scripts" / "run_scheduled_morning_news.py"',
        "environment": "os.environ.copy()",
    }
    for name, expression in expected_assignments.items():
        assignment = _direct_assignment(method, name)
        if assignment is None or not _ast_matches(assignment.value, expression):
            return False
    environment_value = next(
        (
            statement for statement in method.body
            if isinstance(statement, ast.Assign)
            and any(
                isinstance(target, ast.Subscript)
                and _ast_matches(target.value, "environment")
                and _ast_matches(target.slice, '"V3_SHARED_DATA_STORE_ROOT"')
                for target in statement.targets
            )
        ),
        None,
    )
    if environment_value is None or not _ast_matches(environment_value.value, "str(self.shared_data_root)"):
        return False
    calls, direct = _direct_run_calls(method)
    if len(calls) != 1 or calls != direct:
        return False
    call = direct[0]
    if (
        len(call.args) != 2
        or [keyword.arg for keyword in call.keywords] != ["cwd", "env"]
        or not _ast_matches(call.args[0], "module")
        or not _ast_matches(call.args[1], '["--trade-date", request.business_date]')
        or not _ast_matches(call.keywords[0].value, "self.shared_package_root")
        or not _ast_matches(call.keywords[1].value, "environment")
    ):
        return False
    if not _no_return_before(method, call.lineno):
        return False
    return (
        _has_reachable_if(
            method,
            "self.shared_data_root is None or self.shared_package_root is None",
            before_line=call.lineno,
        )
        and _has_reachable_if(method, "not entry.is_file()", before_line=call.lineno)
    )


def _zsxq_registry_contract(source: str) -> bool:
    method = _registry_method(source, "_zsxq_0830")
    if method is None:
        return False
    module_assignment = _direct_assignment(method, "modules")
    expected_modules = [
        "ops.run_zsxq_hourly_delta",
        "ops.collect_hourly_research_input",
        "ops.run_hourly_research",
    ]
    if module_assignment is None or not _ast_matches(
        module_assignment.value, repr(expected_modules).replace("'", '"')
    ):
        return False
    calls, direct = _direct_run_calls(method)
    expected_calls = (
        ("modules[0]", '["--data-root", str(self.data_root), "--date", request.business_date, "--slot", request.slot]'),
        ("modules[1]", '["--data-root", str(self.data_root), "--date", request.business_date, "--slot", request.slot]'),
        ("modules[2]", '["--data-root", str(self.data_root), "--date", request.business_date, "--target-date", request.business_date, "--slot", request.slot, "--mode", request.mode.value]'),
    )
    if len(calls) != 3 or calls != direct:
        return False
    if any(
        len(call.args) != 2 or call.keywords
        or not _ast_matches(call.args[0], module_expression)
        or not _ast_matches(call.args[1], arguments_expression)
        for call, (module_expression, arguments_expression) in zip(calls, expected_calls)
    ):
        return False
    first_line, second_line = calls[0].lineno, calls[1].lineno
    if not _no_return_before(method, first_line):
        return False
    if any(
        isinstance(statement, ast.Return)
        and first_line < statement.lineno < second_line
        for statement in method.body
    ):
        return False
    if not _has_reachable_status_guard(method, "fetched", after_line=first_line):
        return False
    if not _has_reachable_status_guard(method, "collected", after_line=second_line):
        return False
    if not any(
        isinstance(statement, ast.If)
        and statement.lineno > second_line
        and _ast_matches(statement.test, "collector_failure is not None")
        and _body_has_reachable_raise(statement.body)
        for statement in method.body
    ):
        return False
    outer = _registry_method(source, "__call__")
    if outer is None:
        return False
    handler_call_line = next(
        (
            statement.value.lineno
            for statement in ast.walk(outer)
            if isinstance(statement, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "result"
                for target in statement.targets
            )
            and isinstance(statement.value, ast.Call)
            and _ast_matches(statement.value.func, "handler")
        ),
        -1,
    )
    return handler_call_line >= 0 and _has_reachable_status_guard(
        outer, "result", after_line=handler_call_line
    )


def _registry_final_failure_guard(source: str) -> bool:
    method = _registry_method(source, "__call__")
    if method is None:
        return False
    result_lines = [
        statement.value.lineno
        for statement in ast.walk(method)
        if isinstance(statement, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "result" for target in statement.targets)
        and isinstance(statement.value, ast.Call)
    ]
    return bool(result_lines) and _has_reachable_status_guard(
        method, "result", after_line=max(result_lines)
    )


def _registry_mapping(container: ast.Module | ast.ClassDef, name: str) -> dict[str, ast.AST] | None:
    assignment = next(
        (
            statement for statement in container.body
            if isinstance(statement, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == name for target in statement.targets)
        ),
        None,
    )
    if assignment is None or not isinstance(assignment.value, ast.Dict):
        return None
    result: dict[str, ast.AST] = {}
    for key, value in zip(assignment.value.keys, assignment.value.values):
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            return None
        result[key.value] = value
    return result


def _membership_test(node: ast.AST, mapping_name: str) -> bool:
    return (
        isinstance(node, ast.Compare)
        and len(node.ops) == 1
        and isinstance(node.ops[0], ast.In)
        and _ast_matches(node.left, "workload.workload_id")
        and _ast_matches(node.comparators[0], mapping_name)
    )


def _handler_assignment(call: ast.FunctionDef) -> ast.Assign | None:
    """Find the handler map only on the actual non-milestone dispatch path."""

    milestone_branch = next(
        (
            statement
            for statement in call.body
            if isinstance(statement, ast.If)
            and _membership_test(statement.test, "MILESTONE_BY_WORKLOAD")
        ),
        None,
    )
    close_branch = next(
        (
            statement
            for statement in (milestone_branch.orelse if milestone_branch else [])
            if isinstance(statement, ast.If)
            and _membership_test(statement.test, "CLOSE_NODE_BY_WORKLOAD")
        ),
        None,
    )
    assignments = [
        statement
        for statement in (close_branch.orelse if close_branch else [])
        if isinstance(statement, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "handler"
            for target in statement.targets
        )
    ]
    return assignments[0] if len(assignments) == 1 else None


def _branch_result_call(branch: ast.If | None, method_name: str) -> bool:
    if branch is None:
        return False
    calls = [
        statement.value
        for statement in branch.body
        if isinstance(statement, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "result"
            for target in statement.targets
        )
        and isinstance(statement.value, ast.Call)
    ]
    return len(calls) == 1 and _ast_matches(
        calls[0].func, f"self.{method_name}"
    )


def _registry_dispatch(source: str, workload_id: str) -> dict[str, Any] | None:
    tree, registry_class, call = _registry_tree(source), _registry_class(source), _registry_method(source, "__call__")
    if tree is None or registry_class is None or call is None:
        return None
    milestone = _registry_mapping(tree, "MILESTONE_BY_WORKLOAD")
    if milestone is not None and workload_id in milestone:
        branch = next(
            (
                statement
                for statement in call.body
                if isinstance(statement, ast.If)
                and _membership_test(statement.test, "MILESTONE_BY_WORKLOAD")
            ),
            None,
        )
        if not _branch_result_call(branch, "_run_stage_center_milestone"):
            return None
        value = milestone[workload_id]
        if not isinstance(value, ast.Tuple) or len(value.elts) != 3 or not all(isinstance(item, ast.Constant) for item in value.elts):
            return None
        return {"method": "_run_stage_center_milestone", "dispatch": "MILESTONE_BY_WORKLOAD", "dispatch_values": [item.value for item in value.elts]}
    close = _registry_mapping(tree, "CLOSE_NODE_BY_WORKLOAD")
    if close is not None and workload_id in close:
        milestone_branch = next(
            (
                statement
                for statement in call.body
                if isinstance(statement, ast.If)
                and _membership_test(statement.test, "MILESTONE_BY_WORKLOAD")
            ),
            None,
        )
        branch = next(
            (
                statement
                for statement in (milestone_branch.orelse if milestone_branch else [])
                if isinstance(statement, ast.If)
                and _membership_test(statement.test, "CLOSE_NODE_BY_WORKLOAD")
            ),
            None,
        )
        if not _branch_result_call(branch, "_run_close_review_node"):
            return None
        value = close[workload_id]
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            return None
        return {"method": "_run_close_review_node", "dispatch": "CLOSE_NODE_BY_WORKLOAD", "dispatch_values": [value.value]}
    handler_assignment = _handler_assignment(call)
    if handler_assignment is None:
        return None
    milestone_branch = next(
        (
            statement
            for statement in call.body
            if isinstance(statement, ast.If)
            and _membership_test(statement.test, "MILESTONE_BY_WORKLOAD")
        ),
        None,
    )
    close_branch = next(
        (
            statement
            for statement in (milestone_branch.orelse if milestone_branch else [])
            if isinstance(statement, ast.If)
            and _membership_test(statement.test, "CLOSE_NODE_BY_WORKLOAD")
        ),
        None,
    )
    handler_result_calls = [
        statement.value
        for statement in (close_branch.orelse if close_branch else [])
        if isinstance(statement, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "result"
            for target in statement.targets
        )
        and isinstance(statement.value, ast.Call)
        and _ast_matches(statement.value.func, "handler")
    ]
    if len(handler_result_calls) != 1:
        return None
    handler_value = handler_assignment.value
    if not isinstance(handler_value, ast.Subscript) or not isinstance(handler_value.value, ast.Dict):
        return None
    if not _ast_matches(handler_value.slice, "workload.workload_id"):
        return None
    for key, value in zip(handler_value.value.keys, handler_value.value.values):
        if not isinstance(key, ast.Constant) or key.value != workload_id:
            continue
        if isinstance(value, ast.Attribute) and _ast_matches(value.value, "self"):
            return {"method": value.attr, "dispatch": "FixedExecutorRegistry.__call__.handler", "dispatch_values": []}
        if isinstance(value, ast.Lambda) and isinstance(value.body, ast.Call):
            target = value.body.func
            if not isinstance(target, ast.Attribute) or not _ast_matches(target.value, "self"):
                return None
            lane = next((keyword.value.value for keyword in value.body.keywords if keyword.arg == "lane" and isinstance(keyword.value, ast.Constant)), None)
            if lane is None:
                return None
            return {"method": target.attr, "dispatch": "FixedExecutorRegistry.__call__.handler", "dispatch_values": [lane]}
    return None


def _catalog_identity_valid(command: Any, dispatch: Mapping[str, Any], repo_root: Path) -> bool:
    if not isinstance(command, list) or len(command) < 3 or command[:2] != ["python", "-m"]:
        return False
    if not all(isinstance(item, str) and item for item in command[2:]):
        return False
    flags = command[3:]
    if len(flags) % 2 or any(not flags[index].startswith("--") for index in range(0, len(flags), 2)):
        return False
    if len({flags[index] for index in range(0, len(flags), 2)}) != len(flags) // 2:
        return False
    dispatch_name = dispatch.get("dispatch")
    values = dispatch.get("dispatch_values") or []
    command_values = dict(zip(flags[::2], flags[1::2]))
    if dispatch_name == "MILESTONE_BY_WORKLOAD":
        return (
            command[2] == "ops.run_stage_center_milestone"
            and len(values) == 3
            and command_values.get("--node") == values[0]
            and command_values.get("--stage-id") == values[1]
        )
    if dispatch_name == "CLOSE_NODE_BY_WORKLOAD":
        return (
            command[2] == "ops.run_v4_close_review_slot"
            and len(values) == 1
            and command_values.get("--node") == values[0]
        )
    if values and command_values.get("--lane") != values[0]:
        return False
    return _module_file(command[2], repo_root) is not None


def _regular_executor_provenance(
    workload_id: str,
    command: Any,
    repo_root: Path,
    registry_source: str | None = None,
    registry_source_sha256: str | None = None,
) -> dict[str, Any] | None:
    if workload_id in SPECIAL_EXECUTOR_CATALOG_COMMANDS or not _runner_module_present(command, repo_root):
        return None
    if command != _canonical_catalog_command(workload_id, Path(repo_root)):
        return None
    bundled_source, bundled_sha = _read_registry_source_with_sha(repo_root)
    if bundled_source is None:
        return None
    if registry_source is not None and registry_source != bundled_source:
        return None
    if registry_source_sha256 is not None and registry_source_sha256 != bundled_sha:
        return None
    registry_source, registry_source_sha256 = bundled_source, bundled_sha
    if registry_source is None:
        return None
    dispatch = _registry_dispatch(registry_source, workload_id)
    if dispatch is None:
        return None
    method = _registry_method(registry_source, str(dispatch["method"]))
    if method is None:
        return None
    calls, _direct = _direct_run_calls(method)
    if not calls or any(
        len(call.args) < 2
        or any(keyword.arg not in {"cwd", "env", "python_executable", "timeout_seconds"} for keyword in call.keywords)
        for call in calls
    ) or not _catalog_identity_valid(command, dispatch, repo_root):
        return None
    if not _catalog_matches_handler(workload_id, command, method) and not (
        workload_id == "preselection_pools"
        and isinstance(command, list)
        and command[2:3] == ["ops.materialize_preselection"]
        and _module_file(command[2], repo_root) is not None
    ):
        return None
    if not _frozen_executor_contract_matches(workload_id, command, dispatch, method):
        return None
    if not _registry_final_failure_guard(registry_source):
        return None
    return {
        "workload_id": workload_id,
        "kind": "actual_executor_handler",
        "status": "VERIFIED",
        "handler": f"FixedExecutorRegistry.{dispatch['method']}",
        "dispatch": dispatch["dispatch"],
        "catalog_identity": list(command),
        "capture_boundary": "FixedExecutorRegistry._run",
        "registry_source_sha256": registry_source_sha256,
        "source": _REGISTRY_METHOD_OWNER.get(
            str(dispatch["method"]), "infrastructure.scheduling.executor_registry"
        ),
    }


def _special_executor_provenance(workload_id: str, command: Any, repo_root: Path) -> dict[str, Any] | None:
    expected = SPECIAL_EXECUTOR_CATALOG_COMMANDS.get(workload_id)
    if expected is None or not isinstance(command, list) or tuple(command) != expected:
        return None
    source, source_sha = _read_registry_source_with_sha(Path(repo_root))
    if source is None:
        return None
    if workload_id == "morning_news_0830":
        bundle = _safe_repo_path(Path(repo_root), Path("upstreams/v3_shared_data/scripts/run_scheduled_morning_news.py"))
        if bundle is None or not bundle.is_file() or bundle.is_symlink() or not _morning_registry_contract(source):
            return None
        return {
            "workload_id": workload_id, "kind": "special_executor", "status": "VERIFIED",
            "handler": "FixedExecutorRegistry._morning_news_0830", "catalog_command": list(command),
            "module": expected[2], "bundle_path": "upstreams/v3_shared_data/scripts/run_scheduled_morning_news.py",
            "registry_source_sha256": source_sha,
            "source": _REGISTRY_METHOD_OWNER["_morning_news_0830"],
        }
    modules = ["ops.run_zsxq_hourly_delta", "ops.collect_hourly_research_input", "ops.run_hourly_research"]
    if not _zsxq_registry_contract(source):
        return None
    if any(
        (module_path := _module_file(module, Path(repo_root))) is None
        or not module_path.is_file() or module_path.is_symlink()
        for module in modules
    ):
        return None
    return {
        "workload_id": workload_id, "kind": "special_executor", "status": "VERIFIED",
        "handler": "FixedExecutorRegistry._zsxq_0830", "catalog_command": list(command),
        "modules": modules,
        "steps": [
            {"module": modules[0], "arguments": ["--data-root", "{data_root}", "--date", "{business_date}", "--slot", "{slot}"]},
            {"module": modules[1], "arguments": ["--data-root", "{data_root}", "--date", "{business_date}", "--slot", "{slot}"]},
            {"module": modules[2], "arguments": ["--data-root", "{data_root}", "--date", "{business_date}", "--target-date", "{business_date}", "--slot", "{slot}", "--mode", "{mode}"]},
        ],
        "failure_propagation": "ABORT_ON_ANY_STEP_FAILURE", "registry_source_sha256": source_sha,
        "source": _REGISTRY_METHOD_OWNER["_zsxq_0830"],
    }


def build_provenance_snapshot(
    workload_by_id: Mapping[str, Mapping[str, Any]], repo_root: Path
) -> dict[str, Any]:
    """Return registry-bound status for every catalog workload."""

    root = Path(repo_root)
    source, source_sha = _read_registry_source_with_sha(root)
    regular = {
        workload_id: provenance
        for workload_id, row in workload_by_id.items()
        if (
            provenance := _regular_executor_provenance(
                workload_id, row.get("command"), root, source, source_sha
            )
        )
    }
    runner_modules = sorted(
        workload_id
        for workload_id, row in workload_by_id.items()
        if _runner_module_present(row.get("command"), root)
    )
    incomplete = sorted(
        workload_id
        for workload_id in runner_modules
        if workload_id not in regular
        and workload_id not in SPECIAL_EXECUTOR_CATALOG_COMMANDS
    )
    available = sorted(regular)
    special_ids = sorted(
        workload_id
        for workload_id in SPECIAL_EXECUTOR_CATALOG_COMMANDS
        if workload_by_id.get(workload_id, {}).get("enabled") is True
    )
    special = [
        provenance
        for workload_id in special_ids
        if (
            provenance := _special_executor_provenance(
                workload_id, workload_by_id[workload_id].get("command"), root
            )
        )
    ]
    verified_special = {row["workload_id"] for row in special}
    return {
        "registry_source_sha256": source_sha,
        "regular_provenance_by_id": regular,
        "runner_modules_present": runner_modules,
        "incomplete_runner_commands": incomplete,
        "available_runners": available,
        "missing_runners": sorted(set(workload_by_id) - set(available)),
        "special_executor_workload_ids": special_ids,
        "special_executor_provenance": special,
        "verified_special_executor_ids": verified_special,
        "invalid_special_executor_workload_ids": sorted(set(special_ids) - verified_special),
    }


__all__ = [
    "SPECIAL_EXECUTOR_CATALOG_COMMANDS",
    "build_provenance_snapshot",
    "_regular_executor_provenance",
    "_runner_command_complete",
    "_runner_module_present",
    "_special_executor_provenance",
]
