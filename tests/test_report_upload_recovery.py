import asyncio
from types import SimpleNamespace

import pytest

from ops.report_evidence_index import PreSubmitUploadError, serialize_uploads, submit_resource


def test_upload_only_is_serialized_and_other_tasks_can_run():
    async def exercise():
        active = 0
        maximum = 0
        other_ran = False
        async def upload(path):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(.01)
            active -= 1
            return path
        async def other():
            nonlocal other_ran
            await asyncio.sleep(.001)
            other_ran = True
        client = SimpleNamespace(_upload_temp_file=upload)
        serialize_uploads(client)
        assert await asyncio.gather(client._upload_temp_file('a'), client._upload_temp_file('b'), other()) == ['a', 'b', None]
        assert maximum == 1 and other_ran
    asyncio.run(exercise())


@pytest.mark.parametrize('failure,expected', [
    (PreSubmitUploadError('upload'), 'UPLOAD_FAILED_BEFORE_SUBMISSION'),
    (TimeoutError('unknown outcome'), 'SUBMISSION_UNKNOWN'),
])
def test_submission_checkpoint_preserves_uncertain_outcome(failure, expected):
    async def exercise():
        writes=[]; calls=[]; entry={}
        async def add(*args, **kwargs):
            calls.append(1)
            raise failure
        client=SimpleNamespace(add_resource=add)
        def checkpoint(cid, value):writes.append(dict(value))
        with pytest.raises(type(failure)):
            await submit_resource(client,'snapshot','target','id',entry,checkpoint)
        assert writes[0]['submission_state']=='SUBMISSION_UNKNOWN'
        assert entry['submission_state']==expected
        if expected=='SUBMISSION_UNKNOWN':
            with pytest.raises(RuntimeError,match='RECONCILIATION_REQUIRED'):
                await submit_resource(client,'snapshot','target','id',entry,checkpoint)
            assert len(calls)==1
    asyncio.run(exercise())


def test_successful_submission_records_task_identity():
    async def exercise():
        writes=[];entry={}
        async def add(*args, **kwargs):return {'task_id':'known-task'}
        await submit_resource(SimpleNamespace(add_resource=add),'snapshot','target','id',entry,
                              lambda cid,value:writes.append(dict(value)))
        assert writes[0]['submission_state']=='SUBMISSION_UNKNOWN'
        assert entry['submission_state']=='TASK_RECORDED' and entry['task_id']=='known-task'
    asyncio.run(exercise())


def test_upload_error_stops_and_preserves_cause():
    async def exercise():
        calls = []
        async def upload(path):
            calls.append(path)
            raise FileNotFoundError('fixture')
        client = SimpleNamespace(_upload_temp_file=upload)
        serialize_uploads(client)
        with pytest.raises(PreSubmitUploadError) as caught:
            await client._upload_temp_file('a')
        assert isinstance(caught.value.__cause__, FileNotFoundError)
        assert calls == ['a']
    asyncio.run(exercise())
