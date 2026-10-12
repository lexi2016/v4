from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


TASK_ROOT = Path(__file__).resolve().parents[2]
ADAPTER_PATH = TASK_ROOT / "E/tools/issue35_phase4_pair_publication_adapter_r4_observer.py"
SPEC = importlib.util.spec_from_file_location("issue35_phase4_pair_r4_observer_tested", ADAPTER_PATH)
assert SPEC is not None and SPEC.loader is not None
ADAPTER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ADAPTER
SPEC.loader.exec_module(ADAPTER)


def api_loaded() -> dict:
    return {
        "state": "LOADED",
        "identity": {
            "state": "running",
            "pid": "3299",
            "V35_APP_ROOT": "/candidate/app",
            "V35_RELEASE_ID": "candidate-release",
            "V35_RELEASE_MANIFEST_SHA256": "a" * 64,
        },
    }


class FakeObserver:
    def __init__(self, *, api_results=(), launchctl_results=()):
        self.LABEL = None
        self.api_results = list(api_results)
        self.launchctl_results = list(launchctl_results)
        self.calls: list[tuple[str, str | None]] = []

    @staticmethod
    def _next(queue, label):
        if not queue:
            raise AssertionError(f"unexpected extra observer call for {label}")
        value = queue.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

    def _observe_loaded(self):
        self.calls.append(("api_identity_observer", self.LABEL))
        return self._next(self.api_results, self.LABEL)

    def _launchctl_print(self):
        self.calls.append(("launchctl_print", self.LABEL))
        return self._next(self.launchctl_results, self.LABEL)


def test_pair_precondition_keeps_api_identity_and_accepts_scheduler_without_api_keys():
    expected_api = api_loaded()
    observer = FakeObserver(
        api_results=[expected_api],
        launchctl_results=["label = gui/501/com.lexi.v35.scheduler\nstate = running\npid = 28680\n"],
    )

    api, scheduler = ADAPTER._observe_original_pair(observer)

    assert api == expected_api
    assert scheduler == {
        "state": "LOADED",
        "identity": {"state": "running", "pid": "28680"},
        "label": ADAPTER.SCHEDULER_LABEL,
        "observer_contract": "EXACT_LABEL_RUNNING_PID",
    }
    assert observer.calls == [
        ("api_identity_observer", ADAPTER.API_LABEL),
        ("launchctl_print", ADAPTER.SCHEDULER_LABEL),
    ]


def test_pair_precondition_does_not_upgrade_api_identity_failure_from_state_and_pid():
    observer = FakeObserver(
        api_results=[{"state": "UNKNOWN", "identity": None,
                      "error": "API_ONLY_LAUNCH_AGENT_RUNTIME_IDENTITY_UNAVAILABLE"}],
        launchctl_results=["state = running\npid = 28680\n"],
    )

    with pytest.raises(ValueError, match="BOTH_ORIGINAL_SERVICES_MUST_BE_LOADED_BEFORE_PAIR_SWITCH"):
        ADAPTER._observe_original_pair(observer)
    assert observer.calls == [
        ("api_identity_observer", ADAPTER.API_LABEL),
        ("launchctl_print", ADAPTER.SCHEDULER_LABEL),
    ]


def test_pair_precondition_rejects_scheduler_without_numeric_pid():
    observer = FakeObserver(api_results=[api_loaded()], launchctl_results=["state = running\n"])

    with pytest.raises(ValueError, match="BOTH_ORIGINAL_SERVICES_MUST_BE_LOADED_BEFORE_PAIR_SWITCH"):
        ADAPTER._observe_original_pair(observer)
    assert observer.calls[-1] == ("launchctl_print", ADAPTER.SCHEDULER_LABEL)


@pytest.mark.parametrize(
    ("output", "expected_error"),
    [
        ("state = waiting\npid = 28680\n", "SCHEDULER_NOT_RUNNING"),
        ("pid = 28680\n", "SCHEDULER_LAUNCHCTL_STATE_MISSING"),
        ("state = running\n", "SCHEDULER_PID_MISSING"),
        ("state = running\npid = nope\n", "SCHEDULER_PID_MISSING"),
    ],
)
def test_scheduler_observer_rejects_missing_nonrunning_or_non_numeric_fields(output, expected_error):
    observed = ADAPTER._scheduler_observation_from_output(ADAPTER.SCHEDULER_LABEL, output)

    assert observed["state"] == "UNKNOWN"
    assert observed["error"] == expected_error


def test_scheduler_observer_rejects_a_wrong_label():
    with pytest.raises(ValueError, match="PAIR_SCHEDULER_OBSERVER_LABEL_NOT_ALLOWED"):
        ADAPTER._scheduler_observation_from_output("com.lexi.v35.api-only", "state = running\npid = 1\n")


def test_pair_observer_rejects_unknown_label_before_any_query():
    observer = FakeObserver()

    with pytest.raises(ValueError, match="PAIR_SERVICE_OBSERVER_LABEL_NOT_ALLOWED"):
        ADAPTER._observe_pair_service(observer, "com.lexi.v35.unknown")
    assert observer.calls == []


def test_scheduler_launchctl_errors_remain_unknown_and_do_not_echo_raw_details():
    observer = FakeObserver(launchctl_results=[ValueError("API_ONLY_LAUNCH_AGENT_PRINT_FAILED:secret-looking-detail")])

    observed = ADAPTER._observe_pair_service(observer, ADAPTER.SCHEDULER_LABEL)

    assert observed["state"] == "UNKNOWN"
    assert observed["error"] == "SCHEDULER_LAUNCHCTL_QUERY_FAILED:ValueError"
    assert "secret-looking-detail" not in repr(observed)


def test_exact_missing_service_is_distinct_from_a_launchctl_error():
    observer = FakeObserver(launchctl_results=[ValueError("API_ONLY_LAUNCH_AGENT_NOT_LOADED:service not found")])

    observed = ADAPTER._observe_pair_service(observer, ADAPTER.SCHEDULER_LABEL)

    assert observed == {"state": "NOT_LOADED", "identity": None, "label": ADAPTER.SCHEDULER_LABEL}


@pytest.mark.parametrize("label", [ADAPTER.API_LABEL, ADAPTER.SCHEDULER_LABEL])
def test_wait_label_waits_for_each_service_contract_to_become_loaded(label):
    if label == ADAPTER.API_LABEL:
        observer = FakeObserver(api_results=[
            {"state": "LOADED_UNVERIFIED", "identity": None, "error": "API_ONLY_LAUNCH_AGENT_NOT_RUNNING"},
            api_loaded(),
        ])
    else:
        observer = FakeObserver(launchctl_results=[
            "state = waiting\npid = 28680\n",
            "state = running\npid = 28680\n",
        ])

    result = ADAPTER._wait_label(observer, label, True, timeout=2.0)

    assert result == {"present": True, "state": "running", "pid": "3299" if label == ADAPTER.API_LABEL else "28680"}
    assert len(observer.calls) == 2
    assert all(call[1] == label for call in observer.calls)


@pytest.mark.parametrize("label", [ADAPTER.API_LABEL, ADAPTER.SCHEDULER_LABEL])
def test_wait_label_confirms_absence_for_each_service_contract(label):
    if label == ADAPTER.API_LABEL:
        observer = FakeObserver(api_results=[api_loaded(), {"state": "NOT_LOADED", "identity": None}])
    else:
        observer = FakeObserver(launchctl_results=[
            "state = running\npid = 28680\n",
            ValueError("API_ONLY_LAUNCH_AGENT_NOT_LOADED:service not found"),
        ])

    result = ADAPTER._wait_label(observer, label, False, timeout=2.0)

    assert result == {"present": False, "error": "SERVICE_NOT_LOADED"}
    assert len(observer.calls) == 2
    assert all(call[1] == label for call in observer.calls)


@pytest.mark.parametrize(
    "result",
    [
        ValueError("API_ONLY_LAUNCH_AGENT_PRINT_FAILED:temporary failure"),
        "state = waiting\npid = 28680\n",
        "state = running\n",
    ],
)
def test_wait_does_not_treat_scheduler_error_nonrunning_or_missing_pid_as_unloaded(result):
    observer = FakeObserver(launchctl_results=[result])

    with pytest.raises(ValueError, match="LAUNCHCTL_STATE_TIMEOUT"):
        ADAPTER._wait_label(observer, ADAPTER.SCHEDULER_LABEL, False, timeout=0.01)


def test_recovery_refuses_ambiguous_scheduler_state_but_accepts_loaded_or_absent():
    loaded = FakeObserver(launchctl_results=["state = running\npid = 28680\n"])
    absent = FakeObserver(launchctl_results=[ValueError("API_ONLY_LAUNCH_AGENT_NOT_LOADED:service not found")])
    unknown = FakeObserver(launchctl_results=["state = running\n"])

    assert ADAPTER._recovery_service_observation(loaded, ADAPTER.SCHEDULER_LABEL)["state"] == "LOADED"
    assert ADAPTER._recovery_service_observation(absent, ADAPTER.SCHEDULER_LABEL)["state"] == "NOT_LOADED"
    with pytest.raises(ValueError, match="PAIR_RECOVERY_REFUSES_UNKNOWN_SERVICE_STATE"):
        ADAPTER._recovery_service_observation(unknown, ADAPTER.SCHEDULER_LABEL)


def test_pair_cas_and_recovery_fault_injection_remains_temp_only():
    result = ADAPTER.self_test()

    assert result["status"] == "PASS_TEMP_PLIST_FAULT_INJECTION"
    assert result["live_paths_touched"] is False
