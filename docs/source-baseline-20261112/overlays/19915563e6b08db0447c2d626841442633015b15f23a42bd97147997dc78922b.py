"""Small AST extractors used by the registry provenance audit.

This module intentionally contains no runtime imports or dispatch policy.  It
only turns the fixed registry's direct ``_run`` calls into checkable command
shape information; the provenance module owns the safety decision.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any


def _direct_assignment(method: ast.FunctionDef, name: str) -> ast.Assign | None:
    return next(
        (
            statement for statement in method.body
            if isinstance(statement, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == name
                for target in statement.targets
            )
        ),
        None,
    )


def direct_run_calls(method: ast.FunctionDef) -> tuple[list[ast.Call], list[ast.Call]]:
    calls = sorted(
        (
            node for node in ast.walk(method)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_run"
        ),
        key=lambda node: (node.lineno, node.col_offset),
    )
    direct = []
    for statement in method.body:
        value = statement.value if isinstance(statement, (ast.Assign, ast.Return)) else None
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute) and value.func.attr == "_run":
            direct.append(value)
    return calls, direct


def _assigned_value(method: ast.FunctionDef, name: str) -> ast.AST | None:
    assignment = _direct_assignment(method, name)
    return assignment.value if assignment is not None else None


def _module_value(
    node: ast.AST, method: ast.FunctionDef, seen: tuple[str, ...] = ()
) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name) and node.id not in seen:
        value = _assigned_value(method, node.id)
        return _module_value(value, method, (*seen, node.id)) if value is not None else None
    if (
        isinstance(node, ast.Subscript)
        and isinstance(node.slice, ast.Constant)
        and isinstance(node.slice.value, int)
    ):
        value = _assigned_value(method, node.value.id) if isinstance(node.value, ast.Name) else None
        if isinstance(value, ast.List) and node.slice.value < len(value.elts):
            return _module_value(value.elts[node.slice.value], method, seen)
    return None


def _flag_values(node: ast.AST, method: ast.FunctionDef, *, top_level: bool) -> list[str]:
    if isinstance(node, ast.Name):
        value = _assigned_value(method, node.id)
        return _flag_values(value, method, top_level=top_level) if value is not None else []
    if isinstance(node, ast.IfExp):
        return _flag_values(node.body, method, top_level=False) + _flag_values(
            node.orelse, method, top_level=False
        )
    if isinstance(node, ast.Starred):
        return _flag_values(node.value, method, top_level=False)
    if not isinstance(node, (ast.List, ast.Tuple)):
        return []
    result: list[str] = []
    for item in node.elts:
        if isinstance(item, ast.Constant) and isinstance(item.value, str) and item.value.startswith("--"):
            result.append(item.value)
        elif not top_level:
            result.extend(_flag_values(item, method, top_level=False))
    return result


def run_call_contract(
    call: ast.Call, method: ast.FunctionDef
) -> tuple[str | None, list[str], list[str], list[str]]:
    if len(call.args) < 2:
        return None, [], [], []
    module = _module_value(call.args[0], method)
    required = _flag_values(call.args[1], method, top_level=True)
    all_flags = _flag_values(call.args[1], method, top_level=False)
    if isinstance(call.args[1], ast.Name):
        name = call.args[1].id
        for node in ast.walk(method):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "extend"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == name
                and node.args
            ):
                all_flags.extend(_flag_values(node.args[0], method, top_level=False))
    return module, required, all_flags, [keyword.arg or "**" for keyword in call.keywords]


def _assignment_nodes(node: ast.AST, method: ast.FunctionDef) -> list[ast.AST]:
    if isinstance(node, ast.Name):
        value = _assigned_value(method, node.id)
        return _assignment_nodes(value, method) if value is not None else []
    if isinstance(node, ast.IfExp):
        return _assignment_nodes(node.body, method) + _assignment_nodes(node.orelse, method)
    if isinstance(node, ast.Starred):
        return _assignment_nodes(node.value, method)
    if isinstance(node, (ast.List, ast.Tuple)):
        result: list[ast.AST] = []
        for item in node.elts:
            result.extend(_assignment_nodes(item, method) if isinstance(item, ast.Starred) else [item])
        return result
    return []


def argument_pairs(node: ast.AST, method: ast.FunctionDef) -> list[tuple[str, ast.AST]]:
    nodes = _assignment_nodes(node, method)
    if isinstance(node, ast.Name):
        for extension in sorted(
            (
                item for item in ast.walk(method)
                if isinstance(item, ast.Call)
                and isinstance(item.func, ast.Attribute)
                and item.func.attr == "extend"
                and isinstance(item.func.value, ast.Name)
                and item.func.value.id == node.id
                and item.args
            ),
            key=lambda item: item.lineno,
        ):
            nodes.extend(_assignment_nodes(extension.args[0], method))
    return [
        (item.value, nodes[index + 1])
        for index, item in enumerate(nodes[:-1])
        if isinstance(item, ast.Constant)
        and isinstance(item.value, str)
        and item.value.startswith("--")
    ]


_PLACEHOLDER_ALIASES = {
    "--data-root": {"data_root"},
    "--shared-data-root": {"shared_data_root"},
    "--selector-data-root": {"selector_data_root"},
    "--shared-package-root": {"shared_package_root", "review_core_shared_package_root"},
    "--stage-selection-root": {"stage_selection_root"},
    "--date": {"business_date"},
    "--trade-date": {"business_date"},
    "--signal-date": {"business_date"},
    "--through-date": {"business_date"},
    "--business-date": {"business_date"},
    "--effective-date": {"target_date"},
    "--target-date": {"target_date"},
    "--slot": {"slot"},
    "--mode": {"mode"},
    "--futu-python": {"shared_futu_python"},
    "--hk-python-executable": {"hk_0_2_python"},
    "--stage": {"stage_id"},
    "--selection-root": {"stage_selection_root"},
    "--producer-receipt-root": {"research_panel_receipt_root"},
    "--receipt-root": {"research_panel_receipt_root"},
    "--a-tdx-root": {"research_panel_a_tdx_root"},
    "--hk-tdx-root": {"research_panel_hk_tdx_root"},
    "--a-sync-script": {"research_panel_a_sync_script"},
    "--a-formula-script": {"research_panel_a_formula_script"},
    "--a-seed-panel": {"research_panel_a_seed_panel"},
    "--a-data-root": {"research_panel_a_data_root"},
    "--a-selector-pointer": {"research_panel_a_selector_pointer"},
    "--a-backtest-pointer": {"research_panel_a_backtest_pointer"},
    "--a-selector-seed": {"research_panel_a_selector_seed"},
    "--a-backtest-seed": {"research_panel_a_backtest_seed"},
    "--a-contract-csv": {"research_panel_a_contract_csv"},
    "--a-canonical-formula": {"research_panel_a_canonical_formula"},
    "--a-return-root": {"research_panel_a_return_root"},
    "--hk-updater-script": {"research_panel_hk_updater_script"},
    "--hk-asset-root": {"research_panel_hk_asset_root"},
    "--hk-root": {"review_core_hk_root"},
    "--calendar-path": {"review_core_calendar_path"},
    "--review-core-package-root": {"review_core_package_root"},
    "--shared-store-root": {"review_core_shared_store_root"},
    "--runtime-root": {"review_core_runtime_root"},
    "--close-root": {"review_core_close_root"},
    "--fupan-store-root": {"review_core_fupan_store_root"},
    "--stage7-store-root": {"review_core_stage7_store_root"},
    "--bundle-root": {"review_core_bundle_root"},
    "--selector-pointer": {"selector_pointer"},
    "--backtest-pointer": {"backtest_pointer"},
    "--close-review-path": {"close_review_path"},
    "--close-review-receipt": {"close_review_receipt"},
    "--input-root": {"wechat_input_root"},
    "--receipt": {"wechat_receipt"},
    "--panel-pointer": {"panel_pointer"},
}
_DYNAMIC_LITERAL_FLAGS = frozenset({"--node", "--stage-id", "--lane"})

# These immutable fingerprints are the third-party anchor for the audit: a
# catalog and registry changed together must not be able to certify one
# another.  The command hash covers the complete module/flag/value sequence;
# the dispatch tuple and function AST hash cover the actual registry owner.
_FROZEN_EXECUTOR_CONTRACTS = {
    "hourly_research": (
        "cddcf389261f749a5aa4a29dd7e2f226d3a78b794d162913bce84f871be756d3",
        "FixedExecutorRegistry.__call__.handler", "_hourly_research", (),
        "8abe09a191780c47f146e3f4820d5b893037fa6e8ea45ef6a197823d41d0fea8",
    ),
    "us_market_digest": (
        "f90ebbfe23116e6abd800a6ef2e5dc673e6dbf0f48e57d895434c7dbf73f3020",
        "FixedExecutorRegistry.__call__.handler", "_us_market_digest", (),
        "fb4e0df55ff8809361af739d0ae5e0a814f20fa11637670c89a5179f9a5c6ac4",
    ),
    "research_panel_daily_a": (
        "32e098579fac9c63a0602a04964fffd9e71c320c4c96f9eb547d8aef89fd6fe5",
        "FixedExecutorRegistry.__call__.handler", "_research_panel_daily", ("A",),
        "8eb945669a35a735c6e862ac593f5ad569524ae4513e4f87410a76db9964b28c",
    ),
    "research_panel_daily_hk": (
        "695676e929e9aa3185e5b739acc5d213f812962cfa49bbf7ad643eed53a18d04",
        "FixedExecutorRegistry.__call__.handler", "_research_panel_daily", ("HK",),
        "8eb945669a35a735c6e862ac593f5ad569524ae4513e4f87410a76db9964b28c",
    ),
    "research_panel_runtime_evidence": (
        "a48f7f858c9f9dd276d18d769ead18ff36781a18aa0160f7671dfbfe1d8231c3",
        "FixedExecutorRegistry.__call__.handler", "_research_panel_runtime_evidence", (),
        "1cc2600b3440fa3613b00faa68374d5173735cc8919998ecd9fdc3b22609a2b9",
    ),
    "wechat_preselection_sync": (
        "e091edc8169458a14b254978d026fbc5171d4ad8e5ca7e28d3e732f029fbd025",
        "FixedExecutorRegistry.__call__.handler", "_wechat_preselection_sync", (),
        "bce5b8983091446da92b9d676ec9376afe42ca3ba9dcb7f964adcda9c492c362",
    ),
    "review_core_pool_pipeline": (
        "8a1ebe0fb02d4ef2f483defbd902bfc7a5f79bd0d94d818d4f3a9b0d4a70c836",
        "FixedExecutorRegistry.__call__.handler", "_review_core_pool_pipeline", (),
        "af12f9f95c2ad5292559b79719cee8804ca72bab2231e5733781b4a0be2a7fb2",
    ),
    "a_share_close_review": (
        "9346cbf798b75575c5b92638a86547ff81afabf746049743f5558dbd36fa9b2e",
        "FixedExecutorRegistry.__call__.handler", "_a_share_close_review", (),
        "c504f473a263b8d6eecd22efa9f188bfe72b4fc3de66c39109d55edea5ddca48",
    ),
    "hk_connect_close_review": (
        "08acfadfacd44893653b67b6ac9429af0f6899b8c95f5bc78a221259d55dfbe0",
        "FixedExecutorRegistry.__call__.handler", "_hk_connect_close_review", (),
        "e98df7dc0ec7afbce617bb45f190443e659c0e66bff4ffb8445956f8785a95a7",
    ),
    "preselection_pools": (
        "a96c8b693e6673783ff33f3529c295512a72176a1afdd28a51a6110b419ee6d4",
        "FixedExecutorRegistry.__call__.handler", "_preselection_pools", (),
        "7778b325464f49a85d415f9d435b94e9c0afbb25bdf678a6fc2470f0d0f1d648",
    ),
    "daily_materialize": (
        "c74e1c3e24ec59545185c06678e7429f38496d63bbcc93a1078724736e78b5a5",
        "FixedExecutorRegistry.__call__.handler", "_daily_materialize", (),
        "472b1301b7f2922a8e6a169878615e9f6f359dde2f9650584200ee9cbe0dd0d5",
    ),
    "stage_workbench": (
        "00a583ef0fab18d9cc811b3e77a54e8724cec98582f4f8a48887e0dcd9a73928",
        "FixedExecutorRegistry.__call__.handler", "_stage_workbench", (),
        "8c0161d9599229ba28e3d1a9a86917c35d497d0bae0c814a820aa71254ab3edc",
    ),
    "hk_auction_0920": (
        "bf9621101728a4405f3c1f4ecd0300a7e8b58a8c67e27905b9c66473aeae7501",
        "FixedExecutorRegistry.__call__.handler", "_hk_auction_0920", (),
        "806868eb2474ea39bc2d2407907a3b98189388bbbe4e937738ca35b37fb5675b",
    ),
    "fupan_close_materials": (
        "5012108c8d5c408b608525bcbd7c075ccdb753386ec561a904c6f1dd4193ebb9",
        "MILESTONE_BY_WORKLOAD", "_run_stage_center_milestone",
        ("FUPAN_CLOSE_MATERIALS", "STAGE_1445_1500", "A_SHARE"),
        "286317c429aa0b3f6bf623fbf98bdf5e051509a80528b3bc6a87ef806b55d4c4",
    ),
    "fupan_review_start": (
        "23720e722cba1da5170e78fe00184468cb0be3d68ef6351e9cdb479028fcd757",
        "MILESTONE_BY_WORKLOAD", "_run_stage_center_milestone",
        ("FUPAN_REVIEW_START", "STAGE_1545_1555", "HK_CONNECT"),
        "286317c429aa0b3f6bf623fbf98bdf5e051509a80528b3bc6a87ef806b55d4c4",
    ),
    "fupan_video_check": (
        "6c5303883ebb1bfc10ecb9921687122fd8b95750bfd91c9f7822b2be5a725c37",
        "CLOSE_NODE_BY_WORKLOAD", "_run_close_review_node", ("FUPAN_VIDEO_CHECK",),
        "136aa682e234af59a9a979cec21389b28db25d1a37121cf8ef7b9367f01c7222",
    ),
    "fupan_video_download_asr": (
        "7d5277b7e1f2be78007b0be7f5edb523368ec9957c59e3e1c26fe48b35f4c2d7",
        "CLOSE_NODE_BY_WORKLOAD", "_run_close_review_node", ("FUPAN_VIDEO_DOWNLOAD_ASR",),
        "136aa682e234af59a9a979cec21389b28db25d1a37121cf8ef7b9367f01c7222",
    ),
    "fupan_stockdict": (
        "0fe9e8c448f1daff16d2dbdde029080c1faa7a4df11d16595dce713157fab9fc",
        "CLOSE_NODE_BY_WORKLOAD", "_run_close_review_node", ("FUPAN_STOCKDICT",),
        "136aa682e234af59a9a979cec21389b28db25d1a37121cf8ef7b9367f01c7222",
    ),
    "fupan_video_table_ocr_align": (
        "d5977b17096ca7846e29b78812e8153feb1e3bac6b50b150444eb98c3a635318",
        "CLOSE_NODE_BY_WORKLOAD", "_run_close_review_node", ("FUPAN_VIDEO_TABLE_OCR_ALIGN",),
        "136aa682e234af59a9a979cec21389b28db25d1a37121cf8ef7b9367f01c7222",
    ),
    "fupan_video_gap": (
        "d3ca236a220ec4d851c4d4f32c525d684963ec7c0e62bb3b4a6a639faa2570e5",
        "CLOSE_NODE_BY_WORKLOAD", "_run_close_review_node", ("FUPAN_VIDEO_GAP",),
        "136aa682e234af59a9a979cec21389b28db25d1a37121cf8ef7b9367f01c7222",
    ),
    "fupan_v3_publish": (
        "fc3d769259afef18431040fe90e4dc36fad163092a552b536cf1c5a6ea7e9e97",
        "CLOSE_NODE_BY_WORKLOAD", "_run_close_review_node", ("FUPAN_V3_PUBLISH",),
        "136aa682e234af59a9a979cec21389b28db25d1a37121cf8ef7b9367f01c7222",
    ),
    "fupan_8771_verify": (
        "8db7480e63a9f8e75c007436261e39d3eb9b355ec1bb75870f63a3f0a8cf8209",
        "CLOSE_NODE_BY_WORKLOAD", "_run_close_review_node", ("FUPAN_8771_VERIFY",),
        "136aa682e234af59a9a979cec21389b28db25d1a37121cf8ef7b9367f01c7222",
    ),
}


def frozen_executor_contract_matches(
    workload_id: str, command: Any, dispatch: Any, method: ast.FunctionDef
) -> bool:
    expected = _FROZEN_EXECUTOR_CONTRACTS.get(workload_id)
    if expected is None or not isinstance(dispatch, dict):
        return False
    try:
        command_sha = hashlib.sha256(
            json.dumps(command, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        dispatch_values = dispatch.get("dispatch_values")
        method_sha = hashlib.sha256(
            ast.dump(method, include_attributes=False).encode("utf-8")
        ).hexdigest()
    except (TypeError, ValueError):
        return False
    return (
        command_sha == expected[0]
        and dispatch.get("dispatch") == expected[1]
        and dispatch.get("method") == expected[2]
        and isinstance(dispatch_values, list)
        and tuple(dispatch_values) == expected[3]
        and method_sha == expected[4]
    )


def _placeholder_matches_flag(flag: str, name: str) -> bool:
    return name in _PLACEHOLDER_ALIASES.get(flag, ())


def _expression_has_role(flag: str, name: str, value: ast.AST) -> bool:
    parts = {
        item
        for node in ast.walk(value)
        for item in (
            [node.id.lower()] if isinstance(node, ast.Name) else
            [node.attr.lower()] if isinstance(node, ast.Attribute) else
            [str(node.value).lower().replace("-", "_")] if isinstance(node, ast.Constant) and isinstance(node.value, str) else
            []
        )
    }
    parts.update(
        item[4:]
        for item in tuple(parts)
        if item.startswith("v35_")
    )
    if name in parts:
        return True
    aliases = {
        "research_panel_receipt_root": ("producer_root",),
        "close_review_path": ("close_path",),
        "close_review_receipt": ("close_receipt",),
        "review_core_calendar_path": ("calendar_path",),
        "panel_pointer": ("pointer",),
        "review_core_package_root": ("package_root",),
        "review_core_shared_package_root": ("shared_package_root",),
        "review_core_shared_store_root": ("shared_store_root",),
        "review_core_runtime_root": ("runtime_root",),
        "review_core_hk_root": ("hk_root",),
        "review_core_close_root": ("close_root",),
        "review_core_fupan_store_root": ("fupan_root",),
        "review_core_stage7_store_root": ("stage7_root",),
        "review_core_bundle_root": ("bundle_root",),
        "wechat_input_root": ("input_root",),
        "wechat_receipt": ("receipt",),
        "shared_futu_python": ("shared_futu_python_executable",),
        "hk_0_2_python": ("hk_0_2_python_executable",),
    }
    if any(alias in parts for alias in aliases.get(name, ())):
        return True
    return flag == "--target-date" and {"request", "business_date"} <= parts


def catalog_values_match(
    command: Any, pairs: list[tuple[str, ast.AST]]
) -> bool:
    if not isinstance(command, list) or len(command[3:]) % 2:
        return False
    if len({flag for flag, _value in pairs}) != len(pairs):
        return False
    actual = {flag: value for flag, value in pairs}
    for flag, expected in zip(command[3::2], command[4::2]):
        value = actual.get(flag)
        if value is None:
            return False
        if expected.startswith("{") and expected.endswith("}"):
            name = expected[1:-1]
            if not _placeholder_matches_flag(flag, name) or not _expression_has_role(flag, name, value):
                return False
        elif flag not in _DYNAMIC_LITERAL_FLAGS:
            if not isinstance(value, ast.Constant) or str(value.value) != expected:
                return False
    return True


def canonical_catalog_command(workload_id: str, repo_root: Path) -> list[str] | None:
    path = Path(repo_root) / "contracts" / "runtime_workloads.json"
    if path.is_symlink() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("workloads", []) if isinstance(payload, dict) else []
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return next(
        (
            row.get("command")
            for row in rows
            if isinstance(row, dict)
            and row.get("workload_id") == workload_id
            and isinstance(row.get("command"), list)
        ),
        None,
    )


_OPTIONAL_CATALOG_FLAGS = {
    "hourly_research": frozenset({"--source"}),
    "hk_connect_close_review": frozenset({"--stage-selection-root"}),
    "stage_workbench": frozenset({"--shared-data-root", "--shared-package-root"}),
}

_SCOPED_CATALOG_CONTRACTS = {
    "us_market_digest": {
        "catalog_command": (
            "python", "-m", "ops.us_market_digest",
            "--data-root", "{data_root}",
            "--trade-date", "{business_date}",
            "--capture-phase", "{capture_phase}",
        ),
        "module": "ops.us_market_digest",
        "runtime_flags": (
            "--data-root", "--trade-date", "--capture-phase", "--timeout",
        ),
        "runtime_expressions": {
            "--data-root": "str(self.data_root)",
            "--trade-date": 'capture["us_session_date"]',
            "--capture-phase": 'capture["capture_phase"]',
            "--timeout": "str(_PERIPHERAL_FETCH_TIMEOUT_SECONDS)",
        },
    },
}


def _expression_matches(value: ast.AST, expression: str) -> bool:
    try:
        expected = ast.parse(expression, mode="eval").body
    except SyntaxError:
        return False
    return ast.dump(value, include_attributes=False) == ast.dump(
        expected, include_attributes=False
    )


def _scoped_catalog_matches_handler(
    contract: dict[str, Any], command: Any, method: ast.FunctionDef
) -> bool:
    if not isinstance(command, list) or tuple(command) != contract["catalog_command"]:
        return False
    calls, _direct = direct_run_calls(method)
    if len(calls) != 1:
        return False
    call = calls[0]
    module, required, all_flags, kwargs = run_call_contract(call, method)
    runtime_flags = contract["runtime_flags"]
    if (
        module != contract["module"]
        or tuple(required) != runtime_flags
        or tuple(all_flags) != runtime_flags
        or kwargs
    ):
        return False
    if len(call.args) < 2:
        return False
    pairs = argument_pairs(call.args[1], method)
    if tuple(flag for flag, _value in pairs) != runtime_flags:
        return False
    return all(
        _expression_matches(value, contract["runtime_expressions"][flag])
        for flag, value in pairs
    )


def catalog_matches_handler(
    workload_id: str, command: Any, method: ast.FunctionDef
) -> bool:
    scoped_contract = _SCOPED_CATALOG_CONTRACTS.get(workload_id)
    if scoped_contract is not None:
        return _scoped_catalog_matches_handler(scoped_contract, command, method)
    if not isinstance(command, list) or len(command) < 3 or len(command[3:]) % 2:
        return False
    catalog_module = command[2]
    catalog_flags = command[3::2]
    optional = _OPTIONAL_CATALOG_FLAGS.get(workload_id, frozenset())
    matched = []
    for call in direct_run_calls(method)[0]:
        module, required, all_flags, kwargs = run_call_contract(call, method)
        if module != catalog_module or any(
            name not in {"cwd", "env", "python_executable", "timeout_seconds"}
            for name in kwargs
        ):
            continue
        catalog_set, actual_set = set(catalog_flags), set(all_flags)
        if (
            set(required) - catalog_set <= optional
            and catalog_set <= actual_set
            and actual_set - catalog_set <= optional
            and catalog_values_match(command, argument_pairs(call.args[1], method))
        ):
            matched.append(call)
    return len(matched) == 1


__all__ = [
    "argument_pairs",
    "canonical_catalog_command",
    "catalog_matches_handler",
    "catalog_values_match",
    "direct_run_calls",
    "frozen_executor_contract_matches",
    "run_call_contract",
]
