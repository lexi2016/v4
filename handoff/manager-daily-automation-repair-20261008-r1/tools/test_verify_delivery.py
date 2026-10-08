"""Synthetic, temporary-directory tests for the read-only delivery verifier.

Run: python3 -m unittest discover -s tools -p 'test_verify_delivery.py' -v
"""
from contextlib import redirect_stdout
from copy import deepcopy
import difflib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import verify_delivery as verifier


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class DeliveryVerifierTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.package = self.root / "package"
        self.source = self.root / "source"
        self.package.mkdir()
        self.source.mkdir()
        self.manifest = {
            "schema_version": "v4.manager_workbench_repair.delivery.v1",
            "base_commit": "a" * 40,
            "files": [],
        }
        self.add_file("v4/example.py", "api", b"old api\n", b"new api\n")
        self.add_file("apps/web/example.ts", "web", b"old web\n", b"new web\n")

    def add_file(self, path, profile, before, after):
        destination = self.package / "after" / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(after)
        if before is not None:
            source = self.source / path
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(before)
        patch = ''.join(difflib.unified_diff(
            before.decode().splitlines(keepends=True) if before is not None else [],
            after.decode().splitlines(keepends=True),
            fromfile="a/" + path if before is not None else "/dev/null",
            tofile="b/" + path)).encode()
        patch_path = "patches/" + profile + "/" + path + ".patch"
        patch_file = self.package / patch_path
        patch_file.parent.mkdir(parents=True, exist_ok=True)
        patch_file.write_bytes(patch)
        self.manifest["files"].append({
            "path": path, "profile": profile,
            "before_sha256": sha(before) if before is not None else None,
            "after_sha256": sha(after), "after_bytes": len(after),
            "after_path": "after/" + path,
            "patch_path": patch_path, "patch_sha256": sha(patch), "patch_bytes": len(patch),
        })
        self.save_manifest()

    def save_manifest(self):
        (self.package / "source_manifest.json").write_text(json.dumps(self.manifest))

    def verify(self, profile="api", against="before"):
        return verifier.verify(self.package, self.source, profile=profile, against=against)

    def assert_failed(self, result, code):
        self.assertEqual(result["status"], "FAIL")
        self.assertIn(code, [failure["code"] for failure in result["failures"]])

    def test_before_selection_checks_all_package_files_without_source_writes(self):
        before = {str(p.relative_to(self.source)): p.read_bytes()
                  for p in self.source.rglob("*") if p.is_file()}
        result = self.verify()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["package_files_checked"], 2)
        self.assertEqual(result["source_files_checked"], 1)
        after = {str(p.relative_to(self.source)): p.read_bytes()
                 for p in self.source.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_wrong_source_preimage_fails(self):
        (self.source / "v4/example.py").write_bytes(b"parallel edit\n")
        self.assert_failed(self.verify(), "SOURCE_SHA_MISMATCH")

    def test_hk_child_preimage_cannot_be_substituted_by_api_layer(self):
        self.add_file("ops/panel.py", "hk_child", b"actual hk child\n", b"repaired hk child\n")
        self.assertEqual(self.verify("hk_child")["status"], "PASS")
        # Both releases may have this path, but the API/canonical bytes are
        # not the actual child preimage and must not pass the child gate.
        (self.source / "ops/panel.py").write_bytes(b"other release panel\n")
        self.assert_failed(self.verify("hk_child"), "SOURCE_SHA_MISMATCH")
        self.assertEqual(self.verify("api")["status"], "PASS")

    def test_hk_upstream_uses_the_bound_updater_package_root(self):
        self.add_file("shared_data/hk_daily_supplement.py", "hk_upstream",
                      b"bound upstream before\n", b"bound upstream after\n")
        self.assertEqual(self.verify("hk_upstream")["status"], "PASS")
        original = self.source / "shared_data/hk_daily_supplement.py"
        guessed = self.source / "upstreams/v3_shared_data/shared_data/hk_daily_supplement.py"
        guessed.parent.mkdir(parents=True)
        original.rename(guessed)
        self.assert_failed(self.verify("hk_upstream"), "FILE_MISSING")

    def test_after_mode_uses_after_identity(self):
        for item in self.manifest["files"]:
            (self.source / item["path"]).write_bytes((self.package / item["after_path"]).read_bytes())
        self.assertEqual(self.verify("all", "after")["status"], "PASS")
        self.assert_failed(self.verify(), "SOURCE_SHA_MISMATCH")

    def test_added_before_file_must_be_absent_including_dangling_symlink(self):
        self.add_file("tests/new.py", "tests", None, b"test\n")
        self.assertEqual(self.verify("tests")["status"], "PASS")
        path = self.source / "tests/new.py"
        path.parent.mkdir()
        path.write_bytes(b"preexisting\n")
        self.assert_failed(self.verify("tests"), "SOURCE_EXPECTED_ABSENT")
        path.unlink()
        path.symlink_to(self.root / "missing.py")
        self.assert_failed(self.verify("tests"), "SYMLINK_NOT_ALLOWED")

    def test_unselected_package_after_file_is_still_verified(self):
        (self.package / "after/apps/web/example.ts").write_bytes(b"bad web\n")
        self.assert_failed(self.verify("api"), "PACKAGE_SHA_MISMATCH")

    def test_after_size_is_independent_of_hash(self):
        self.manifest["files"][0]["after_bytes"] += 1
        self.save_manifest()
        self.assert_failed(self.verify(), "PACKAGE_SIZE_MISMATCH")

    def test_unselected_patch_is_verified_before_any_application(self):
        patch = self.package / self.manifest["files"][1]["patch_path"]
        patch.write_bytes(patch.read_bytes() + b"undeclared patch content\n")
        self.assert_failed(self.verify("api"), "PACKAGE_PATCH_SHA_MISMATCH")

    def test_patch_size_is_independent_of_hash(self):
        self.manifest["files"][0]["patch_bytes"] += 1
        self.save_manifest()
        self.assert_failed(self.verify(), "PACKAGE_PATCH_SIZE_MISMATCH")

    def test_patch_manifest_requires_identity_and_safe_path(self):
        original = deepcopy(self.manifest)
        for field, value in (("patch_sha256", None), ("patch_bytes", -1),
                             ("patch_path", "patches/../outside.patch"),
                             ("patch_path", "after/misplaced.patch")):
            with self.subTest(field=field, value=value):
                self.manifest = deepcopy(original)
                self.manifest["files"][0][field] = value
                self.save_manifest()
                self.assert_failed(self.verify(), "MANIFEST_INVALID")

    def test_incremental_patch_is_also_bound_and_verified(self):
        row = self.manifest["files"][0]
        raw = (self.package / row["patch_path"]).read_bytes()
        incremental = self.package / "patches/incremental/v4/example.py.patch"
        incremental.parent.mkdir(parents=True)
        incremental.write_bytes(raw)
        row.update(incremental_patch_path=str(incremental.relative_to(self.package)),
                   incremental_patch_sha256=sha(raw), incremental_patch_bytes=len(raw))
        self.save_manifest()
        self.assertEqual(self.verify()["status"], "PASS")
        incremental.write_bytes(raw + b"extra\n")
        self.assert_failed(self.verify(), "PACKAGE_PATCH_SHA_MISMATCH")

    def test_patch_symlink_is_rejected_even_with_matching_bytes(self):
        patch = self.package / self.manifest["files"][0]["patch_path"]
        external = self.root / "external.patch"
        external.write_bytes(patch.read_bytes())
        patch.unlink()
        patch.symlink_to(external)
        self.assert_failed(self.verify(), "SYMLINK_NOT_ALLOWED")

    def test_scheduler_prerequisite_payload_prefix_is_profile_bound(self):
        self.add_file("ops/daemon.py", "scheduler_prerequisite", b"old daemon\n", b"new daemon\n")
        item = self.manifest["files"][-1]
        target = self.package / "prerequisites/scheduler/ops/daemon.py"
        target.parent.mkdir(parents=True)
        (self.package / item["after_path"]).rename(target)
        item["after_path"] = "prerequisites/scheduler/ops/daemon.py"
        self.save_manifest()
        self.assertEqual(self.verify("scheduler_prerequisite")["status"], "PASS")
        item["profile"] = "api"
        self.save_manifest()
        self.assert_failed(self.verify(), "MANIFEST_INVALID")

    def test_manifest_rejects_unsafe_or_noncanonical_relative_paths(self):
        original = deepcopy(self.manifest)
        cases = [("path", value) for value in (
            "../outside.py", "/absolute.py", "v4/../example.py", "v4//example.py",
            "v4/./example.py", "v4\\example.py", "v4/example.py/", "")]
        cases += [("after_path", "elsewhere/example.py"), ("after_path", "after/../example.py")]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                self.manifest = deepcopy(original)
                self.manifest["files"][0][field] = value
                self.save_manifest()
                self.assert_failed(self.verify(), "MANIFEST_INVALID")

    def test_package_file_or_parent_symlink_is_rejected(self):
        file = self.package / "after/v4/example.py"
        external = self.root / "external.py"
        external.write_bytes(file.read_bytes())
        file.unlink()
        file.symlink_to(external)
        self.assert_failed(self.verify(), "SYMLINK_NOT_ALLOWED")
        file.unlink()
        file.parent.rmdir()
        directory = self.root / "external"
        directory.mkdir()
        (directory / "example.py").write_bytes(external.read_bytes())
        file.parent.symlink_to(directory, target_is_directory=True)
        self.assert_failed(self.verify(), "SYMLINK_NOT_ALLOWED")

    def test_source_file_and_root_symlinks_are_rejected(self):
        file = self.source / "v4/example.py"
        external = self.root / "source-external.py"
        external.write_bytes(file.read_bytes())
        file.unlink()
        file.symlink_to(external)
        self.assert_failed(self.verify(), "SYMLINK_NOT_ALLOWED")
        alias = self.root / "source-alias"
        alias.symlink_to(self.source, target_is_directory=True)
        self.assert_failed(verifier.verify(self.package, alias, profile="api"), "SYMLINK_NOT_ALLOWED")

    def test_manifest_symlink_and_duplicate_record_are_rejected(self):
        path = self.package / "source_manifest.json"
        external = self.root / "manifest.json"
        external.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(external)
        self.assert_failed(self.verify(), "SYMLINK_NOT_ALLOWED")
        path.unlink()
        self.manifest["files"].append(deepcopy(self.manifest["files"][0]))
        self.save_manifest()
        self.assert_failed(self.verify(), "MANIFEST_INVALID")

    def test_preserve_pins_are_profile_specific_and_never_relaxed(self):
        path = self.source / "ops/launch.sh"
        path.parent.mkdir()
        path.write_bytes(b"preserved launcher\n")
        self.manifest["preserve"] = [{
            "profile": "scheduler_prerequisite", "path": "ops/launch.sh",
            "sha256": sha(path.read_bytes()),
        }]
        self.save_manifest()
        self.assertEqual(self.verify("scheduler_prerequisite")["status"], "PASS")
        path.write_bytes(b"wrong launcher\n")
        self.assertEqual(self.verify("api")["status"], "PASS")
        self.assert_failed(self.verify("scheduler_prerequisite"), "PRESERVE_SHA_MISMATCH")

    def test_report_is_exclusive_and_source_tree_stays_read_only(self):
        report = self.root / "new-report.json"
        args = ["--package-root", str(self.package), "--source-root", str(self.source),
                "--profile", "api", "--report", str(report)]
        with redirect_stdout(io.StringIO()):
            self.assertEqual(verifier.main(args), 0)
        original = report.read_bytes()
        with redirect_stdout(io.StringIO()) as stdout:
            self.assertNotEqual(verifier.main(args), 0)
        self.assertEqual(report.read_bytes(), original)
        self.assert_failed(json.loads(stdout.getvalue()), "REPORT_WRITE_FAILED")
        source_report = self.source / "new-report.json"
        args[-1] = str(source_report)
        with redirect_stdout(io.StringIO()) as stdout:
            self.assertNotEqual(verifier.main(args), 0)
        self.assertFalse(source_report.exists())
        self.assert_failed(json.loads(stdout.getvalue()), "REPORT_INSIDE_SOURCE_ROOT")

    def run_cli(self, source, report):
        return subprocess.run([
            sys.executable, "-B", str(Path(verifier.__file__).resolve()),
            "--package-root", str(self.package), "--source-root", str(source),
            "--profile", "api", "--report", str(report),
        ], cwd=self.root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def test_cli_source_alias_cannot_create_report_in_real_source(self):
        alias = self.root / "source-alias"
        alias.symlink_to(self.source, target_is_directory=True)
        report = self.source / "new-report.json"
        before = {str(path.relative_to(self.source)): path.read_bytes()
                  for path in self.source.rglob("*") if path.is_file()}
        result = self.run_cli(alias, report)
        self.assertNotEqual(result.returncode, 0)
        self.assert_failed(json.loads(result.stdout), "SYMLINK_NOT_ALLOWED")
        self.assertFalse(report.exists(), "failed source verification must not allow a source-tree report write")
        after = {str(path.relative_to(self.source)): path.read_bytes()
                 for path in self.source.rglob("*") if path.is_file()}
        self.assertEqual(after, before)

    def test_cli_report_beneath_source_ancestor_is_rejected(self):
        report = self.source / "v4/nested-report.json"
        result = self.run_cli(self.source, report)
        self.assertNotEqual(result.returncode, 0)
        self.assert_failed(json.loads(result.stdout), "REPORT_INSIDE_SOURCE_ROOT")
        self.assertFalse(report.exists())

    def test_cli_report_outside_source_is_created_exclusively(self):
        report = self.root / "outside-report.json"
        result = self.run_cli(self.source, report)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "PASS")
        original = report.read_bytes()
        repeated = self.run_cli(self.source, report)
        self.assertNotEqual(repeated.returncode, 0)
        self.assert_failed(json.loads(repeated.stdout), "REPORT_WRITE_FAILED")
        self.assertEqual(report.read_bytes(), original)

    def test_cli_source_mismatch_may_write_failure_report_outside_source(self):
        (self.source / "v4/example.py").write_bytes(b"parallel edit\n")
        report = self.root / "outside-failure-report.json"
        result = self.run_cli(self.source, report)
        self.assertNotEqual(result.returncode, 0)
        self.assert_failed(json.loads(result.stdout), "SOURCE_SHA_MISMATCH")
        self.assertEqual(json.loads(report.read_bytes()), json.loads(result.stdout))


if __name__ == "__main__":
    unittest.main()
