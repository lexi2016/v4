"""Run only the final state-race delta against actual candidate module bytes."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', required=True, type=Path)
    parser.add_argument('--evidence', required=True, type=Path)
    parser.add_argument('--integrity', action='store_true', help='Only the two authorized receipt state/identity regressions')
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).resolve().parents[3]
    candidate = json.loads((args.candidate / 'candidate_receipt.json').read_bytes())
    relative = 'infrastructure/report_evidence_sidecar.py'
    expected = candidate['report_source_files'][relative]['sha256']
    roles = {}
    for role, row in candidate['roles'].items():
        module = Path(row['app_root']) / relative
        actual = hashlib.sha256(module.read_bytes()).hexdigest()
        assert actual == expected, (role, actual, expected)
        roles[role] = {'path': str(module), 'sha256': actual}
    names = [
        'test_unknown_ps_is_busy_and_does_not_overwrite_worker_terminal',
        'test_orphan_check_uses_same_consumer_lock_without_waiting',
        'test_confirmed_dead_fails_once_and_terminal_states_are_immutable',
        'test_pid_probe_distinguishes_unknown_from_observed_dead',
    ]
    if args.integrity:
        names = ['test_unknown_existing_receipt_is_preserved_at_all_read_boundaries', 'test_mismatched_receipt_job_id_is_refused_at_all_read_boundaries']
    app = Path(candidate['roles']['main']['app_root'])
    code = "import sys,unittest;sys.path[:0]=" + repr([str(app), str(source)]) + ";from infrastructure import report_evidence_sidecar as module;assert module.__file__==" + repr(str(app / relative)) + ";suite=unittest.TestLoader().loadTestsFromNames(" + repr(['tests.test_report_evidence_sidecar.SidecarCompatibilityTests.' + name for name in names]) + ");result=unittest.TextTestRunner(verbosity=2).run(suite);sys.exit(not result.wasSuccessful())"
    run = subprocess.run([sys.executable, '-B', '-c', code], cwd=app, capture_output=True, text=True)
    (args.evidence / 'targeted-tests.log').write_text(run.stdout + run.stderr)
    result = {'status': 'PASS' if run.returncode == 0 else 'FAIL', 'candidate': str(args.candidate), 'source_commit': candidate['source_commit'], 'report_source_ref': candidate['report_source_ref'], 'roles': roles, 'tests': names, 'returncode': run.returncode, 'scope': ('Two authorized receipt integrity regressions' if args.integrity else 'Four new state-race regressions') + ' loaded from actual Main candidate; identical sidecar SHA on Stage/API. Isolated fixtures, no live mutations.', 'prior_actual_entry_evidence_reused': 'integration/actual-entry-r1/RESULT.json', 'test_source_sha256': hashlib.sha256((source / 'tests/test_report_evidence_sidecar.py').read_bytes()).hexdigest(), 'verifier_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (args.evidence / 'RESULT.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False))
    if run.returncode: raise SystemExit(run.returncode)


if __name__ == '__main__': main()
