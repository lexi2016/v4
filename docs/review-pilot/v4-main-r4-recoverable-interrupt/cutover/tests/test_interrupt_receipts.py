from contextlib import ExitStack, contextmanager
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_main_only_cutover as base

CUTOVER = base.CUTOVER


class InterruptReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="v4-r4-interrupt-")
        self.root = Path(self.temp.name).resolve()
        self.fixture = base.MainOnlyCutoverTests()
        self.fixture.root = self.root

    def tearDown(self):
        self.temp.cleanup()

    def cli(self, action, invoke, filename="receipt.json"):
        receipt = self.root / filename
        argv = ["main_only_cutover.py", action, "--plan", "fixture-plan",
                "--plan-sha256", "0"*64, "--authorization", "fixture-auth",
                "--authorization-sha256", "0"*64, "--chat-review-receipt", "fixture-chat",
                "--chat-review-sha256", "0"*64, "--receipt", str(receipt)]
        with patch.object(sys, "argv", argv), patch.object(CUTOVER, "run", side_effect=lambda args: invoke()):
            with self.assertRaises(KeyboardInterrupt):
                CUTOVER.main()
        self.assertTrue(receipt.is_file())
        self.assertEqual(receipt.stat().st_mode & 0o777, 0o600)
        return json.loads(receipt.read_bytes())

    def activation_fixture(self):
        refs, _, new, _ = self.fixture.receipts()
        pins = self.root / "managed-pins.json"
        sources = []
        for i in range(95):
            source = self.root / f"source-{i}"
            source.write_bytes(str(i).encode())
            sources.append({"path":str(source),"sha256":base.sha(source.read_bytes())})
        pins_sha = base.write_json(pins, {"source_bindings":sources})
        review = self.root/"review.json"
        review_sha = base.write_json(review, {"verdict":"PASS","roles":{"main":{
            "candidate_release_id":"release-r5","candidate_manifest_sha256":"3"*64,
            "candidate_plist_sha256":"4"*64,"delta_files":[]}}})
        candidate = self.root/"candidate"
        candidate.mkdir()
        plan = {"release_id":"release-r5","target_date":"20261123",
                "approved_candidate_parent":str(self.root),
                "candidate_pins":{"path":str(pins),"sha256":pins_sha},"admission_evidence":refs,
                "controller_plan":{"roles":[{"role":"main","candidate_release_id":"release-r5",
                                             "candidate_plist":str(candidate/"launchd.plist")}],
                                   "review_approval":{"path":str(review),"sha256":review_sha}}}
        controller = base.FakeController(self.root, [])
        return plan, controller

    def test_cli_persists_recorded_forward_recovery_before_interrupt_leaves(self):
        for status in ("ROLLED_BACK","ROLLBACK_INCOMPLETE"):
            with self.subTest(status=status):
                root = self.root/status
                root.mkdir()
                self.fixture.root=root
                original_root=self.root
                self.root=root
                try:
                    plan, controller=self.activation_fixture()
                    def interrupt(roles, controller_plan, result):
                        result.update(status=status,error="KeyboardInterrupt:original",
                                      roles={"main":{"rollback_error":"kept detail"}})
                        raise KeyboardInterrupt("original")
                    controller.activate=interrupt
                    invoke=lambda: CUTOVER.activate_main(plan,controller,lock_adapter=lambda *a:None,
                        qfq_adapter=lambda *a:{"status":"PASS"},preflight_adapter=lambda *a:{"status":"PASS"})
                    result=self.cli("activate",invoke)
                    self.assertEqual(result["status"],status)
                    self.assertEqual(result["roles"]["main"]["rollback_error"],"kept detail")
                    self.assertEqual(result["interruption"]["type"],"KeyboardInterrupt")
                finally:
                    self.root=original_root
                    self.fixture.root=original_root

    def scenario(self, action, stage):
        scenario_root=self.root/f"{action}-{stage}"
        scenario_root.mkdir()
        receipt = scenario_root/"receipt.json"
        command=[sys.executable,"-I","-S","-B","-X",f"pycache_prefix={CUTOVER.PYTHON_CACHE_PREFIX}",
                 str(Path(__file__).resolve()),"--scenario",action,stage,str(receipt)]
        result=subprocess.run(command,capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,130,result.stdout+result.stderr)
        observed=json.loads(receipt.read_bytes())
        details=json.loads(receipt.with_suffix(".observed.json").read_bytes())
        archive=os.environ.get("V4_INTERRUPT_TEST_EVIDENCE_ROOT")
        if archive:
            destination=Path(archive)
            destination.mkdir(parents=True,exist_ok=True)
            for suffix,path in (("receipt",receipt),("observed",receipt.with_suffix(".observed.json"))):
                with (destination/f"{action}-{stage}-{suffix}.json").open("xb") as output:
                    output.write(path.read_bytes())
        self.assertEqual(observed["interruption"]["type"],"KeyboardInterrupt")
        self.assertEqual(details["original_message"],"injected-"+stage)
        self.assertTrue(details["actual_loader_source"].endswith("/cutover/switch_reviewed_roles.py"))
        self.assertEqual(details["actual_loader_sha256"],CUTOVER.CONTROLLER_SHA256)
        self.assertEqual(details["final_mode"],"0644")
        self.assertTrue(details["receipt_was_written_before_interrupt_propagated"])
        if "final_state" in observed:
            self.assertEqual(observed["final_state"]["plist_sha256"],details["final_sha256"])
            if observed["final_state"]["loaded_identity"] != "UNKNOWN":
                self.assertEqual(observed["final_state"]["loaded"],details["loaded"])
        self.assertLessEqual(details["recovery_bootstraps"],1)
        return observed,details

    def test_real_loader_forward_interrupts_unload_cas_bootstrap_and_recorded_terminals(self):
        for stage in ("unload","cas","bootstrap","ROLLED_BACK","ROLLBACK_INCOMPLETE"):
            with self.subTest(stage=stage):
                result,details=self.scenario("activate",stage)
                if stage in ("ROLLED_BACK","ROLLBACK_INCOMPLETE"):
                    self.assertEqual(result["status"],stage)
                    self.assertEqual(result["roles"]["main"]["rollback_error"],"immutable recovery detail")
                else:
                    self.assertEqual(result["status"],"ROLLED_BACK")
                    self.assertEqual(result["final_state"]["plist_identity"],"OLD")
                    self.assertEqual(result["final_state"]["loaded_identity"],"OLD")

    def test_real_loader_reverse_interrupts_unload_cas_bootstrap_and_recovery(self):
        for stage in ("unload","cas","bootstrap","recovery","double_interrupt","primary_readback",
                      "terminal_restored","terminal_still_loaded"):
            with self.subTest(stage=stage):
                result,details=self.scenario("rollback",stage)
                self.assertNotEqual(result["status"],"RESTORED_MAIN_ONLY")
                if stage in ("recovery","double_interrupt"):
                    self.assertEqual(result["status"],"ROLLBACK_INCOMPLETE")
                    self.assertIn("KeyboardInterrupt",result["recovery_error"])
                    if stage=="double_interrupt":
                        self.assertIn("injected-double_interrupt",result["error"])
                        self.assertIn("second interruption",result["recovery_error"])
                elif stage=="primary_readback":
                    self.assertEqual(result["interruption"]["message"],"injected-primary_readback")
                    self.assertIn("second readback interruption",result["final_state"]["loaded_read_error"])
                    self.assertEqual(result["status"],"ROLLBACK_INCOMPLETE")
                elif stage.startswith("terminal_"):
                    self.assertEqual(result["status"],"ROLLBACK_INCOMPLETE")
                    self.assertTrue(result["final_readback_mismatch"])
                    self.assertIn("KeyboardInterrupt",result["final_state"]["loaded_read_error"])
                    self.assertTrue(result["status_before_final_readback"].startswith(
                        "ROLLBACK_FAILED_CURRENT_CONFIGURATION_"))
                else:
                    self.assertEqual(result["final_state"]["plist_identity"],result["final_state"]["loaded_identity"])
                expected_phase={"unload":"UNLOADING_MAIN","cas":"RESTORING_MAIN_PLIST",
                    "bootstrap":"BOOTSTRAPPING_MAIN","double_interrupt":"BOOTSTRAPPING_MAIN",
                    "primary_readback":"BOOTSTRAPPING_MAIN","recovery":"ROLLBACK_RECOVERY_BOOTSTRAP",
                    "terminal_restored":"ROLLBACK_FINAL_READBACK","terminal_still_loaded":"ROLLBACK_FINAL_READBACK"}
                self.assertEqual(result["interruption"]["phase"],expected_phase[stage])

    def test_receipt_failure_propagates_original_interrupt_with_durable_failure_notice(self):
        original=KeyboardInterrupt("original-write-failure")
        original.v4_cutover_result={"status":"ROLLED_BACK","error":"original detail"}
        receipt=self.root/"unwritable.json"
        argv=["main_only_cutover.py","activate","--plan","p","--plan-sha256","x",
              "--authorization","a","--authorization-sha256","x","--chat-review-receipt","c",
              "--chat-review-sha256","x","--receipt",str(receipt)]
        with (patch.object(sys,"argv",argv),patch.object(CUTOVER,"run",side_effect=original),
              patch.object(CUTOVER.os,"write",side_effect=OSError("disk-full")),
              patch.object(sys,"stderr") as stderr):
            with self.assertRaises(KeyboardInterrupt) as caught:
                CUTOVER.main()
        self.assertIs(caught.exception,original)
        self.assertIn("RECEIPT_WRITE_FAILED:OSError:disk-full",original.__notes__)
        self.assertIn("original detail","".join(call.args[0] for call in stderr.write.call_args_list))
        self.assertEqual(receipt.read_bytes(),b"")

        second=self.root/"notice-also-failed.json"
        argv[-1]=str(second)
        with (patch.object(sys,"argv",argv),patch.object(CUTOVER,"run",side_effect=original),
              patch.object(CUTOVER.os,"write",side_effect=OSError("disk-full")),
              patch.object(sys,"stderr") as stderr):
            stderr.write.side_effect=OSError("stderr-closed")
            with self.assertRaises(KeyboardInterrupt) as caught:
                CUTOVER.main()
        self.assertIs(caught.exception,original)
        self.assertTrue(any(note.startswith("RECEIPT_FAILURE_NOTICE_FAILED:") for note in original.__notes__))
        with patch.object(sys,"argv",argv),patch.object(CUTOVER,"run") as run:
            with self.assertRaisesRegex(SystemExit,"RECEIPT_PATH_MUST_BE_ABSOLUTE_NEW_FILE"):
                CUTOVER.main()
        run.assert_not_called()
        self.assertEqual(receipt.read_bytes(),b"")

    def test_system_exit_zero_is_recorded_as_failed_interrupted_operation(self):
        receipt=self.root/"system-exit.json"
        original=SystemExit(0)
        argv=["main_only_cutover.py","rollback","--plan","p","--plan-sha256","x",
              "--authorization","a","--authorization-sha256","x","--chat-review-receipt","c",
              "--chat-review-sha256","x","--receipt",str(receipt)]
        with patch.object(sys,"argv",argv),patch.object(CUTOVER,"run",side_effect=original):
            with self.assertRaises(SystemExit) as caught:
                CUTOVER.main()
        self.assertIs(caught.exception,original)
        self.assertEqual(caught.exception.code,2)
        data=json.loads(receipt.read_bytes())
        self.assertEqual(data["status"],"INTERRUPTED")
        self.assertEqual(data["interruption"]["original_exit_code"],0)
        self.assertEqual(data["interruption"]["effective_exit_code"],2)
        before=receipt.read_bytes()
        with patch.object(sys,"argv",argv),patch.object(CUTOVER,"run") as run:
            with self.assertRaisesRegex(SystemExit,"RECEIPT_PATH_MUST_BE_ABSOLUTE_NEW_FILE"):
                CUTOVER.main()
        run.assert_not_called()
        self.assertEqual(receipt.read_bytes(),before)

    def test_reverse_double_unknown_final_readback_cannot_preserve_restored_status(self):
        plan,controller,live,old_raw,new_raw,_,_=self.fixture.rollback_fixture(fail_bootstrap_count=1)
        before={"plist_identity":"OLD","loaded_identity":"ABSENT","loaded":None}
        unknown={"plist_identity":"UNKNOWN","loaded_identity":"UNKNOWN",
                 "plist_read_error":"OSError:read failed","loaded_read_error":"OSError:observation failed"}
        with patch.object(CUTOVER,"final_main_state",side_effect=[before,unknown]):
            result=CUTOVER.rollback_main(plan,controller,lock_adapter=lambda *a:None)
        self.assertEqual(result["status_before_final_readback"],"ROLLBACK_FAILED_CURRENT_CONFIGURATION_RESTORED")
        self.assertEqual(result["status"],"ROLLBACK_INCOMPLETE")
        self.assertTrue(result["final_readback_mismatch"])
        self.assertEqual(result["final_state"],unknown)

    def test_actual_loader_retains_forward_and_reverse_success_on_lock_release_interrupt(self):
        for action in ("activate","rollback"):
            with self.subTest(action=action):
                result,details=self.scenario(action,"lock_release")
                expected="ACTIVATED_MAIN_ONLY" if action=="activate" else "RESTORED_MAIN_ONLY"
                self.assertEqual(result["status"],expected)
                self.assertEqual(result["interruption"]["phase"],"LOCK_RELEASE")
                self.assertIn("KeyboardInterrupt:injected-lock_release",result["lock_release_errors"])

    def test_actual_loader_lock_release_secondary_interrupt_keeps_first(self):
        result,details=self.scenario("rollback","lock_release_secondary")
        self.assertEqual(result["status"],"ROLLBACK_FAILED_CURRENT_CONFIGURATION_RESTORED")
        self.assertEqual(result["interruption"]["message"],"injected-lock_release_secondary")
        self.assertEqual(result["interruption"]["phase"],"BOOTSTRAPPING_MAIN")
        self.assertIn("KeyboardInterrupt:secondary lock release",result["lock_release_errors"])

    def test_lock_release_runtime_error_retains_known_result_and_nonzero_cli_return(self):
        receipt=self.root/"lock-runtime-error.json"
        result={"status":"RESTORED_MAIN_ONLY","roles":{"main":{"restored":"exact fixture identity"}}}
        @contextmanager
        def bad_release():
            yield
            raise RuntimeError("lock release failed")
        def invoke(args):
            with CUTOVER.ResultExitStack(result) as stack:
                stack.enter_context(bad_release())
                return result
        argv=["main_only_cutover.py","rollback","--plan","p","--plan-sha256","x",
              "--authorization","a","--authorization-sha256","x","--chat-review-receipt","c",
              "--chat-review-sha256","x","--receipt",str(receipt)]
        with patch.object(sys,"argv",argv),patch.object(CUTOVER,"run",side_effect=invoke):
            self.assertEqual(CUTOVER.main(),2)
        actual=json.loads(receipt.read_bytes())
        self.assertEqual(actual["status"],"RESTORED_MAIN_ONLY")
        self.assertEqual(actual["roles"],result["roles"])
        self.assertIn("RuntimeError:lock release failed",actual["lock_release_errors"])
        self.assertEqual(actual["cli_failure"],"RuntimeError:lock release failed")


def run_scenario(action,stage,receipt):
    test=InterruptReceiptTests()
    test.root=receipt.parent
    test.fixture=base.MainOnlyCutoverTests()
    test.fixture.root=test.root
    actual_loader=CUTOVER.load_controller
    original_activate=CUTOVER.activate_main
    original_rollback=CUTOVER.rollback_main
    row_details={}
    triggered=False
    bootstrap_count=0
    loaded_count=0
    error=KeyboardInterrupt("injected-"+stage)
    if action=="rollback":
        plan,fake,live,old_raw,new_raw,_,_=test.fixture.rollback_fixture()
        role=None
    else:
        plan,stub=test.activation_fixture()
        live=stub.LAUNCH_AGENTS/"com.lexi.v4.scheduler.plist"
        old_cfg={"WorkingDirectory":str(test.root/"old-app"),
                 "EnvironmentVariables":{"V4_RELEASE_MANIFEST_SHA256":"a"*64}}
        new_cfg={"WorkingDirectory":str(test.root/"new-app"),
                 "EnvironmentVariables":{"V4_RELEASE_MANIFEST_SHA256":"b"*64}}
        old_raw=plistlib.dumps(old_cfg);new_raw=plistlib.dumps(new_cfg)
        live.write_bytes(old_raw);live.chmod(0o644)
        fake=base.FakeRollbackController(stub.LAUNCH_AGENTS,live,new_cfg,"b"*64)
        fake.state={"cwd":old_cfg["WorkingDirectory"],"path":str(live),
                    "loaded_manifest_sha256":"a"*64,"pid":27}
        role={"role":"main","label":"com.lexi.v4.scheduler","path":live,
              "old":old_raw,"new":new_raw,"old_cfg":old_cfg,"new_cfg":new_cfg,
              "old_cwd":old_cfg["WorkingDirectory"],"new_cwd":new_cfg["WorkingDirectory"],
              "before":dict(fake.state)}

    def inject(name,callback,*args):
        nonlocal triggered,bootstrap_count
        if name=="bootstrap":
            bootstrap_count+=1
            if stage=="double_interrupt":
                if bootstrap_count==1:
                    raise error
                raise KeyboardInterrupt("second interruption")
            if stage=="primary_readback" and bootstrap_count==1:
                raise error
            if stage=="lock_release_secondary" and bootstrap_count==1:
                raise error
            if stage=="terminal_restored" and bootstrap_count==1:
                raise RuntimeError("first bootstrap failed")
            if stage=="terminal_still_loaded" and bootstrap_count==1:
                callback(*args)
                raise RuntimeError("bootstrap started but reported failure")
            if stage=="recovery":
                if bootstrap_count==1:
                    raise RuntimeError("first bootstrap failed")
                if bootstrap_count==2:
                    triggered=True
                    raise error
        value=callback(*args)
        if not triggered and stage==name:
            triggered=True
            raise error
        return value

    def loader():
        controller=actual_loader()
        row_details.update(actual_loader_source=controller.__file__,
                           actual_loader_sha256=base.sha(Path(controller.__file__).read_bytes()))
        controller.LAUNCH_AGENTS=fake.LAUNCH_AGENTS
        controller.DOMAIN="gui/test"
        controller.owned_interprocess_lock=fake.owned_interprocess_lock
        if stage in ("lock_release","lock_release_secondary"):
            @contextmanager
            def interrupting_lock(*args,**kwargs):
                try:
                    yield
                finally:
                    if stage=="lock_release":
                        raise error
                    raise KeyboardInterrupt("secondary lock release")
            controller.owned_interprocess_lock=interrupting_lock
        controller.load_role=lambda row,approved:role
        controller.role_idle=lambda role:None
        controller.scheduler_idle=fake.scheduler_idle
        def loaded(label):
            nonlocal loaded_count
            loaded_count+=1
            if stage=="primary_readback" and loaded_count==4:
                raise KeyboardInterrupt("second readback interruption")
            if stage.startswith("terminal_") and loaded_count==4:
                raise error
            return fake.loaded(label)
        controller.loaded=loaded
        controller.verify_loaded=fake.verify_loaded
        controller.unload=lambda row:inject("unload",fake.unload,row)
        controller.write_atomic=lambda path,raw,previous:inject("cas",fake.write_atomic,path,raw,previous)
        controller.run_ctl=lambda a,d,p:inject("bootstrap",fake.run_ctl,a,d,p)
        if stage in ("ROLLED_BACK","ROLLBACK_INCOMPLETE"):
            def terminal(roles,selected,result):
                result.update(status=stage,error="original terminal detail",
                              roles={"main":{"rollback_error":"immutable recovery detail"}})
                raise error
            controller.activate=terminal
        return controller

    files={}
    for name,value in (("plan",plan),("authorization",{}),("chat-review-receipt",{})):
        path=test.root/(name+".json")
        files[name]=(path,base.write_json(path,value))
    argv=["main_only_cutover.py",action]
    for name,(path,digest) in files.items():
        argv.extend(("--"+name,str(path),"--"+({"plan":"plan-sha256","authorization":"authorization-sha256",
                    "chat-review-receipt":"chat-review-sha256"}[name]),digest))
    argv.extend(("--receipt",str(receipt)))
    with ExitStack() as stack:
        stack.enter_context(patch.object(sys,"argv",argv))
        stack.enter_context(patch.object(CUTOVER,"validate_plan",return_value=None))
        stack.enter_context(patch.object(CUTOVER,"check_activation_authorization",return_value=None))
        stack.enter_context(patch.object(CUTOVER,"check_rollback_authorization",return_value=None))
        stack.enter_context(patch.object(CUTOVER,"load_controller",side_effect=loader))
        stack.enter_context(patch.object(CUTOVER,"activate_main",side_effect=lambda p,c:original_activate(
            p,c,lock_adapter=lambda *a:None,qfq_adapter=lambda *a:{"status":"PASS"},
            preflight_adapter=lambda *a:{"status":"PASS"})))
        stack.enter_context(patch.object(CUTOVER,"rollback_main",side_effect=lambda p,c:original_rollback(
            p,c,lock_adapter=lambda *a:None)))
        try:
            CUTOVER.main()
        except KeyboardInterrupt as caught:
            assert caught is error
            row_details.update(original_message=str(caught),final_sha256=base.sha(live.read_bytes()),
                final_mode=format(live.stat().st_mode&0o777,"04o"),loaded=fake.loaded("com.lexi.v4.scheduler"),
                recovery_bootstraps=max(0,bootstrap_count-1) if stage in (
                    "bootstrap","recovery","double_interrupt","primary_readback",
                    "terminal_restored","terminal_still_loaded","lock_release_secondary",
                    "lock_release") else bootstrap_count,
                receipt_was_written_before_interrupt_propagated=receipt.is_file())
            receipt.with_suffix(".observed.json").write_text(json.dumps(row_details,indent=2))
            return 130
    raise AssertionError("Scenario did not propagate its original interruption")


if __name__ == "__main__":
    if len(sys.argv)>1 and sys.argv[1]=="--scenario":
        raise SystemExit(run_scenario(sys.argv[2],sys.argv[3],Path(sys.argv[4])))
    unittest.main()
