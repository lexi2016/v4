"""Task6: real private vendor queues, no sockets or live business state."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import socket
import threading
from types import SimpleNamespace

import httpx
import pytest

from infrastructure import zsxq_pdf_local as pdf
from ops import run_manager_flash_announcements as announcement

VENDOR = Path('/Users/lexi/Desktop/学习/agents调试/助手/qwen_flash_next_20261013/pipeline_canary/announcement_queue.py')
VENDOR_SHA = '5e8158fc578c2e005204b984a95ada4429c15750f81a9c2fa58baa906cabc7b7'


@pytest.fixture(autouse=True)
def disconnected(monkeypatch):
    def forbidden(*_a, **_k):
        pytest.fail('Task6 attempted socket access')
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket.socket, 'connect_ex', forbidden)


@pytest.fixture
def vendor():
    assert hashlib.sha256(VENDOR.read_bytes()).hexdigest() == VENDOR_SHA
    # Import the unchanged real queue without importing runtime/settings helpers.
    import sys
    spec = importlib.util.spec_from_file_location('task6_frozen_vendor_queue', VENDOR)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def payload(name, *, market='PDF'):
    return pdf._make_classification_payload(import_date='20261024', document_id=name,
        pdf_sha256=hashlib.sha256(name.encode()).hexdigest(), text='[PAGE 1]\nsource',
        page_count=1, text_truncated=False) | {'market': market}


def running(queue, p):
    item = queue.enqueue(p)
    with queue_module_lock(queue):
        state = queue._load_state()
        queue._claim_next_locked(state, {item['idempotency_key']})
    return item['idempotency_key']


def queue_module_lock(queue):
    import sys
    return sys.modules[type(queue).__module__]._file_lock(queue._state_lock_path)


class Output:
    def __init__(self): self.values = []
    def send(self, value): self.values.append(value)
    def close(self): pass


def classification():
    return {'document_type': '公司', 'industry_tags': [], 'companies': [],
            'document_date': None, 'evidence_page_refs': [1], 'classification_status': 'CLASSIFIED'}


def test_pdf_worker_leaves_actual_legacy_announcement_bytes_unchanged(tmp_path, monkeypatch, vendor):
    legacy = tmp_path / 'announcement_flash/queue'
    old = vendor.SerialAnnouncementQueue(legacy, announcement.QUEUE_ID, pdf.MODEL_ID,
                                        max_attempts=1, max_body_bytes=None)
    with vendor._file_lock(old._model_lock_path): pass
    foreign_key = running(old, payload('announcement-running', market='HK'))
    before = {p.relative_to(legacy).as_posix(): p.read_bytes() for p in legacy.rglob('*') if p.is_file()}
    private = tmp_path / 'data' / pdf.LOCAL_PDF_ROOT / 'classification/queue'
    monkeypatch.setattr(pdf, 'PINNED_ANNOUNCEMENT_QUEUE_ROOT', legacy)
    monkeypatch.setattr(pdf, 'PDF_CLASSIFICATION_QUEUE_ROOT', private, raising=False)
    fake_runner = SimpleNamespace(MODEL_ID=pdf.MODEL_ID, load_local_api_key=lambda: 'fixture')
    class Transport:
        def __init__(self, *_a, **_k): pass
        def begin_job(self, _job): pass
        def complete_batch(self, *_a, **_k): return SimpleNamespace(final_text=json.dumps(classification()))
        def finish_job(self, **_k): pass
        def close(self): pass
    fake_canary = SimpleNamespace(MODEL_ID=pdf.MODEL_ID, EXPECTED_SETTINGS_SHA256='a'*64,
        EXPECTED_MODEL_SETTINGS_SHA256='b'*64, GatedStreamingTransport=Transport)
    monkeypatch.setattr(pdf, '_load_existing_model_modules', lambda: (vendor, fake_canary, fake_runner))
    monkeypatch.setattr(pdf, '_classification_binding', lambda *_a: {'fixture': 'frozen'}, raising=False)
    out = Output()
    pdf._classification_worker(str(legacy), payload('new-pdf'), out)
    assert out.values == [{'status': 'CLASSIFIED', 'classification': classification()}]
    after = {p.relative_to(legacy).as_posix(): p.read_bytes() for p in legacy.rglob('*') if p.is_file()}
    assert after == before, 'PDF execution changed historical announcement state or evidence'
    assert old._load_state()['jobs'][foreign_key]['status'] == 'RUNNING'
    assert (private / 'queue-state.json').is_file()


def adapter(vendor, root, business, legacy, guard=lambda: None, **kw):
    from infrastructure.model_execution_gate import create_business_queue
    return create_business_queue(vendor, root, business, pdf.MODEL_ID,
                                 legacy_queue_root=legacy, binding_guard=guard, **kw)


def test_allowed_business_and_key_selected_before_recovery(tmp_path, vendor):
    legacy = vendor.SerialAnnouncementQueue(tmp_path/'legacy', 'legacy', pdf.MODEL_ID, max_attempts=1)
    with vendor._file_lock(legacy._model_lock_path): pass
    raw = vendor.SerialAnnouncementQueue(tmp_path/'business', 'foreign', pdf.MODEL_ID, max_attempts=1)
    foreign = running(raw, payload('foreign'))
    state=raw._load_state();state['jobs'][foreign]['queue_ids'].append('announcement');raw._save_state(state)
    own = vendor.SerialAnnouncementQueue(raw.state_root, 'announcement', pdf.MODEL_ID, max_attempts=1)
    own_unselected = running(own, payload('unselected'))
    q = adapter(vendor, raw.state_root, 'announcement', legacy.state_root)
    selected = q.enqueue(payload('selected'))['idempotency_key']
    before = deepcopy(q._load_state()['jobs'])
    result = q.run_next(lambda _j: '{}', lambda _j, p: p, idempotency_keys=[selected])
    assert result['status'] == 'SUCCEEDED'
    after = q._load_state()['jobs']
    assert after[foreign] == before[foreign]
    assert after[own_unselected] == before[own_unselected]


def test_new_announcement_pdf_and_unchanged_legacy_client_serial_transport(tmp_path, vendor):
    legacy = vendor.SerialAnnouncementQueue(tmp_path/'legacy', 'legacy', pdf.MODEL_ID, max_attempts=1)
    # Materialize the original physical lock using the unchanged legacy client.
    with vendor._file_lock(legacy._model_lock_path): pass
    inode = legacy._model_lock_path.stat().st_ino
    queues = [legacy, adapter(vendor,tmp_path/'announcement','announcement',legacy.state_root),
              adapter(vendor,tmp_path/'pdf','pdf',legacy.state_root)]
    keys = [q.enqueue(payload(str(i)))['idempotency_key'] for i,q in enumerate(queues)]
    active = 0; maximum = 0; posts = []; mutex = threading.Lock()
    entered = threading.Event(); release = threading.Event(); outcomes = []; errors = []
    def handler(request):
        nonlocal active, maximum
        with mutex:
            active += 1; maximum = max(maximum, active); posts.append(request)
            first = len(posts) == 1
        if first:
            entered.set(); assert release.wait(5)
        with mutex: active -= 1
        return httpx.Response(200, json={'ok': True})
    def execute(_job):
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            return client.post('http://fixture.invalid/v1/chat/completions').text
    def run(q,key):
        try: outcomes.append(q.run_next(execute,lambda _j,p:p,idempotency_keys=[key]))
        except Exception as exc: errors.append(exc)
    threads = [threading.Thread(target=run,args=(q,k)) for q,k in zip(queues,keys)]
    threads[0].start(); assert entered.wait(5)
    threads[1].start(); threads[2].start()
    release.set()
    for thread in threads: thread.join(5); assert not thread.is_alive()
    assert not errors
    assert len(outcomes) == len(posts) == 3
    assert all(row['status'] == 'SUCCEEDED' for row in outcomes)
    assert maximum == 1
    assert legacy._model_lock_path.stat().st_ino == inode


def test_legacy_busy_zero_post_claim_attempt(tmp_path, vendor):
    legacy = vendor.SerialAnnouncementQueue(tmp_path/'legacy','legacy',pdf.MODEL_ID,max_attempts=1)
    with vendor._file_lock(legacy._model_lock_path): pass
    q = adapter(vendor,tmp_path/'pdf','pdf',legacy.state_root)
    key = q.enqueue(payload('busy'))['idempotency_key']; before = q.state_path.read_bytes()
    with vendor._file_lock(legacy._model_lock_path):
        with pytest.raises(vendor.ModelSlotBusy):
            q.run_next(lambda _j: pytest.fail('busy dispatched'),lambda _j,p:p,
                       idempotency_keys=[key],wait_for_model_slot=False)
    assert q.state_path.read_bytes() == before
    assert q._load_state()['jobs'][key]['attempts'] == []


@pytest.mark.parametrize('after_wait', [False, True])
@pytest.mark.parametrize('kind', ['configuration', 'source'])
def test_frozen_drift_stops_before_claim_even_after_wait(tmp_path, vendor, after_wait, kind):
    from infrastructure.model_execution_gate import frozen_file_guard
    legacy = vendor.SerialAnnouncementQueue(tmp_path/'legacy','legacy',pdf.MODEL_ID,max_attempts=1)
    with vendor._file_lock(legacy._model_lock_path): pass
    frozen = tmp_path/(kind+'.json'); frozen.write_bytes(b'frozen')
    guard = frozen_file_guard({frozen: hashlib.sha256(b'frozen').hexdigest()})
    checked = threading.Event()
    def observed_guard(): guard(); checked.set()
    q = adapter(vendor,tmp_path/'pdf','pdf',legacy.state_root, observed_guard)
    key = q.enqueue(payload('drift'))['idempotency_key']; before = q.state_path.read_bytes(); errors=[]
    checked.clear()
    def run():
        try: q.run_next(lambda _j: pytest.fail('drift dispatched'),lambda _j,p:p,idempotency_keys=[key])
        except Exception as exc: errors.append(exc)
    if after_wait:
        with vendor._file_lock(legacy._model_lock_path):
            thread=threading.Thread(target=run); thread.start(); assert checked.wait(5)
            frozen.write_bytes(b'changed')
        thread.join(5); assert not thread.is_alive()
    else:
        frozen.write_bytes(b'changed'); run()
    assert len(errors)==1 and 'MODEL_EXECUTION_BINDING_CHANGED' in str(errors[0])
    assert q.state_path.read_bytes()==before


def test_missing_legacy_lock_is_not_created(tmp_path, vendor):
    from infrastructure.model_execution_gate import ModelExecutionBindingError
    with pytest.raises(ModelExecutionBindingError):
        adapter(vendor,tmp_path/'pdf','pdf',tmp_path/'legacy')
    assert not (tmp_path/'legacy').exists()


def test_announcement_factory_uses_filtered_gate_adapter(tmp_path, vendor):
    legacy=vendor.SerialAnnouncementQueue(tmp_path/'announcement_flash/queue',announcement.QUEUE_ID,
                                         pdf.MODEL_ID,max_attempts=1)
    with vendor._file_lock(legacy._model_lock_path): pass
    foreign=vendor.SerialAnnouncementQueue(legacy.state_root,pdf.MODEL_QUEUE_ID,pdf.MODEL_ID,max_attempts=1)
    key=running(foreign,payload('legacy-pdf'))
    q=announcement._new_only_queue(vendor,legacy.state_root,pdf.MODEL_ID)
    own=q.enqueue(payload('new-announcement',market='HK'))['idempotency_key']
    before=deepcopy(q._load_state()['jobs'][key])
    result=q.run_next(lambda _j:'{}',lambda _j,p:p,idempotency_keys=[own])
    assert result['status']=='SUCCEEDED'
    assert q._load_state()['jobs'][key]==before
    assert hasattr(q,'binding_guard'), 'actual runner must use thin adapter'


def test_actual_pdf_worker_busy_does_not_attempt_or_dispatch(tmp_path, monkeypatch, vendor):
    legacy=vendor.SerialAnnouncementQueue(tmp_path/'announcement_flash/queue',announcement.QUEUE_ID,
                                         pdf.MODEL_ID,max_attempts=1)
    with vendor._file_lock(legacy._model_lock_path): pass
    private=tmp_path/'pdf/queue'
    monkeypatch.setattr(pdf,'PINNED_ANNOUNCEMENT_QUEUE_ROOT',legacy.state_root)
    monkeypatch.setattr(pdf,'PDF_CLASSIFICATION_QUEUE_ROOT',private)
    monkeypatch.setattr(pdf,'_classification_binding',lambda *_a: {'fixture':'frozen'})
    class Transport:
        def __init__(self,*_a,**_k): pass
        def complete_batch(self,*_a,**_k): pytest.fail('busy PDF made a POST')
        def begin_job(self,*_a): pytest.fail('busy PDF began an attempt')
        def close(self): pass
    runner=SimpleNamespace(MODEL_ID=pdf.MODEL_ID,load_local_api_key=lambda:'fixture')
    canary=SimpleNamespace(MODEL_ID=pdf.MODEL_ID,GatedStreamingTransport=Transport,
        EXPECTED_SETTINGS_SHA256='a'*64,EXPECTED_MODEL_SETTINGS_SHA256='b'*64)
    monkeypatch.setattr(pdf,'_load_existing_model_modules',lambda:(vendor,canary,runner))
    out=Output()
    with vendor._file_lock(legacy._model_lock_path):
        pdf._classification_worker(str(legacy.state_root),payload('busy-worker'),out)
    assert out.values==[{'status':'DEFERRED','reason_code':'LOCAL_MODEL_SLOT_BUSY'}]
    state=json.loads((private/'queue-state.json').read_bytes())
    assert len(state['jobs'])==1
    item=next(iter(state['jobs'].values()))
    assert item['status']=='PENDING' and item['attempt_count']==0 and item['attempts']==[]
    assert not (private/'evidence').exists()
    assert not (legacy.state_root/'queue-state.json').exists()


def test_healthy_classifier_timeout_defers_without_termination_or_duplicate(tmp_path, monkeypatch, vendor):
    from infrastructure import model_execution_gate as gate
    legacy=tmp_path/'announcement_flash/queue'; legacy.mkdir(parents=True)
    monkeypatch.setattr(pdf,'PINNED_ANNOUNCEMENT_QUEUE_ROOT',legacy)
    monkeypatch.setattr(pdf,'_CLASSIFICATION_WORKERS',{})
    monkeypatch.setattr(pdf,'_load_existing_model_modules',lambda: (vendor,None,None))
    monkeypatch.setattr(pdf,'_classification_binding',lambda *_a: {'fixture':'frozen'})
    monkeypatch.setattr(gate,'legacy_model_slot_busy',lambda *_a:False)
    class Pipe:
        closed=False
        def close(self): self.closed=True
    class Child:
        pid=1
        alive=True
        def start(self): pass
        def is_alive(self): return self.alive
        def terminate(self): pytest.fail('cancelled healthy worker')
        def kill(self): pytest.fail('killed healthy worker')
    calls=[]
    class Context:
        def Pipe(self,**_k): return Pipe(),Pipe()
        def Process(self,**kw): calls.append(kw); return Child()
    monkeypatch.setattr(pdf.multiprocessing,'get_context',lambda _kind:Context())
    ticks=iter([0.0,121.0]); monkeypatch.setattr(pdf,'time',SimpleNamespace(monotonic=lambda:next(ticks)))
    kwargs=dict(announcement_queue_root=legacy,import_date='20261024',document_id='timeout',
                pdf_sha256='a'*64,pages=[{'page_number':1,'text':'x'}])
    result=pdf.classify_with_existing_model(tmp_path/'data',**kwargs)
    assert result=={'status':'DEFERRED','reason_code':'LOCAL_MODEL_WORKER_STILL_RUNNING'}
    assert len(calls)==1 and calls[0]['daemon'] is False
    retained=dict(pdf._CLASSIFICATION_WORKERS);key,worker=next(iter(retained.items()))
    assert not worker['recv'].closed
    assert pdf.classify_with_existing_model(tmp_path/'data',**kwargs)==result
    # Simulate an independent caller with no parent registry: the business
    # ownership flock still rejects a second worker before it can start.
    monkeypatch.setattr(pdf,'_CLASSIFICATION_WORKERS',{})
    assert pdf.classify_with_existing_model(tmp_path/'data',**kwargs)==result
    assert len(calls)==1 and not worker['recv'].closed
    worker['child'].alive=False
    pdf._release_classification_worker(key,worker)


def test_runner_frozen_guard_uses_material_and_detects_change(tmp_path, monkeypatch):
    from infrastructure import local_document_model as model
    pipeline=tmp_path/'pipeline'; pipeline.mkdir()
    helper=pipeline/'evidence/recent-day-20261014/recent_day_freeze.py'; helper.parent.mkdir(parents=True)
    helper.write_bytes(b'helper')
    vendor_source=pipeline/'announcement_queue.py';vendor_source.write_bytes(b'vendor')
    repo=tmp_path/'repo';(repo/'infrastructure').mkdir(parents=True)
    gate=repo/'infrastructure/model_execution_gate.py';gate.write_bytes(b'gate')
    engine=repo/'v4/engine.py';engine.parent.mkdir();engine.write_bytes(b'engine')
    settings=tmp_path/'settings';settings.write_bytes(b'settings')
    model_settings=tmp_path/'model-settings';model_settings.write_bytes(b'model-settings')
    digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    monkeypatch.setattr(model,'PINNED_SOURCE_SHA256',{'announcement_queue.py':digest(vendor_source)})
    monkeypatch.setattr(announcement,'PIPELINE_ROOT',pipeline)
    monkeypatch.setattr(announcement,'REPO_ROOT',repo)
    material={'runtime_settings_sha256':digest(settings),'model_settings_sha256':digest(model_settings),
              'source_code_sha256':{'recent_day_freeze.py':digest(helper),'v4/engine.py':digest(engine)}}
    runner=SimpleNamespace(OMLX_SETTINGS_PATH=settings,OMLX_MODEL_SETTINGS_PATH=model_settings)
    guard=announcement._announcement_execution_guard(runner,material);guard()
    engine.write_bytes(b'changed')
    with pytest.raises(Exception,match='MODEL_EXECUTION_BINDING_CHANGED'):guard()


def test_runtime_binding_builder_checks_frozen_classification_config(tmp_path,monkeypatch):
    from infrastructure import local_document_model as model
    from infrastructure.model_execution_gate import frozen_file_guard
    pipeline=tmp_path/'pipeline';pipeline.mkdir()
    source=pipeline/'announcement_queue.py';source.write_bytes(b'vendor')
    settings=tmp_path/'settings';settings.write_bytes(b'settings')
    model_settings=tmp_path/'model-settings';model_settings.write_bytes(b'model-settings')
    digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    monkeypatch.setattr(model,'PIPELINE_ROOT',pipeline)
    monkeypatch.setattr(model,'PINNED_SOURCE_SHA256',{'announcement_queue.py':digest(source)})
    modules=SimpleNamespace(runner=SimpleNamespace(OMLX_SETTINGS_PATH=settings,OMLX_MODEL_SETTINGS_PATH=model_settings),
        canary=SimpleNamespace(EXPECTED_SETTINGS_SHA256=digest(settings),EXPECTED_MODEL_SETTINGS_SHA256=digest(model_settings)))
    files=model.classification_binding_files(modules);guard=frozen_file_guard(files);guard()
    settings.write_bytes(b'changed')
    with pytest.raises(Exception,match='MODEL_EXECUTION_BINDING_CHANGED'):guard()


def test_busy_public_classifier_never_spawns_duplicate_healthy_work(tmp_path,monkeypatch,vendor):
    legacy=vendor.SerialAnnouncementQueue(tmp_path/'announcement_flash/queue','legacy',pdf.MODEL_ID,max_attempts=1)
    with vendor._file_lock(legacy._model_lock_path):pass
    monkeypatch.setattr(pdf,'PINNED_ANNOUNCEMENT_QUEUE_ROOT',legacy.state_root)
    monkeypatch.setattr(pdf.multiprocessing,'get_context',lambda *_a:pytest.fail('busy spawned a duplicate worker'))
    before={p.relative_to(legacy.state_root).as_posix():p.read_bytes() for p in legacy.state_root.rglob('*') if p.is_file()}
    with vendor._file_lock(legacy._model_lock_path):
        result=pdf.classify_with_existing_model(tmp_path/'data',announcement_queue_root=legacy.state_root,
            import_date='20261024',document_id='busy',pdf_sha256='a'*64,pages=[{'page_number':1,'text':'x'}])
    assert result=={'status':'DEFERRED','reason_code':'LOCAL_MODEL_SLOT_BUSY'}
    after={p.relative_to(legacy.state_root).as_posix():p.read_bytes() for p in legacy.state_root.rglob('*') if p.is_file()}
    assert after==before
    assert not (tmp_path/'data').exists()


def test_actual_announcement_pdf_worker_and_legacy_transport_share_slot(tmp_path,monkeypatch,vendor):
    legacy=vendor.SerialAnnouncementQueue(tmp_path/'announcement_flash/queue','legacy',pdf.MODEL_ID,max_attempts=1)
    with vendor._file_lock(legacy._model_lock_path):pass
    ann=announcement._new_only_queue(vendor,legacy.state_root,pdf.MODEL_ID,recover_running=True)
    private=tmp_path/'pdf/queue'
    monkeypatch.setattr(pdf,'PINNED_ANNOUNCEMENT_QUEUE_ROOT',legacy.state_root)
    monkeypatch.setattr(pdf,'PDF_CLASSIFICATION_QUEUE_ROOT',private)
    monkeypatch.setattr(pdf,'_classification_binding',lambda *_a:{'fixture':'frozen'})
    active=0;maximum=0;posts=[];mutex=threading.Lock();entered=threading.Event();release=threading.Event()
    def handler(request):
        nonlocal active,maximum
        with mutex:
            active+=1;maximum=max(maximum,active);posts.append(request);first=len(posts)==1
        if first:entered.set();assert release.wait(5)
        with mutex:active-=1
        return httpx.Response(200,json=classification())
    def execute(_job):
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            return client.post('http://fixture.invalid/v1/chat/completions').text
    class Transport:
        def __init__(self,*_a,**kw):
            self.client=httpx.Client(transport=httpx.MockTransport(handler))
            assert Path(_a[1])==private/'evidence'
        def begin_job(self,_job):pass
        def complete_batch(self,*_a,**_k):
            return SimpleNamespace(final_text=self.client.post('http://fixture.invalid/v1/chat/completions').text)
        def finish_job(self,**_k):pass
        def close(self):self.client.close()
    runner=SimpleNamespace(MODEL_ID=pdf.MODEL_ID,load_local_api_key=lambda:'fixture')
    canary=SimpleNamespace(MODEL_ID=pdf.MODEL_ID,GatedStreamingTransport=Transport,
        EXPECTED_SETTINGS_SHA256='a'*64,EXPECTED_MODEL_SETTINGS_SHA256='b'*64)
    monkeypatch.setattr(pdf,'_load_existing_model_modules',lambda:(vendor,canary,runner))
    oldkey=legacy.enqueue(payload('old'))['idempotency_key'];annkey=ann.enqueue(payload('ann',market='HK'))['idempotency_key']
    errors=[];outcomes=[];out=Output()
    def run(q,key):
        try:outcomes.append(q.run_next(execute,lambda _j,p:p,idempotency_keys=[key]))
        except Exception as exc:errors.append(exc)
    old=threading.Thread(target=run,args=(legacy,oldkey));old.start();assert entered.wait(5)
    new_ann=threading.Thread(target=run,args=(ann,annkey));new_ann.start()
    # The worker's nonblocking behavior must defer under the unchanged legacy owner.
    pdf._classification_worker(str(legacy.state_root),payload('pdf'),out)
    assert out.values==[{'status':'DEFERRED','reason_code':'LOCAL_MODEL_SLOT_BUSY'}]
    release.set();old.join(5);new_ann.join(5)
    assert not old.is_alive() and not new_ann.is_alive() and not errors
    resumed=Output();pdf._classification_worker(str(legacy.state_root),payload('pdf'),resumed)
    assert resumed.values==[{'status':'CLASSIFIED','classification':classification()}]
    assert len(posts)==3 and maximum==1
    assert all(row['status']=='SUCCEEDED' for row in outcomes)
    pdfstate=json.loads((private/'queue-state.json').read_bytes())
    assert len(pdfstate['jobs'])==1 and next(iter(pdfstate['jobs'].values()))['attempt_count']==1


def test_timeout_retains_ipc_inputs_owner_then_reuses_natural_success(tmp_path,monkeypatch,vendor):
    import queue as thread_queue
    legacy=vendor.SerialAnnouncementQueue(tmp_path/'announcement_flash/queue','legacy',pdf.MODEL_ID,max_attempts=1)
    with vendor._file_lock(legacy._model_lock_path):pass
    monkeypatch.setattr(pdf,'PINNED_ANNOUNCEMENT_QUEUE_ROOT',legacy.state_root)
    monkeypatch.setattr(pdf,'_CLASSIFICATION_WORKERS',{})
    monkeypatch.setattr(pdf,'_classification_binding',lambda *_a:{'fixture':'frozen'})
    entered=threading.Event();release=threading.Event();posts=[]
    def handler(request):
        posts.append(request);entered.set();assert release.wait(5)
        return httpx.Response(200,json=classification())
    class Transport:
        def __init__(self,*_a,**_k):self.client=httpx.Client(transport=httpx.MockTransport(handler))
        def begin_job(self,_job):pass
        def complete_batch(self,*_a,**_k):
            return SimpleNamespace(final_text=self.client.post('http://fixture.invalid/v1/chat/completions').text)
        def finish_job(self,**_k):pass
        def close(self):self.client.close()
    runner=SimpleNamespace(MODEL_ID=pdf.MODEL_ID,load_local_api_key=lambda:'fixture')
    canary=SimpleNamespace(MODEL_ID=pdf.MODEL_ID,GatedStreamingTransport=Transport,
        EXPECTED_SETTINGS_SHA256='a'*64,EXPECTED_MODEL_SETTINGS_SHA256='b'*64)
    monkeypatch.setattr(pdf,'_load_existing_model_modules',lambda:(vendor,canary,runner))
    receivers=[];senders=[];children=[]
    class Receiver:
        closed=False
        def __init__(self,q):self.q=q
        def poll(self,_timeout):return not self.q.empty()
        def recv(self):return self.q.get_nowait()
        def close(self):self.closed=True
    class Sender:
        closed=False
        def __init__(self,q):self.q=q
        def send(self,value):assert not receivers[-1].closed;self.q.put(value)
        def close(self):self.closed=True
    class Child:
        pid=1
        def __init__(self,kw):self.kw=kw;self.thread=None
        def start(self):
            self.thread=threading.Thread(target=self.kw['target'],args=self.kw['args']);self.thread.start()
            assert entered.wait(5)
        def is_alive(self):return self.thread is not None and self.thread.is_alive()
        def join(self,timeout=None):self.thread.join(timeout)
        def terminate(self):pytest.fail('cancelled healthy child')
        def kill(self):pytest.fail('killed healthy child')
    class Context:
        def Pipe(self,**_k):
            q=thread_queue.Queue();r=Receiver(q);s=Sender(q);receivers.append(r);senders.append(s);return r,s
        def Process(self,**kw):c=Child(kw);children.append(c);return c
    monkeypatch.setattr(pdf.multiprocessing,'get_context',lambda *_a:Context())
    ticks=iter([0.0,121.0]);monkeypatch.setattr(pdf,'time',SimpleNamespace(monotonic=lambda:next(ticks)))
    kwargs=dict(announcement_queue_root=legacy.state_root,import_date='20261024',document_id='natural',
                pdf_sha256='a'*64,pages=[{'page_number':1,'text':'full source survives timeout'}])
    first=pdf.classify_with_existing_model(tmp_path/'data',**kwargs)
    assert first=={'status':'DEFERRED','reason_code':'LOCAL_MODEL_WORKER_STILL_RUNNING'}
    worker=next(iter(pdf._CLASSIFICATION_WORKERS.values()))
    assert worker['child'].is_alive() and not receivers[0].closed
    assert 'full source survives timeout' in worker['payload']['article_body']
    assert worker['binding']=={'fixture':'frozen'}
    private=tmp_path/'data'/pdf.LOCAL_PDF_ROOT/'classification/queue'
    assert (private/'queue-state.json').exists() and list((private/'workers').glob('*.lock'))
    before=(private/'queue-state.json').read_bytes()
    second=pdf.classify_with_existing_model(tmp_path/'data',**kwargs)
    assert second['status']=='DEFERRED' and len(children)==len(posts)==1
    assert (private/'queue-state.json').read_bytes()==before and not receivers[0].closed
    release.set();children[0].join(5);assert not children[0].is_alive()
    succeeded=(private/'queue-state.json').read_bytes()
    third=pdf.classify_with_existing_model(tmp_path/'data',**kwargs)
    assert third=={'status':'CLASSIFIED','classification':classification()}
    assert len(children)==len(posts)==1 and receivers[0].closed and not pdf._CLASSIFICATION_WORKERS
    assert (private/'queue-state.json').read_bytes()==succeeded
    # A changed source/config binding must never reuse this original success.
    original=worker['payload'];changed=pdf._bound_classification_payload(original,{'fixture':'changed'})
    assert pdf._read_classification_result(private,changed,vendor) is None
    # Same binding with a tampered result also fails closed without spawning.
    state=json.loads(succeeded);item=next(iter(state['jobs'].values()))
    (private/item['validated_path']).write_bytes(b'{}')
    failed=pdf.classify_with_existing_model(tmp_path/'data',**kwargs)
    assert failed=={'status':'FAILED','reason_code':'LOCAL_CLASSIFICATION_REUSE_SHA_MISMATCH'}
    assert len(children)==len(posts)==1
