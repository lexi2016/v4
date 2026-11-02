"""Explicit local-only report indexing operation; never called by a GET or MCP tool."""
from __future__ import annotations
import argparse
import asyncio
import fcntl
import json
import os
from pathlib import Path
import sys
import time
from infrastructure.report_evidence_index import (BgeTokenizer, PdfOwner, ReportIndex, MODEL_REVISION,
    NAMESPACE, canonical, digest)
from infrastructure.report_evidence_native import LocalNative

def save(path, obj):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(obj, ensure_ascii=False, indent=2))
    os.replace(temp, path)

class PreSubmitUploadError(RuntimeError):
    """The SDK failed while uploading, before its resource submission call."""

def serialize_uploads(client):
    """Serialize only SDK uploads; resource processing remains concurrent."""
    original = client._upload_temp_file
    lock = asyncio.Lock()
    async def upload(path):
        async with lock:
            try:
                return await original(path)
            except Exception as exc:
                raise PreSubmitUploadError(type(exc).__name__) from exc
    client._upload_temp_file = upload

async def submit_resource(client, snapshot, target, cid, entry, checkpoint):
    if entry.get('submission_state') == 'SUBMISSION_UNKNOWN':
        raise RuntimeError('SUBMISSION_RECONCILIATION_REQUIRED')
    entry['submission_state']='SUBMISSION_UNKNOWN';checkpoint(cid,entry)
    try:
        result=await client.add_resource(str(snapshot),to=target,wait=False,
            options={'processing_mode':'vectors_only','args':{'parse_mode':'no_split'},'create_parent':True})
    except PreSubmitUploadError:
        entry['submission_state']='UPLOAD_FAILED_BEFORE_SUBMISSION';checkpoint(cid,entry)
        raise
    entry.update(task_id=result.get('task_id'),ingest_result=result,
        submission_state='TASK_RECORDED' if result.get('task_id') else 'SUBMISSION_UNKNOWN');checkpoint(cid,entry)
    if not entry['task_id']:raise RuntimeError('TASK_ID_MISSING_CHECKPOINT_RETAINED')

async def import_vectors(index, native, pending=1, content_id=None):
    """Bounded native task pipeline; the existing embedding service stays batch1."""
    from openviking_sdk import AsyncHTTPClient
    if not 1<=pending<=8:
        raise ValueError('PENDING_LIMIT_1_TO_8')
    c=native.credentials()
    client=AsyncHTTPClient(url=native.runtime.URL,api_key=c['api_key'],account=c['account'],user=c['user'],timeout=120)
    await client.initialize()
    serialize_uploads(client)
    cp=index.root/'native-checkpoint.json'
    state=json.loads(cp.read_text()) if cp.exists() else dict(namespace=NAMESPACE,model_revision=MODEL_REVISION,chunks={})
    if state['namespace']!=NAMESPACE or state['model_revision']!=MODEL_REVISION:
        raise RuntimeError('CHECKPOINT_IDENTITY_MISMATCH')
    with index.connect(True) as db:
        db.execute('CREATE TABLE IF NOT EXISTS native_tasks(id TEXT PRIMARY KEY,entry TEXT NOT NULL)')
        for row in db.execute('SELECT id,entry FROM native_tasks'):
            state['chunks'][row['id']]=json.loads(row['entry'])
    def checkpoint(cid,entry):
        with index.connect(True) as db:
            db.execute('INSERT OR REPLACE INTO native_tasks VALUES(?,?)',(cid,canonical(entry)))
    snapshots=index.root/'snapshots';snapshots.mkdir(exist_ok=True)
    started=time.perf_counter();completed=0;resolved=0;errors=[]
    with index.connect() as db:
        rows=[dict(r) for r in db.execute('SELECT c.* FROM chunks c JOIN documents d ON c.document_id=d.id WHERE d.active=1 ORDER BY c.id')]
    pages={}
    for row in rows:pages.setdefault(row['document_id'],set()).add((row['page'],row['page_sha']))
    scopes={}
    with index.connect(True) as db:
        for doc_id,source_pages in pages.items():
            m=json.loads(db.execute('SELECT metadata FROM documents WHERE id=?',(doc_id,)).fetchone()[0])
            scopes[doc_id]=NAMESPACE+'/'+m['pdf_sha']+'/'+digest(canonical([sorted(source_pages),MODEL_REVISION]))
            m['vector_scope_uri']=scopes[doc_id]
            db.execute('UPDATE documents SET metadata=? WHERE id=?',(canonical(m),doc_id))
    groups={}
    for row in rows:
        if row['uri']:completed+=1;continue
        cid=json.loads(row['detail'])['content_id'];groups.setdefault(cid,[]).append(row)
    if content_id is not None:
        if content_id not in groups:raise ValueError('CANARY_CONTENT_NOT_PENDING')
        groups={content_id:groups[content_id]}
    def progress():
        elapsed=time.perf_counter()-started
        value=dict(completed_rows=completed,total_rows=len(rows),resolved_content_groups=resolved,seconds=elapsed,
            rows_per_second=resolved/elapsed,remaining_seconds_estimate=(len(groups)-resolved)*elapsed/max(resolved,1),
            model_batch_size=1,native_in_flight_limit=pending,queue_limit=2*pending,
            stop_requested=(index.root/'pause-new-submissions').exists())
        save(index.root/'native-progress.json',value)
        print('NATIVE_CHECKPOINT',canonical(value),flush=True)
    async def one(cid,group):
        row=group[0];entry=state['chunks'].setdefault(cid,{})
        snapshot=snapshots/(cid+'.md')
        if not snapshot.exists():snapshot.write_text(row['body'])
        if digest(snapshot.read_bytes())!=digest(row['body']):raise RuntimeError('SNAPSHOT_SHA_DRIFT')
        if not entry.get('imported_uri'):
            native.guard()
            if not entry.get('task_id'):
                await submit_resource(client,snapshot,scopes[row['document_id']]+'/'+cid,cid,entry,checkpoint)
            while True:
                task=await client.get_task(entry['task_id'])
                status=task.get('status') if task else None
                if entry.get('task_status')!=status:entry['task_status']=status;checkpoint(cid,entry)
                if task and status=='completed':break
                if task and status in {'failed','cancelled'}:raise RuntimeError('NATIVE_TASK_FAILED_CHECKPOINT_RETAINED')
                await asyncio.sleep(.1)
            root=task.get('result',{}).get('root_uri') or entry['ingest_result'].get('root_uri')
            if not root or not root.startswith(NAMESPACE+'/'):raise RuntimeError('NATIVE_NAMESPACE_MISMATCH')
            if root.endswith('.md'):uri=root
            else:
                files=[x['uri'] for x in await client.ls(root,recursive=True,node_limit=10) if x.get('uri','').endswith('.md') and not Path(x['uri']).name.startswith('.')]
                if len(files)!=1:raise RuntimeError('EXPECTED_ONE_ORIGINAL_CHUNK')
                uri=files[0]
            if snapshot.read_text().strip() not in await client.read(uri):raise RuntimeError('NATIVE_BODY_READBACK_MISMATCH')
            entry.update(imported_uri=uri,readback_sha=digest(row['body']));checkpoint(cid,entry)
        if entry.get('readback_sha')!=digest(row['body']):raise RuntimeError('CHECKPOINT_BODY_MISMATCH')
        with index.connect(True) as db:
            db.executemany('UPDATE chunks SET uri=? WHERE id=?',[(entry['imported_uri'],r['id']) for r in group])
    queue=asyncio.Queue(maxsize=2*pending)
    async def worker():
        nonlocal completed,resolved
        while True:
            item=await queue.get()
            try:
                if item is None:return
                if errors or (index.root/'pause-new-submissions').exists():continue
                cid,group=item
                try:
                    await one(cid,group);completed+=len(group);resolved+=1
                    if resolved%25==0:progress()
                except Exception as error:
                    errors.append(type(error).__name__)
                    save(index.root/'native-error.json',dict(status='STOPPED_NEW_SUBMISSIONS',error_type=type(error).__name__,checkpoint_retained=True))
            finally:queue.task_done()
    workers=[asyncio.create_task(worker()) for _ in range(pending)]
    try:
        for item in groups.items():
            if errors or (index.root/'pause-new-submissions').exists():break
            await queue.put(item)
        for _ in workers:await queue.put(None)
        await queue.join();await asyncio.gather(*workers);progress()
        if errors:raise RuntimeError('NATIVE_TASK_FAILED_INFLIGHT_DRAINED_CHECKPOINT_RETAINED')
    finally:
        await client.close()

async def main(args):
    index = ReportIndex(args.index_root, PdfOwner(args.data_root)); index.initialize()
    if args.full or args.vectors_only:
        receipt = json.loads(Path(args.canary_receipt).read_text())
        if receipt.get('status') != 'PASS_FROZEN_12_REAL_LOCAL_VECTOR' or not receipt.get('sqlite_sha256') or not receipt.get('native_uri_set_sha256'):
            raise RuntimeError('CANARY_GATE_NOT_PASSED')
    native = LocalNative(args.bridge)
    native.guard()
    model = json.loads((native.runtime.ART/'local_model_manifest.json').read_text())
    if args.vectors_only:
        mechanical=json.loads((index.root/'coverage.json').read_text())
        if mechanical.get('full_scope') is not True:
            raise RuntimeError('FULL_MECHANICAL_COVERAGE_REQUIRED')
        await import_vectors(index,native,args.pending,args.content_id)
        save(index.root/'coverage.json',{**mechanical,**index.coverage()})
        print(canonical(index.coverage()))
        return
    tokenizer = BgeTokenizer(model['model_dir'])
    inventory = list(index.owner.inventory())
    scope = [(doc,day) for doc,day in inventory if args.full or doc in args.document_id]
    if not scope:
        raise ValueError('EXPLICIT_DOCUMENT_SCOPE_REQUIRED')
    statuses = []
    for n,(doc,day) in enumerate(scope,1):
        try:
            d = index.owner.verified(doc,day)
            status = index.upsert(d,tokenizer)
            statuses.append(dict(document_id=doc,status=status,available_at=__import__('infrastructure.report_evidence_index',fromlist=['metadata']).metadata(d)['available_at']))
        except Exception as exc:
            reason = str(exc) if isinstance(exc,ValueError) else getattr(exc,'code',type(exc).__name__)
            index.record_gap(doc,reason); statuses.append(dict(document_id=doc,status='CANNOT_CONFIRM',reason=reason))
        if n%25==0:
            save(index.root/'coverage-checkpoint.json', dict(total_scope=len(scope),completed=n,items=statuses))
            print('VERIFY_CHECKPOINT',n,'/',len(scope),flush=True)
    if args.full:
        active_ids = {doc for doc,_ in inventory}
        with index.connect(True) as db:
            for r in db.execute('SELECT id FROM documents').fetchall():
                if r[0] not in active_ids:
                    db.execute('UPDATE documents SET active=0 WHERE id=?',(r[0],))
                    db.execute('INSERT OR REPLACE INTO ledger VALUES(?,?,?)',(r[0],'RETRACTED','REMOVED_FROM_OWNER_INDEX'))
    save(index.root/'coverage-checkpoint.json',dict(total_scope=len(scope),completed=len(scope),items=statuses))
    if args.vectors:
        await import_vectors(index,native,args.pending)
    save(index.root/'coverage.json', dict(**index.coverage(),owner_inventory=len(inventory),processed_scope=len(scope),
        historical_available_unknown=sum(x.get('status')!='CANNOT_CONFIRM' and x.get('available_at') is None for x in statuses),
        source_semantics='OWNER_INDEX_ONLY_NOT_ALL_REPORTS',full_scope=args.full))
    print(canonical(index.coverage()))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-root',required=True);p.add_argument('--index-root',required=True);p.add_argument('--bridge',required=True)
    p.add_argument('--document-id',action='append',default=[]);p.add_argument('--vectors',action='store_true');p.add_argument('--full',action='store_true');p.add_argument('--canary-receipt');p.add_argument('--vectors-only',action='store_true');p.add_argument('--pending',type=int,default=1)
    p.add_argument('--content-id', help='Single pending content group for an explicit vectors-only canary')
    args=p.parse_args()
    if args.content_id and (not args.vectors_only or len(args.content_id)!=64 or any(c not in '0123456789abcdef' for c in args.content_id)):
        p.error('--content-id requires --vectors-only and a lowercase SHA256')
    ReportIndex(args.index_root,PdfOwner(args.data_root)).root.mkdir(parents=True,exist_ok=True)
    with (Path(args.index_root)/'operation.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        asyncio.run(main(args))
