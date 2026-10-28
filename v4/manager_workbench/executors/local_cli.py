"""A tool-free CLI process using existing host authentication.

The fixed model profile exposes only the independently checked Code Mode entry,
whose host rejects tool access; ordinary host tools remain disabled. Host
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

VERIFIED_BINARY_SHA256 = "0d5ac7aae20c4eda6242428d5e218c55ba96d8763fda2a271088ff37104b9d28"
SKILL_LIMITS = ("skills.include_instructions=false", "skills.bundled.enabled=false", "cloud.skills.enabled=false")
ISOLATION_REVIEW_SHA256 = "9e3d65a3fe54801289d6402f4644caa5810659e9032c09a15ca53c0692403a3a"


def process_environment():
    # Parent LaunchAgents deliberately use NO_PROXY=*. Only this model child
    # inherits the user's verified local system proxy and local bypass list.
    env={k:v for k,v in os.environ.items() if k in {
        "PATH","HOME","CODEX_HOME","TMPDIR","LANG","LC_ALL","SSL_CERT_FILE"}}
    env["CODEX_BUNDLED_MODE"]="1"
    probe=subprocess.run(["/usr/sbin/scutil","--proxy"],capture_output=True,check=False,timeout=5)
    text=probe.stdout.decode()
    import re
    settings=dict(re.findall(r"^\s*(HTTPSEnable|HTTPSProxy|HTTPSPort|HTTPEnable|HTTPProxy|HTTPPort)\s*:\s*(\S+)\s*$",text,re.M))
    if all(settings.get(k)==v for k,v in {"HTTPEnable":"1","HTTPSEnable":"1","HTTPProxy":"127.0.0.1","HTTPSProxy":"127.0.0.1","HTTPPort":"7897","HTTPSPort":"7897"}.items()):
        for key in ("HTTP_PROXY","HTTPS_PROXY","http_proxy","https_proxy"):env[key]="http://127.0.0.1:7897"
        for key in ("NO_PROXY","no_proxy"):env[key]="localhost,127.0.0.1,::1"
    return env


DISABLED_FEATURES = (
    "shell_tool", "unified_exec", "apps", "browser_use", "browser_use_external",
    "browser_use_full_cdp_access", "computer_use", "hooks", "plugins", "remote_plugin",
    "image_generation", "view_image", "multi_agent", "multi_agent_v2", "code_mode",
    "code_mode_host", "skill_search", "memories", "chronicle", "artifact", "workspace_dependencies",
    "sleep_tool", "in_app_browser", "in_app_local_automation", "standalone_web_search",
    "agent_message_board", "enable_mcp_apps", "code_mode_tool_search",
)


def invocation_profile(binary,workspace,*,model="gpt-6-luna",reasoning_effort="max"):
    argv=[str(binary),"exec","--ignore-user-config","--ephemeral","--json",
        "--enable","skip_host_skill_discovery","-c","project_doc_max_bytes=0",
        "--skip-git-repo-check","--model",model,"--sandbox","read-only","-c","mcp_servers={}",
        "-c",'web_search="disabled"',"-c",f'model_reasoning_effort="{reasoning_effort}"',
        "--output-schema",str(workspace/"result.schema.json"),
        "--output-last-message",str(workspace/"result.json"),"-"]
    for setting in SKILL_LIMITS:argv[2:2]=["-c",setting]
    for feature in DISABLED_FEATURES:argv[2:2]=["--disable",feature]
    return argv


class LocalCliRunner:
    def __init__(self, binary: Path):
        if not binary or not binary.is_absolute() or not binary.is_file():
            raise IsolationNotVerified("CODEX_BINARY_UNAVAILABLE")
        if hashlib.sha256(binary.read_bytes()).hexdigest()!=VERIFIED_BINARY_SHA256:
            raise IsolationNotVerified("CODEX_BINARY_REVIEW_IDENTITY_CHANGED")
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
        if result.returncode or any(lines.get(name) != "false" for name in DISABLED_FEATURES if name != "unified_exec") or lines.get("unified_exec") not in {"true","false"}:
            raise IsolationNotVerified("CODEX_TOOL_DISABLE_CAPABILITY_UNVERIFIED")
        version = subprocess.run([str(self.binary),"--version"],capture_output=True,check=False,timeout=10)
        return {"policy":"MODEL_NO_TOOLS_V1","binary_sha256":hashlib.sha256(self.binary.read_bytes()).hexdigest(),
                "help_sha256":hashlib.sha256(help_result.stdout).hexdigest(),
                "feature_probe_sha256":hashlib.sha256(result.stdout).hexdigest(),
                "disabled_features":list(DISABLED_FEATURES),"web_search":"disabled",
                "ignore_user_config":True,"version":version.stdout.decode().strip(),
                "tool_registration_boundary":"INDEPENDENTLY_VERIFIED_CODE_MODE_ONLY_HOST_DENIAL",
                "independent_review_sha256":ISOLATION_REVIEW_SHA256,"skills_limits":list(SKILL_LIMITS)}

    def run(self, *, argv, cwd, stdin, timeout_seconds, role):
        if hashlib.sha256(self.binary.read_bytes()).hexdigest()!=VERIFIED_BINARY_SHA256:
            raise IsolationNotVerified("CODEX_BINARY_REVIEW_IDENTITY_CHANGED")
        if not set(SKILL_LIMITS).issubset(argv):raise IsolationNotVerified("CODEX_SKILLS_CONTEXT_NOT_DISABLED")
        if '--model' not in argv or argv[argv.index('--model')+1]!='gpt-6-luna' or 'model_reasoning_effort="max"' not in argv:
            raise IsolationNotVerified("CODEX_MODEL_REVIEW_IDENTITY_CHANGED")
        if '--sandbox' not in argv or argv[argv.index('--sandbox')+1]!='read-only':
            raise IsolationNotVerified("CODEX_SANDBOX_POLICY_CHANGED")
        if argv != invocation_profile(self.binary,cwd):
            raise IsolationNotVerified("CODEX_FIXED_PROFILE_CHANGED")
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
        env = process_environment()
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
                                        "observed_tool_events":0, "argv_sha256":digest(argv), "network_route":"CURRENT_SYSTEM_LOOPBACK_PROXY" if "HTTPS_PROXY" in env else "DIRECT", "proxy_bypass":env.get("NO_PROXY") },sort_keys=True))
