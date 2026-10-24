"""Temp-file regression for exact publication-stage content-SHA binding."""

from __future__ import annotations

import ast
import hashlib
import pathlib
import tempfile
import unittest


COLLECTOR = pathlib.Path(__file__).with_name("collect_actual_panel.py")


def load_stage_sha_functions():
    """Load the two production functions without running the collector."""
    module = ast.parse(COLLECTOR.read_text(encoding="utf-8"), filename=str(COLLECTOR))
    wanted = {"sha", "require_publication_stage_sha"}
    functions = [
        node
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in wanted
    ]
    if {node.name for node in functions} != wanted:
        raise AssertionError("COLLECTOR_STAGE_SHA_FUNCTIONS_MISSING")
    namespace = {"hashlib": hashlib, "pathlib": pathlib}
    code = compile(ast.Module(body=functions, type_ignores=[]), str(COLLECTOR), "exec")
    exec(code, namespace)
    return namespace["sha"], namespace["require_publication_stage_sha"]


class PublicationStageShaTests(unittest.TestCase):
    def test_matching_selector_and_backtest_bytes_pass(self):
        sha, require_stage_sha = load_stage_sha_functions()
        with tempfile.TemporaryDirectory(prefix="panel-d23-r3-stage-sha-") as temp:
            root = pathlib.Path(temp)
            outputs = {}
            for role in ("selector", "backtest"):
                panel = root / (role + ".parquet")
                panel.write_bytes((role + " stage bytes").encode("ascii"))
                outputs[role] = {"path": str(panel), "sha256": sha(panel)}

            for role in ("selector", "backtest"):
                panel = pathlib.Path(outputs[role]["path"])
                self.assertEqual(sha(panel), outputs[role]["sha256"])
                self.assertEqual(
                    require_stage_sha(role, panel, outputs),
                    outputs[role]["sha256"],
                )

    def test_same_path_replacement_rejected_for_each_role_even_if_lane_sha_refreshes(self):
        sha, require_stage_sha = load_stage_sha_functions()
        for role in ("selector", "backtest"):
            with self.subTest(role=role), tempfile.TemporaryDirectory(
                prefix="panel-d23-r3-stage-sha-"
            ) as temp:
                panel = pathlib.Path(temp) / (role + ".parquet")
                original = (role + " reviewed stage bytes").encode("ascii")
                replacement = (role + " replacement bytes").encode("ascii")
                panel.write_bytes(original)
                outputs = {
                    role: {"path": str(panel), "sha256": hashlib.sha256(original).hexdigest()}
                }

                panel.write_bytes(replacement)
                refreshed_lane_receipt = {
                    role: {"path": str(panel), "sha256": sha(panel)}
                }
                refreshed_lane_sha = refreshed_lane_receipt[role]["sha256"]
                self.assertEqual(refreshed_lane_sha, hashlib.sha256(replacement).hexdigest())
                self.assertEqual(outputs[role]["path"], str(panel))
                self.assertNotEqual(refreshed_lane_sha, outputs[role]["sha256"])
                with self.assertRaisesRegex(
                    RuntimeError,
                    "PUBLICATION_STAGE_SHA_MISMATCH:" + role,
                ):
                    require_stage_sha(role, panel, outputs)


if __name__ == "__main__":
    unittest.main()
