from infrastructure.legacy_isolation import scan_text_tree, scan_tracked_production_text


TEXT_EXTENSIONS = (".py", ".ts", ".vue", ".js", ".html", ".css", ".json", ".toml", ".yaml", ".yml", ".ps1")
INJECTED_LEGACY_TEXT = "\n".join(
    (
        r'C:\Users\huang\Desktop\学习\v3_system',
        "C:/Users/huang/Desktop/学习/v3_system",
        "http://127.0.0.1:8771/api/v3",
        "sys.path.insert(0, 'legacy')",
        "from v3_system.legacy import execute",
    )
)


def test_zero_legacy_scanner_detects_all_vectors_in_each_supported_text_extension(tmp_path) -> None:
    isolated_tree = tmp_path / "isolated"
    isolated_tree.mkdir()
    for extension in TEXT_EXTENSIONS:
        (isolated_tree / f"fixture{extension}").write_text(INJECTED_LEGACY_TEXT, encoding="utf-8")

    violations = scan_text_tree(isolated_tree)

    assert {violation.relative_path.suffix for violation in violations} == set(TEXT_EXTENSIONS)
    assert all(
        violation.kinds
        == (
            "absolute_legacy_root",
            "legacy_8771_proxy",
            "sys_path_injection",
            "legacy_import_or_execution",
        )
        for violation in violations
    )


def test_zero_legacy_scanner_detects_relative_legacy_source_reads_and_import_module_aliases(tmp_path) -> None:
    fixtures = {
        "relative.yaml": "old_source: v3_system/runtime.py\n",
        "parent-relative.toml": 'old_source = "../v3_system/runtime.py"\n',
        "path-read.py": 'from pathlib import Path\nPath("v3_system/runtime.py").read_text()\n',
        "direct-import-module.py": "from importlib import import_module\nimport_module('v3_system.foo')\n",
        "aliased-import-module.py": "from importlib import import_module as load_module\nload_module('v3_system.foo')\n",
        "module-import-alias.py": "import importlib as modules\nmodules.import_module('v3_system.foo')\n",
    }
    for name, content in fixtures.items():
        (tmp_path / name).write_text(content, encoding="utf-8")

    violations = {violation.relative_path.name: violation.kinds for violation in scan_text_tree(tmp_path)}

    assert violations["relative.yaml"] == ("relative_legacy_source_reference",)
    assert violations["parent-relative.toml"] == ("relative_legacy_source_reference",)
    assert violations["path-read.py"] == ("relative_legacy_source_reference",)
    assert violations["direct-import-module.py"] == ("legacy_import_or_execution",)
    assert violations["aliased-import-module.py"] == ("legacy_import_or_execution",)
    assert violations["module-import-alias.py"] == ("legacy_import_or_execution",)


def test_zero_legacy_scanner_allows_relative_replacement_inventory_paths(tmp_path) -> None:
    relative_inventory = tmp_path / "inventory.yaml"
    relative_inventory.write_text("old_source: 30_runtime/worker.py\n", encoding="utf-8")

    assert scan_text_tree(tmp_path) == ()


def test_tracked_production_text_has_no_legacy_execution_dependency() -> None:
    assert scan_tracked_production_text() == ()
