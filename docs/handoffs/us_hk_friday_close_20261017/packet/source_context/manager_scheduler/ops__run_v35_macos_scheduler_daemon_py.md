## Source excerpt: `ops/run_v35_macos_scheduler_daemon.py`

Original source path: `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/zsxq-long-pdf-scheduler-20261016-r3/app/ops/run_v35_macos_scheduler_daemon.py`

Original full-file SHA-256: `1d03d0b21e352a772278e326086ef50a4e43dbfdeacb2dbf56111b496773476a`

Release/worktree group: `manager_scheduler`

Loaded daemon chooses WorkbenchHook when the manager workbench binding is present.

### Full-source lines 940-947

```python

    announcement_hook: AnnouncementCycleHook | None = None
    try:
        if os.environ.get("V4_MANAGER_WORKBENCH_CONFIG_PATH", "").strip():
            # Fail closed: never initialize the old capture owner on this branch.
            from v4.manager_workbench.supervisor import WorkbenchHook
            announcement_hook = WorkbenchHook.from_environment(clock=now)
        else:
            announcement_hook = AnnouncementCycleHook.from_environment(clock=now)

```
