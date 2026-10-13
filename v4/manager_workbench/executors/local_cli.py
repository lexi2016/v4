"""A tool-free CLI process using existing host authentication.

The model has no file, shell, browser, MCP, plugin, agent or network tool. Host
authentication belongs to the CLI process, never model-accessible materials.
Capabilities are checked against the installed binary before any model call.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import subprocess
from datetime import datetime
from ..contracts import HK, canonical, digest
from .codex import IsolatedProcessResult, IsolationNotVerified

DISABLED_FEATURES = (
    "shell_tool", "unified_exec", "apps", "browser_use", "browser_use_external",
    "browser_use_full_cdp_access", "computer_use", "hooks", "plugins", "remote_plugin",
    "image_generation", "view_image", "multi_agent", "multi_agent_v2", "code_mode",
    "code_mode_host", "skill_search", "memories", "chronicle", "artifact", "workspace_dependencies",
    "sleep_tool", "in_app_browser", "in_app_local_automation", "standalone_web_search",
    "agent_message_board", "enable_mcp_apps", "code_mode_tool_search",
)


class LocalCliRunner:
    def __init__(self, binary: Path):
        if not binary or not binary.is_absolute() or not binary.is_file():
            raise IsolationNotVerified("CODEX_BINARY_UNAVAILABLE")
        self.binary = binary
        self.proof = self.verify_capabilities()

    def verify_capabilities(self):
        help_result = subprocess.run([str(self.binary), "exec", "--help"], capture_output=True, check=False, timeout=10)
        if help_result.returncode or any(x not in help_result.stdout.decode() for x in
                ("--ignore-user-config", "--ephemeral", "--disable", "--sandbox", "--output-schema", "--json")):
            raise IsolationNotVerified("CODEX_REQUIRED_ISOLATION_OPTIONS_UNAVAILABLE")
        # Read-only inventory. Overrides prevent the host's configured feature defaults
        # from making the inventory appear sufficient when controls are absent.
        args = [str(self.binary)]
        for name in DISABLED_FEATURES:
            args.extend(["--disable", name])
        result = subprocess.run([*args,"features","list"],capture_output=True,check=False,timeout=10)
        lines = {s.split()[0]:s.split()[-1] for s in result.stdout.decode().splitlines() if len(s.split()) >= 3}
        if result.returncode or any(lines.get(name) != "false" for name in DISABLED_FEATURES):
            raise IsolationNotVerified("CODEX_TOOL_DISABLE_CAPABILITY_UNVERIFIED")
        version = subprocess.run([str(self.binary),"--version"],capture_output=True,check=False,timeout=10)
        return {"policy":"MODEL_NO_TOOLS_V1","binary_sha256":hashlib.sha256(self.binary.read_bytes()).hexdigest(),
                "help_sha256":hashlib.sha256(help_result.stdout).hexdigest(),
                "feature_probe_sha256":hashlib.sha256(result.stdout).hexdigest(),
                "disabled_features":list(DISABLED_FEATURES),"web_search":"disabled",
                "ignore_user_config":True,"version":version.stdout.decode().strip()}

    def run(self, *, argv, cwd, stdin, timeout_seconds, role):
        if Path(argv[0]) != self.binary or argv[1] != "exec":
            raise IsolationNotVerified("CODEX_INVOCATION_IDENTITY_MISMATCH")
        if any(x.startswith("--dangerously") or x in {"--add-dir","--worktree"} for x in argv):
            raise IsolationNotVerified("CODEX_UNSAFE_INVOCATION_DENIED")
        enabled={argv[i+1] for i,x in enumerate(argv[:-1]) if x=="--enable"}
        if enabled!={"skip_host_skill_discovery"} or "project_doc_max_bytes=0" not in argv:
            raise IsolationNotVerified("CODEX_HOST_CONTEXT_DISCOVERY_NOT_DISABLED")
        required = {"--ignore-user-config", "--ephemeral", "--json", "--skip-git-repo-check"}
        flags = {argv[i+1] for i,x in enumerate(argv[:-1]) if x == "--disable"}
        if not required.issubset(argv) or not set(DISABLED_FEATURES).issubset(flags) or "mcp_servers={}" not in argv or 'web_search="disabled"' not in argv:
            raise IsolationNotVerified("CODEX_TOOL_POLICY_MISMATCH")
        if sorted(p.name for p in cwd.iterdir()) != ["result.schema.json"]:
            raise IsolationNotVerified("CODEX_MATERIAL_DIRECTORY_NOT_MINIMAL")
        # Retain only normal CLI runtime env and existing CODEX_HOME host identity.
        env = {k:v for k,v in os.environ.items() if k in {
            "PATH","HOME","CODEX_HOME","TMPDIR","LANG","LC_ALL","SSL_CERT_FILE",
            "HTTP_PROXY","HTTPS_PROXY","ALL_PROXY","NO_PROXY","http_proxy","https_proxy","all_proxy","no_proxy"}}
        env["CODEX_BUNDLED_MODE"] = "1"
        started = datetime.now(HK).isoformat()
        process = subprocess.Popen(argv,cwd=cwd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env)
        try:
            out, err = process.communicate(stdin,timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            out, err = process.communicate()
            raise IsolationNotVerified("CODEX_MODEL_EXECUTION_TIMEOUT")
        # Reject any unexpected capability use in the actual event stream. No tool
        # output or raw stderr is exposed to the application or browser.
        events = []
        for line in out.splitlines():
            try: events.append(json.loads(line))
            except ValueError: continue
        disallowed = {"command_execution","mcp_tool_call","web_search","function_call","tool_call",
                      "file_change","image_generation","collab_tool_call"}
        if any(e.get("item",{}).get("type") in disallowed or e.get("type") in disallowed for e in events):
            raise IsolationNotVerified("CODEX_UNEXPECTED_TOOL_EVENT")
        if process.returncode == 0 and not any(e.get("type") == "thread.started" for e in events):
            raise IsolationNotVerified("CODEX_EXECUTION_IDENTITY_UNOBSERVED")
        return IsolatedProcessResult(returncode=process.returncode,pid=process.pid,started_at=started,
            finished_at=datetime.now(HK).isoformat(),event_sha256=hashlib.sha256(out).hexdigest(),
            isolation_proof=json.dumps({**self.proof,"event_stream_sha256":hashlib.sha256(out).hexdigest(),
                                        "observed_tool_events":0},sort_keys=True))
