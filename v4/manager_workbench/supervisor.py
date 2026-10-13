"""In-process adapter for the existing daemon; jobs have no child deadline."""
from __future__ import annotations
import os
import threading
from datetime import datetime
from .config import load_config
from .binding import create_native_binding
from .service import create_service
from .scheduler import tick
from .contracts import HK
from .inputs.validation import raw_sha

CONFIG_ENV = 'V4_MANAGER_WORKBENCH_CONFIG_PATH'


class WorkbenchHook:
    def __init__(self, config, *, clock=None, binding=None, poll_seconds=1):
        binding = binding or create_native_binding(config)
        self.service = create_service(config,binding['adapters'],binding['engines'],binding['executor'],
            capture_transport=binding.get('capture_transport'),capture_clock=binding.get('capture_clock'))
        self.binding = binding
        self.clock = clock or (lambda:datetime.now(HK))
        self.cancel = threading.Event()
        self.poll_seconds = max(.01,poll_seconds)
        self.last_minute = None
        self.last_result = None
        self.identity = dict(announcement_collection_enabled=config.capture_enabled,plan_material_refresh_only=not config.capture_enabled,
            execution_owner='MANAGER_WORKBENCH',old_manager_owner_excluded=True,
            material_capture_enabled=config.capture_enabled,production_allowed=False,orders_sent=False)
        self.thread = threading.Thread(target=self._run,name='mwb-scheduler-hook',daemon=True)
        self._config_path = None
        self._config_sha = None

    @classmethod
    def from_environment(cls, *, clock=None, start=True):
        path = os.environ.get(CONFIG_ENV,'').strip()
        if not path:return None
        config = load_config(path)
        hook = cls(config,clock=clock)
        from pathlib import Path
        hook._config_path=Path(path)
        hook._config_sha=raw_sha(hook._config_path.read_bytes())
        if start:hook.thread.start()
        return hook

    def once(self):
        # The existing hook is never re-enabled if this binding fails or changes.
        if self._config_path and raw_sha(self._config_path.read_bytes())!=self._config_sha:
            raise ValueError('WORKBENCH_BINDING_REVOKED')
        moment=self.clock()
        minute=moment.astimezone(HK).strftime('%Y%m%d%H%M')
        if minute==self.last_minute:return self.last_result
        self.last_result=tick(self.service,calendar=self.binding['calendar'],stage_feed=self.binding['stage_feed'],at=moment)
        self.last_minute=minute
        return self.last_result

    def _run(self):
        while not self.cancel.is_set():
            try:self.once()
            except Exception as exc:
                # Typed bounded diagnostic; no raw owner bytes or paths.
                self.last_result={'state':'CANNOT_CONFIRM','reason':type(exc).__name__}
            self.cancel.wait(self.poll_seconds)

    def stop(self):
        self.cancel.set()
        if self.thread.is_alive():self.thread.join()
        # Let persisted work finish. No SIGTERM or 50-second subprocess limit.
        self.service.stop()
