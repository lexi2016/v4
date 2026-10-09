"""Exercise the real runner with tiny real pytest/Node suites, not fake exit codes.

Only package-byte verification is replaced: these are deliberately synthetic
mini-packages testing the test gate, not a valid Stage deployment package.
"""
import importlib.util
import json
from pathlib import Path
import sys

import pytest


PACKAGE = Path(__file__).resolve().parents[2]


def load_runner():
    sys.path.insert(0, str(PACKAGE / "tools"))
    try:
        spec = importlib.util.spec_from_file_location("completeness_runner", PACKAGE / "tools/run_checks.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)


def miniature_package(tmp_path, suite=None, defect=None):
    package = tmp_path / "synthetic_package"
    api = package / "checks/api"
    counts = {"stage": 1, "api": 1, "vue": 2, "adaptation": 1, "vue_actual": 1}
    if suite:
        counts[suite] += 1
    write(package / "SOURCE_MAP.json", json.dumps({"files": []}))
    write(package / "TEST_EXPECTATIONS.json", json.dumps({
        "schema_version": "V4_TEST_EXPECTATIONS_V1", "expected_tests": counts,
        "maximum_skipped": 0,
    }))
    paths = {"stage": package / "tests/test_synthetic.py", "api": api / "tests/test_synthetic.py",
             "adaptation": package / "checks/adaptation/test_synthetic.py"}
    for name, path in paths.items():
        code = "def test_one():\n    assert 2 + 2 == 4\n"
        if name == suite and defect == "skip":
            code += "\nimport pytest\n@pytest.mark.skip(reason='explicit synthetic skip')\ndef test_two():\n    assert True\n"
        write(path, code)
    for name, filename in (("vue", "legacy_presentation.test.mjs"),
                           ("vue_actual", "current_app_presentation.test.mjs")):
        code = 'import test from "node:test"; import assert from "node:assert/strict";\ntest("one", () => assert.equal(2 + 2, 4));\n'
        if name == suite and defect == "skip":
            code += 'test("two", {skip: "explicit synthetic skip"}, () => {});\n'
        write(api / "tests" / filename, code)
    write(api / "tests/research_presentation.test.mjs", 'import test from "node:test"; import assert from "node:assert/strict";\ntest("research", () => assert.ok(true));\n')
    write(package / "tools/export_integration_fixture.py", "# Synthetic gate fixture command, no market I/O.\n")
    write(api / "tests/read_integrated_fixture.py", "# Synthetic gate reader command, no market I/O.\n")
    write(api / "tests/verify_integrated_fixture.mjs", "// Synthetic gate render command, no market I/O.\n")
    stage = tmp_path / "synthetic_stage"
    stage.mkdir()
    runtime = tmp_path / "synthetic_runtime"
    runtime.mkdir()
    return package, stage, runtime


def execute_gate(tmp_path, monkeypatch, suite=None, defect=None):
    package, stage, runtime = miniature_package(tmp_path, suite, defect)
    module = load_runner()
    monkeypatch.setattr(module, "__file__", str(package / "tools/run_checks.py"))
    monkeypatch.setattr(module, "verify", lambda _: {"status": "PASS", "scope": "SYNTHETIC_GATE_TEST_ONLY"})
    output = tmp_path / "observations"
    monkeypatch.setattr(sys, "argv", ["run_checks", "--stage-app", str(stage),
                                      "--ui-runtime", str(runtime), "--output", str(output)])
    code = module.main()
    return code, json.loads((output / "RESULTS.json").read_text())


@pytest.mark.parametrize("suite", ["stage", "api", "vue", "adaptation", "vue_actual"])
@pytest.mark.parametrize("defect", ["fewer", "skip"])
def test_zero_exit_incomplete_or_skipped_suite_cannot_pass(tmp_path, monkeypatch, suite, defect):
    code, report = execute_gate(tmp_path, monkeypatch, suite, defect)
    assert code != 0, f"{suite} with {defect} incorrectly passed despite exit-0 children"
    assert report["status"] == "FAIL_OR_NOT_RUN"
    detail = report["results"][suite]
    assert detail["exit_code"] == 0  # This is the actual defect: successful process, incomplete evidence.
    assert detail["gate"]["status"] == "FAIL"
    assert detail["gate"]["expected_tests"] == (3 if suite == "vue" else 2)


def test_every_complete_zero_skip_suite_passes(tmp_path, monkeypatch):
    code, report = execute_gate(tmp_path, monkeypatch)
    assert code == 0, report
    assert report["status"] == "PASS"
    for suite in ("stage", "api", "vue", "adaptation", "vue_actual"):
        assert report["results"][suite]["gate"]["observed_tests"] == (2 if suite == "vue" else 1)
        assert report["results"][suite]["gate"]["skipped"] == 0
        assert report["results"][suite]["gate"]["status"] == "PASS"
