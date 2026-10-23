# Local saved V4 reader — setup and approval boundary

This is a local implementation candidate for **嘻嘻**, the user's dot. It does not connect that dot automatically. No listening gateway, tunnel, deployment credential, OAuth application, dependency installation, startup job or plugin has been configured.

## Existing runtime and local checks

Use the already-installed Python 3.14 runtime with FastAPI, HTTPX, pytest and Uvicorn. No package installation is required for the checks performed here. Run from the source/worktree repository root; use an explicit runtime path suitable for this Mac.

```sh
"$V4_READER_PYTHON" -B -m pytest -q -c /dev/null -p no:cacheprovider \
  --basetemp=integrations/chatgpt_readonly/local_only/pytest-new-run \
  integrations/chatgpt_readonly/tests/test_gateway.py

"$V4_READER_PYTHON" -B -m integrations.chatgpt_readonly.schema

"$V4_READER_PYTHON" -B -m integrations.chatgpt_readonly.verify_saved \
  --pool-root "$V4_READER_POOL_ROOT" \
  --workbench-root "$V4_READER_WORKBENCH_ROOT" \
  --trade-date 20261022 --announcement-date 20261021
```

The last command uses an in-process ASGI client and a public test fixture credential; it opens no listener and deploys no credential. It compares saved records and writes only an ignored local evidence file. The 20261022/20261021 example dates were explicitly selected for this acceptance run; they are not latest-date defaults. Pytest temporary files stay inside this task's ignored directory rather than touching unrelated old temporary directories.

`openapi.yaml` is JSON-compatible YAML 1.2. It can be imported as OpenAPI. The server is deliberately `https://v4-readonly.example.invalid` until an approved deployment is actually verified. Schema export opens no server or source data.

## Manual serving — NOT RUN, separate approval required

After approving the dedicated secret and the exact local serving arrangement, provide **only a newly authorized** `V4_READONLY_API_TOKEN` through the approved secret-setting channel. Do not put its value in a chat, URL, command argument, source file or handoff. The entry point does not generate or persist secrets and never reads existing V4/OpenAI/browser credentials. Missing, short or recognizable test/placeholder credentials are refused by the manual server entry.

```sh
"$V4_READER_PYTHON" -B -m integrations.chatgpt_readonly \
  --pool-root "$V4_READER_POOL_ROOT" \
  --workbench-root "$V4_READER_WORKBENCH_ROOT" \
  --port 8887 --concurrency 1
```

This is a foreground server. It binds **only `127.0.0.1`**; binding atomically checks for a port conflict. It refuses the original 8873 and Vibe 8910 ports and cannot accept a host override. Access logs and proxy-header trust are disabled. No startup/persistence mechanism is included.

Default limits: one active read, configurable to two after resource consideration; 60 accepted requests/minute; 50 rows/page; 64,000 response bytes; 64 MiB/source file; eight-second cooperative source deadline and a ten-second HTTP read deadline. A timed-out worker retains its concurrency slot until it exits, preventing an abandoned-worker queue. A 128 GiB Mac was observed with ample free memory; the real-record canary completed in under one second. No throughput expansion was needed.

## Consumer and network decisions still required

The user clarified that the target is the desktop dot **嘻嘻**, not a newly created custom GPT. Official documentation says dots can use supported plugins enabled for their account. The tools available in this task cannot inspect that dot's settings, and native UI inspection of the application was rejected by the platform. Its actual available plugin/authentication controls remain **CANNOT_CONFIRM**.

The proposed next route is: **嘻嘻 → approved read-only MCP plugin → existing saved-data projection**. The GET-only REST gateway is reusable internally, but it is not an MCP server. A separate, approved MCP transport and compatible authentication are still needed. Read-only MCP tool calls use protocol POST and should be marked `readOnlyHint=true`; do not weaken the REST route whitelist to achieve this. A custom GPT could instead use the provided OpenAPI and its Actions API Key authentication, but that would not connect 嘻嘻.

Before any next action, present the exact object, exposure/permissions, cost and rollback and get the task's separate approval for:

1. A domain, HTTPS/public gateway or private tunnel, provider/account and any paid resource. No provider is selected, so costs are **NOT_SELECTED**, not assumed free.
2. A new dedicated credential or OAuth setup; user entry through the safe configuration channel. No reuse of old service credentials.
3. Any new dependency, persistent/background service, firewall/system/network permission or remote connection.
4. Installing/enabling/configuring the actual plugin in the dot's account. No new/restored/delegated Codex or Mac task and no message to 嘻嘻 is authorized by this handoff.

For a public Actions endpoint, official requirements remain HTTPS 443, a valid public certificate and TLS 1.2+. This implementation keeps a 10-second/64,000-byte budget within the documented 45-second/100,000-character Actions bounds. A dot/MCP deployment must use its own currently supported authentication; Actions API Key settings are not interchangeable with MCP OAuth. A private Secure MCP Tunnel is an alternative to assess after approval, not something configured here.

## Rollout and rollback

First admit only the required saved-data tools, then verify externally using the same exact dates and source hashes. Finally have **嘻嘻 itself** invoke the installed tool. Record the consumer tool name, date, source/version and result. External curl/HTTP success alone is insufficient.

Rollback stops only the newly approved foreground gateway/transport, disables the new plugin/entry and revokes its newly issued credential. There is no V4 data restoration, original process restart, formula change or original 8873 rebinding involved.

## Official references checked on 2026-10-23

- [Dots: computers and apps](https://learn.chatgpt.com/docs/dots/computers-and-apps)
- [Add a custom MCP server](https://developers.openai.com/api/docs/guides/custom-mcp-server)
- [GPT Actions setup](https://developers.openai.com/api/docs/actions/getting-started)
- [Actions authentication](https://developers.openai.com/api/docs/actions/authentication)
- [Actions network and size requirements](https://developers.openai.com/api/docs/actions/production)

Account-specific availability and permissions have not been inferred from those general documents.
