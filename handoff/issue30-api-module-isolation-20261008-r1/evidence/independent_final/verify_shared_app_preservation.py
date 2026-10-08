"""Independent AST and byte checks for the exact R2 shared app delta.

Parses source only; it never imports or runs create_app or business code.
"""
from pathlib import Path
import ast
import copy
import hashlib
import json

ROOT = Path(__file__).resolve().parents[2]
BEFORE = ROOT / "work/preselection_scope/source/r2_app_byte_match/apps/api/v35_api/app.py"
AFTER = ROOT / "work/preselection_revision/after/apps/api/v35_api/app.py"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def dump(node):
    return ast.dump(node, include_attributes=False)


def main():
    before_raw, after_raw = BEFORE.read_bytes(), AFTER.read_bytes()
    assert sha(before_raw) == "90a2bf6390c6c0e219aa3d9bb22bc3b3630ecb2d447df494ae69425933424ed7"
    assert sha(after_raw) == "5d344dfe902db37f81e06d1d401e9a7e20ae910d8f7647b732ae2b3ba4f019e5"
    texts = [before_raw.decode(), after_raw.decode()]
    trees = [ast.parse(text) for text in texts]
    apps = [next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "create_app") for tree in trees]
    old_route = [n for n in apps[0].body if isinstance(n, ast.FunctionDef) and n.name == "preselection_pools"]
    new_registration = [n for n in apps[1].body if isinstance(n, ast.Expr) and any(
        isinstance(child, ast.Name) and child.id == "create_preselection_router" for child in ast.walk(n))]
    assert len(old_route) == len(new_registration) == 1
    expected_registration = ast.parse("""app.include_router(create_preselection_router(
    PreselectionPoolService(store, configured_pool_source=bool(configured_pool_source),
                            resolved_pool_source=resolved_pool_source),
    get_catalog=_catalog, validate_date=_strict_date,
))""").body[0]
    assert dump(new_registration[0]) == dump(expected_registration)
    unchanged = [[n for n in app.body if n not in removed] for app, removed in zip(apps, [old_route, new_registration])]
    assert len(unchanged[0]) == len(unchanged[1]) == 54
    statements = []
    for old, new in zip(*unchanged):
        assert dump(old) == dump(new)
        old_text = ast.get_source_segment(texts[0], old)
        new_text = ast.get_source_segment(texts[1], new)
        assert old_text == new_text
        statements.append({"type": type(old).__name__, "name": getattr(old, "name", None),
            "sha256": sha(old_text.encode()), "before_line": old.lineno, "after_line": new.lineno})

    helpers = {"_is_sha256", "_is_exact_configured_hk_pool", "_preselection_response_from_pools"}
    normalized = []
    for index, tree in enumerate(trees):
        body = []
        for original in tree.body:
            node = copy.deepcopy(original)
            if isinstance(node, ast.FunctionDef) and node.name in helpers:
                assert index == 0
                continue
            if isinstance(node, ast.ImportFrom):
                if node.module in {"apps.api.v35_api.preselection_router", "apps.api.v35_api.preselection_service"}:
                    assert index == 1
                    continue
                if node.module == "domains" and any(alias.name == "preselection" for alias in node.names):
                    assert index == 0 and len(node.names) == 1 and node.names[0].asname == "preselection_domain"
                    continue
                if node.module == "infrastructure.preselection_pool_store":
                    assert index == 0 and [alias.name for alias in node.names] == ["PreselectionPoolStore"]
                    continue
                if node.module == "domains.preselection":
                    assert [alias.name for alias in node.names] == (["OPTIONAL_DAILY_POOL_IDS", "date_catalog", "preselection"] if index == 0 else ["date_catalog"])
                    node.names = [ast.alias(name="date_catalog")]
            if isinstance(node, ast.FunctionDef) and node.name == "create_app":
                node.body = copy.deepcopy(unchanged[index])
            body.append(node)
        normalized.append(ast.Module(body=body, type_ignores=[]))
    assert dump(normalized[0]) == dump(normalized[1])

    marker = b"    # V4 manager research is a separate date/input keyed job lane."
    assert before_raw.count(marker) == after_raw.count(marker) == 1
    old_suffix, new_suffix = before_raw[before_raw.index(marker):], after_raw[after_raw.index(marker):]
    assert old_suffix == new_suffix
    # Also independently match the author's narrower service-construction suffix.
    documented = "022417f603c182a870e8e64f3f7efcbad649c6a2b3a2d78825008c84d6b5b0db"
    service_marker = b"    resolved_manager_research_state_root = _resolve_manager_research_state_root("
    assert before_raw.count(service_marker) == after_raw.count(service_marker) == 1
    service_before = before_raw[before_raw.index(service_marker):]
    service_after = after_raw[after_raw.index(service_marker):]
    assert service_before == service_after
    construction_marker = b"    manager_research_service = manager_research_job_service("
    assert before_raw.count(construction_marker) == after_raw.count(construction_marker) == 1
    construction_before = before_raw[before_raw.index(construction_marker):]
    construction_after = after_raw[after_raw.index(construction_marker):]
    assert construction_before == construction_after
    assert sha(construction_before) == documented
    result = {"status": "PASS", "method": "AST parse only; explicit allowed deltas removed; remaining AST and 54 create_app statement bytes compared",
        "before_app_sha256": sha(before_raw), "after_app_sha256": sha(after_raw),
        "unrelated_ast_identical": True, "non_preselection_create_app_statements": statements,
        "exact_registration_verified": True,
        "entire_manager_section_through_return_byte_exact": True,
        "entire_manager_section_sha256": sha(old_suffix),
        "manager_service_wiring_through_return_byte_exact": True,
        "manager_state_and_service_initialization_sha256": sha(service_before),
        "manager_service_wiring_sha256": sha(construction_before),
        "author_reported_manager_wiring_sha256_independently_matched": True,
        "runtime_business_equivalence": "NOT_RUN; byte preservation is not a manager business regression"}
    (Path(__file__).parent / "final_shared_app_preservation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "non_preselection_create_app_statements"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
