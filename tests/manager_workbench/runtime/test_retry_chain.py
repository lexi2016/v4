"""Regression for independent review P1: successful semantic cache across retries."""
from unittest.mock import patch

from v4.manager_workbench import engines
from v4.manager_workbench.engines import core
from v4.manager_workbench.contracts import JobState, Lane, Phase
from v4.manager_workbench.inputs import NativeAdapters
from v4.manager_workbench.service import create_service
from tests.manager_workbench.runtime.test_native_pipeline import Semantic, corpus, fixture, wait


class TwiceFailedReviewer(Semantic):
    def execute(self, task):
        # Parent fails reviewer attempt 1. Introduce one additional independent
        # retry failure while retaining the original successful Reader output.
        if task['role'] == 'REVIEWER' and self.reviewers == 1:
            self.reviewers += 1
            self.calls += 1
            raise RuntimeError('MODEL_TEMPORARILY_UNAVAILABLE')
        return super().execute(task)


def test_consecutive_partial_retries_reuse_reader_and_completed_lane(tmp_path):
    cfg = fixture(tmp_path, 1); corpus(cfg)
    executor = TwiceFailedReviewer(cfg)
    service = create_service(cfg, NativeAdapters(cfg), engines, executor)
    try:
        with patch('v4.manager_workbench.engines.core.run_oversold', wraps=core.run_oversold) as oversold:
            first = wait(service, service.submit('20261013', Phase.MANUAL,
                lanes=[Lane.ANNOUNCEMENT, Lane.OVERSOLD]))
            assert first.state == JobState.PARTIAL and first.retryable
            original_sha = service.store.read_plan(first.run_id).product_sha256
            second = wait(service, service.retry(first.job_id))
            assert second.state == JobState.PARTIAL and second.retryable
            second_sha = service.store.read_plan(second.run_id).product_sha256
            final = wait(service, service.retry(second.job_id))
            assert final.state == JobState.SUCCEEDED, final.model_dump()
            assert executor.readers == 1 and executor.reviewers == 3
            assert oversold.call_count == 1
            readers = [ref for ref in final.execution_refs if ref.get('role') == 'READER']
            assert len(readers) == 1
            original_reader = next(ref for ref in first.execution_refs if ref.get('role') == 'READER')
            assert readers[0]['execution_id'] == original_reader['execution_id']
            assert readers[0]['process_pid'] == original_reader['process_pid']
            assert service.store.read_plan(first.run_id).product_sha256 == original_sha
            assert service.store.read_plan(second.run_id).product_sha256 == second_sha
            assert service.store.read_plan(final.run_id).counts.selected == 1
            assert final.failed_steps == [] and not final.retryable
    finally:
        service.jobs.stop()
