# 精简源码快照：共享路由、scheduler binding 与 API 根切换

每段均取自所列现役配置树/发布工具，标明源文件完整字节 SHA 和行号。快照用于快速审阅；源文件 hash 才是身份合同，不能把这些片段当独立可执行源码。

## 8873 API app 同时承载 Stage、经理与 UI

源：`/Users/lexi/Desktop/学习/agents调试/V4_ISSUE32_MAC_20261009/candidate/issue32_preselection_api_actual_r4/app/apps/api/v35_api/app.py`  
SHA-256：`5d344dfe902db37f81e06d1d401e9a7e20ae910d8f7647b732ae2b3ba4f019e5`

Stage 选择 API，行 5109–5120：

```python
    @app.get("/api/v3/manager/stage-selection")
    def manager_stage_selection(
        date: str | None = None,
        stage: str | None = None,
        market: str | None = None,
        limit: int = Query(default=50, ge=1, le=50),
    ) -> dict:
        """Read the manager's exact HK_CONNECT stage lane only.

        The shared stage-center route remains a compatibility projection for
        its historical scheduled-market response.  This dedicated route is a
        narrower boundary for the manager consumer and never falls back to
        the unified or A-share lane.
```

经理路由注册，行 5268–5270：

```python
    app.state.manager_research_service = manager_research_service
    app.include_router(create_manager_research_router(manager_research_service))
    app.include_router(create_manager_workbench_router(resolved_manager_research_state_root))
```

同 app 根挂载统一静态 UI，行 5276–5278：

```python
    dist = Path(__file__).resolve().parents[2] / "web" / "dist"
    if dist.is_dir():
        app.mount("/", _RevalidatingStaticFiles(directory=dist, html=True), name="web")
```

经理路由各自前缀：`manager_research_router.py` SHA `84f65a351e1e44171820cb8698e4198b3084e39b8d0cfe82c6b4bc05595f8073`，函数创建 `/api/v4/manager/research`；`manager_workbench_router.py` SHA `95ccda85ff50d44cffbb18fc655e417f926c14b27a60cfa4c5fad17a3cbd1b5e`，函数创建 `/api/v4/manager/workbench-research`。

## 独立 scheduler app 读取经理 binding

源：`/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/issue32-preselection-scheduler-mac-20261009-r1/app/ops/run_v35_macos_scheduler_daemon.py`  
SHA-256：`19e071da0c6b6748465853c4ad86a80d6060524333e9dab21647b67adc8b49ec`

行 34–42 定义 scheduler 对 announcement binding、经理 app、cycle 与 checksum 的运行入口：

```python
ANNOUNCEMENT_BINDING_SCHEMA = "v4.manager_research.announcement_binding.v1"
ANNOUNCEMENT_BINDING_ENV = "V4_MANAGER_ANNOUNCEMENT_BINDING"
ANNOUNCEMENT_APP_ENV = "V4_MANAGER_ANNOUNCEMENT_APP_ROOT"
ANNOUNCEMENT_PYTHON_ENV = "V4_MANAGER_ANNOUNCEMENT_PYTHON"
ANNOUNCEMENT_PYTHON_SHA_ENV = "V4_MANAGER_ANNOUNCEMENT_PYTHON_SHA256"
ANNOUNCEMENT_CYCLE_SHA_ENV = "V4_MANAGER_ANNOUNCEMENT_CYCLE_SHA256"
ANNOUNCEMENT_PLAN_CANARY_SHA_ENV = "V4_MANAGER_ANNOUNCEMENT_PLAN_CANARY_SHA256"
ANNOUNCEMENT_CYCLE_RELATIVE = "ops/run_manager_announcement_cycle.py"
```

行 223–256 从环境变量加载 binding、核验 JSON/schema、安全 flags 与显式执行根：

```python
def _load_announcement_binding(environment: dict[str, str]) -> dict[str, Any] | None:
    binding_text = environment.get(ANNOUNCEMENT_BINDING_ENV, "").strip()
    if not binding_text:
        return None
    expected = {
        ANNOUNCEMENT_APP_ENV: environment.get(ANNOUNCEMENT_APP_ENV, "").strip(),
        ANNOUNCEMENT_PYTHON_ENV: environment.get(ANNOUNCEMENT_PYTHON_ENV, "").strip(),
        ANNOUNCEMENT_PYTHON_SHA_ENV: environment.get(ANNOUNCEMENT_PYTHON_SHA_ENV, "").strip(),
        ANNOUNCEMENT_CYCLE_SHA_ENV: environment.get(ANNOUNCEMENT_CYCLE_SHA_ENV, "").strip(),
    }
    if any(not value for value in expected.values()):
        raise DaemonConfigurationError("announcement environment pins are incomplete")
    binding_path = _exact_path(binding_text)
    if (
        binding.get("schema_version") != ANNOUNCEMENT_BINDING_SCHEMA
        or type(binding.get("enabled")) is not bool
        or binding.get("policy_status") != "PROPOSAL_ONLY"
        or binding.get("policy") not in {"BALANCED_V1", "LOW_LOAD_V1"}
        or binding.get("production_allowed") is not False
        or binding.get("buy_gate_updated") is not False
        or binding.get("orders_sent") is not False
        or binding.get("research_only") is not True
    ):
        raise DaemonConfigurationError("announcement binding contract is unsafe or unsupported")
```

Current scheduler binding details are in `current_runtime_identity.json`; that file records configured roots, not internal Python `module.__file__` values.

## API-only release tool changes the whole API pointer

Source: `/Users/lexi/Desktop/学习/agents调试/V4_ISSUE32_MAC_20261009/tools/api_only_cutover_issue32_r4.py`  
SHA-256: `864a07b9bdf915a14b877eac89ddc931bb0f4976b70599c242671ff177e9cf25`

The tool docstring (lines 2–9) limits writes to the API plist, shared pointer lock and task evidence, while scheduler, binding and manager state are read-only. In the actual switch code, lines 2002–2010 atomically replace the API plist and bootstrap/read back the candidate; it does not switch a manager-only app root. This source was read but not executed in this task.

