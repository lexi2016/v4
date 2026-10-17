# Sanitized runtime identity and dispatch excerpt

This note records only identity labels, required environment-variable names, release ownership and typed outcomes needed to reproduce the issue. It contains no credential values, user-specific tokens, raw log payloads or service mutations.

| Component | Loaded identity | Read-only observation | Source anchor |
|---|---|---|---|
| US digest dispatcher | `futu-industry-us-20261016-r1` | The LaunchAgent has no `EnvironmentVariables` binding for `V35_APP_ROOT`, `V35_RELEASE_ID`, `V35_RELEASE_MANIFEST_PATH`, or `V35_RELEASE_MANIFEST_SHA256`. The dispatcher requires the release identity and fails closed with `RELEASE_IDENTITY`; the first current failure is 2026-10-14 21:00 HKT and starts zero workloads. | `audit/READ_ONLY_AUDIT.md`; `source_context/us_digest/infrastructure__scheduling__dispatcher_py.md` |
| Manager scheduler | `zsxq-long-pdf-scheduler-20261016-r3` | Loaded LaunchAgent points to the r3 app source root; its Python runtime root is a separate v15 runtime. The manager process is reported running. | `audit/READ_ONLY_AUDIT.md`; `source_context/manager_scheduler/` |
| Selector API | `announcement-continuation-api-20261017-r11c` | `NativeAdapters.us_mapping` invokes the dynamic binding route. The source excerpt is included separately from the catalog loader because a catalog read is not proof the selector consumes its projection. | `source_context/api/v4__manager_workbench__inputs__native_py.md`; `source_context/api/v4__manager_workbench__inputs__source_bindings_py.md` |

Date evidence: the Shanghai `2026-10-17 04:15` slot resolves to US session `20261016`; the next HK session is `20261020` because `20261019` is an HKEX holiday. The current US slot payload reports scheduled/business/target date as `20261017`. The scheduler had already written the target-`20261020` draft before the US session closed and no post-close event/consumer receipt was found.

Status is intentionally limited to the read-only audit: no natural post-close selector result, refreshed UI, or notification receipt is established here. Exact hidden identity sub-check remains `CANNOT_CONFIRM` because the dispatcher log records only `RELEASE_IDENTITY`.
