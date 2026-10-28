"""Independent one-worker capture queue; no HTTP handler or 50-second child.

Persisted jobs use the existing public JobRecord, with an internal operation
scope. Source lease is never granted here. Acquisition and model tasks are
separate jobs; model submission occurs only for a changed factual identity.
"""
from __future__ import annotations
from datetime import datetime
from infrastructure.owned_io import LockAcquireTimeout
from ..contracts import HK,Lane,Phase,JobState,digest
from ..jobs import JobCoordinator,StepFailure
from .capture_store import CaptureStore,OWNER
from .capture import capture_window
from .capture_binding import publish


class CaptureJobs:
    def __init__(self,service, *, transport=None,clock=None):
        self.service=service;self.config=service.config;self.clock=clock or (lambda:datetime.now(HK))
        if transport is None:
            import requests
            transport=requests.Session()
        self.transport=transport
        self.cache=CaptureStore(self.config.capture_root,lease_root=self.config.capture_lease_root,
            token=self.config.capture_lease_token,clock=self.clock)
        self.jobs=JobCoordinator(service.store,workers=1)

    def submit(self,context):
        self.cache.assert_exclusive_owner(OWNER)
        ctx=context.model_copy(deep=True)
        # API and scheduler observations in one minute share the same operation.
        instant=datetime.fromisoformat(ctx.cutoff).astimezone(HK).replace(second=0,microsecond=0)
        if ctx.phase not in {Phase.NEXT_DAY,Phase.RETROSPECTIVE}:ctx.phase=Phase.INTRADAY
        ctx.scope_refs={'requested_lanes':[Lane.ANNOUNCEMENT.value],'capture_operation':'CAPTURE_MATERIAL'}
        key='capture_slot_'+digest(dict(target=ctx.target_date,phase=ctx.phase.value,cutoff=instant.isoformat()))
        with self.service.store.lock(key):
            previous=self.service.store.cursor(key)
            if previous:
                job=self.jobs.get(previous['job_id'])
                if job.state in {JobState.QUEUED,JobState.RUNNING,JobState.SUCCEEDED,JobState.PARTIAL}:return job
                if job.retryable:
                    return self.jobs.submit(job.context,self._work,retry_job_id=job.job_id)
                return job
            job=self.jobs.submit(ctx,self._work)
            self.service.store.set_cursor(key,{'job_id':job.job_id})
            return job

    def retry(self,job):
        self.cache.assert_exclusive_owner(OWNER)
        return self.jobs.submit(job.context,self._work,retry_job_id=job.job_id)

    def _work(self,job):
        try:
            # One actual collector across API/scheduler processes sharing state.
            with self.service.store.io.kernel_lock('capture_owner.lock',timeout=0):
                self.cache.assert_exclusive_owner(OWNER)
                self.jobs.update(job,step='CAPTURE_MATERIAL')
                product=capture_window(job.context,dict(transport=self.transport),self.cache)
                completed=job.context.model_copy(deep=True);completed.cutoff=self.clock().astimezone(HK).isoformat()
                with self.cache.guard():
                    pin=publish(self.config,product,completed,job.job_id)
                    self.service.store.save_checkpoint(job.job_id,'CAPTURE_BINDING_'+pin['capture_binding_sha256'],pin)
                # Outsiders are intentionally isolated; post-submit retrieval is
                # eligible only in this later actual version, never 09:25/PIT.
                failures=[g for g in product['gaps'] if g not in {
                    'ANNOUNCEMENT_OUTSIDE_PUBLICATION_WINDOW','CAPTURE_AVAILABLE_AFTER_RESEARCH_CUTOFF'}]
                job.total_count=product['observed_count']
                job.completed_count=sum(a['body_complete'] or a['window_consumption_status']=='EXCLUDED_OUTSIDE_WINDOW' for a in product['rows'])
                job.failed_steps=['CAPTURE_MATERIAL'] if failures else []
                job.retryable=bool(failures);job.failure_code='CAPTURE_INCOMPLETE' if failures else None
                job.execution_refs.append(dict(kind='capture_material',binding_sha256=pin['capture_binding_sha256'],
                    material_sha256=pin['material_sha256'],source_owner=OWNER))
                phase=Phase.NEXT_DAY if job.context.phase==Phase.NEXT_DAY and self.clock().astimezone(HK).strftime('%Y%m%d')<job.context.target_date else Phase.INTRADAY
                if job.context.phase==Phase.RETROSPECTIVE:phase=Phase.RETROSPECTIVE
                analysis_context=self.service.context(job.context.target_date,phase,trigger='SCHEDULED',
                    cutoff=self.clock(),lanes=[Lane.ANNOUNCEMENT],scope_refs={'capture_incremental':True,'capture_binding_pin':pin})
                eligibility=(analysis_context.scope_refs.get('owner_bindings',{}).get('membership')
                    or self.config.source_bindings.get('membership',{}).get(job.context.target_date))
                analysis_identity=digest(dict(material_sha256=pin['material_sha256'],model=self.config.model,
                    reasoning_effort=self.config.announcement_reasoning_effort,prompt_version=self.config.prompt_version,
                    rules_version=self.config.rules_version,eligibility=eligibility))
                key='capture_analysis_'+job.context.target_date
                with self.cache.guard(), self.service.store.lock(key):
                    old=self.service.store.cursor(key)
                    if not old or old.get('analysis_identity')!=analysis_identity:
                        research=self.service.submit(job.context.target_date,phase,trigger='SCHEDULED',lanes=[Lane.ANNOUNCEMENT],
                            cutoff=self.clock(),scope_refs={'capture_incremental':True,'capture_input_sha256':pin['material_sha256'],'capture_analysis_identity':analysis_identity,
                                'capture_job_id':job.job_id,'capture_binding_pin':pin,
                                'owner_bindings':{**analysis_context.scope_refs.get('owner_bindings',{}),
                                    **({'membership':eligibility} if eligibility else {})}})
                        self.service.store.set_cursor(key,{'material_sha256':pin['material_sha256'],'analysis_identity':analysis_identity,'job_id':research.job_id})
                        job.execution_refs.append({'kind':'incremental_research','job_id':research.job_id})
                return job.run_id,JobState.PARTIAL if failures else JobState.SUCCEEDED
        except LockAcquireTimeout as exc:raise StepFailure('CAPTURE_OWNER_BUSY',retryable=True) from exc
        except (OSError,ValueError,KeyError,TypeError) as exc:
            code='CAPTURE_OWNER_REVOKED' if 'EXCLUSIVE_OWNER' in str(exc) else 'CAPTURE_FAILED'
            raise StepFailure(code,retryable=code!='CAPTURE_OWNER_REVOKED') from exc

    def stop(self):self.jobs.stop()
