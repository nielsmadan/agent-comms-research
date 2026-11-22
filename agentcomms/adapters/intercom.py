import json
import re
import shutil
import time
from functools import cache
from pathlib import Path

from agentcomms import procs
from agentcomms.adapters.bridge import (
    BASE_PATH,
    AgentRoute,
    BridgeAdapter,
    require_owned_daemon,
    run_cli,
    run_dir,
    stop_pid,
    wait_for,
)
from agentcomms.adapters.native import now, receipt, unwrap_cross_session
from agentcomms.adapters.pi_ext import VENDOR, vendored
from agentcomms.model import AgentName, Backend, LaunchMods, SendReceipt, Target
from agentcomms.paths import REPO_ROOT, SOCKET_DIR

BROKER_RESPAWN_S = 20.0
CCI_YOLO_NA = "cci launches Claude with --yolo, so the configured mode shows no permission dialog"
COI_RESUME_NA = ("not measured: coi wraps the Codex TUI with its own arguments, and `coi … resume <id>` is rejected "
                 "by codex (`unexpected argument '<work dir>'`), so the killed session cannot be resumed through the "
                 "bridge")
PI_PKG = VENDOR / "agent-intercom-pi"
CLAUDE_PKG = VENDOR / "agent-intercom-claude"
PI_EXTENSION = PI_PKG / "index.ts"
CCI = CLAUDE_PKG / "dist" / "cci.mjs"
CODEX_PKG = VENDOR / "agent-intercom-codex"
COI = CODEX_PKG / "dist" / "coi.mjs"
CODEX_MCP = CODEX_PKG / "dist" / "codex-server.mjs"
TSX = PI_PKG / "node_modules" / "tsx" / "dist" / "cli.mjs"
SEND = REPO_ROOT / "agentcomms" / "intercom" / "send.mts"
ACCEPT = json.dumps({"crossSessionInbound": "accept"})
NATIVE_REPLY_PEER = "the native intercom peer that delivered this message (native mode can only reply)"
CROSS_MACHINE = ("agent-intercom-pi README: \"Same-machine only by design\" (Unix socket broker); remote-access-v1 "
                 "registrations (`remote-gateway.sock`, remote-tree policy) exist in the broker for remote hosts")
PI_FRAME = re.compile(r"\A\*\*(?:\[\d+/\d+\] )?📨 From [^\n]*\*\*(?: \([^\n]*\))?"
                      r"(?:\n\nTo reply, use: [^\n]*)?\n\n(.*)\Z", re.S)
COI_FRAME = re.compile(r"\AIntercom message for [^\n]*\nFrom: [^\n]*\nMessage id: [^\n]*\n\n(.*?)\n*\Z", re.S)
NATIVE_FRAME = re.compile(r"\A\[Intercom message from [^\n]*\]\n(.*?)\n(?:\n[^\n]*)?\n\n(?:Act if needed|The sender is "
                          r"blocking)\..*\Z", re.S)


def state_dir(work_dir: Path) -> Path:
    return run_dir(work_dir) / "ic" / "intercom"


def agent_dir(work_dir: Path) -> Path:
    return SOCKET_DIR / f"{run_dir(work_dir).name}-ic"


def pi_agent_dir(work_dir: Path) -> Path:
    return SOCKET_DIR / f"{run_dir(work_dir).name}-pih-{work_dir.name}"


def runtime_dir(work_dir: Path) -> Path:
    return SOCKET_DIR / f"{run_dir(work_dir).name}-icr"


def link(path: Path, target: Path) -> None:
    if not path.is_symlink():
        path.symlink_to(target)


def node() -> str:
    found = shutil.which("node")
    if not found:
        raise FileNotFoundError("node not on PATH")
    return str(Path(found).resolve())


def unwrap_intercom(recorded: str) -> str:
    framed = PI_FRAME.match(recorded) or COI_FRAME.match(recorded)
    if framed:
        return framed.group(1)
    inner = unwrap_cross_session(recorded)
    native = NATIVE_FRAME.match(inner)
    return native.group(1).rstrip("\n") if native else inner


def codex_mcp_flags(node_bin: str, work_dir: Path) -> tuple[str, ...]:
    return ("-c", f"mcp_servers.codex-intercom.command={json.dumps(node_bin)}",
            "-c", f"mcp_servers.codex-intercom.args={json.dumps([str(CODEX_MCP)])}",
            "-c", f"mcp_servers.codex-intercom.env.PI_CODING_AGENT_DIR={json.dumps(str(agent_dir(work_dir)))}",
            "-c", 'mcp_servers.codex-intercom.default_tools_approval_mode="approve"')


def cli_env(work_dir: Path) -> dict[str, str]:
    return {"PATH": BASE_PATH, "HOME": str(agent_dir(work_dir)), "LANG": "en_US.UTF-8",
            "PI_CODING_AGENT_DIR": str(agent_dir(work_dir)), "NODE_NO_WARNINGS": "1"}


def send_argv(*args: str) -> list[str]:
    return [node(), str(vendored(TSX)), str(SEND), *args]


def sessions(work_dir: Path) -> list[dict]:
    out = run_cli(send_argv("--list"), cli_env(work_dir), cwd=run_dir(work_dir), timeout_s=20)
    try:
        data = json.loads(out.stdout.strip().splitlines()[-1]) if out.code == 0 and out.stdout.strip() else []
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def session_for(entries: list[dict], work_dir: Path) -> dict | None:
    return next((e for e in entries if e.get("cwd") == str(work_dir)), None)


def broker_pid(work_dir: Path) -> int | None:
    try:
        text = (state_dir(work_dir) / "broker.owner").read_text().strip()
    except OSError:
        return None
    return int(text) if text.isdigit() else None


def respawned_broker(work_dir: Path, old: int) -> int | None:
    pid = broker_pid(work_dir)
    return pid if pid and pid != old and procs.alive(pid) else None


@cache
def package_version(pkg: Path) -> str:
    try:
        version = json.loads((pkg / "package.json").read_text())["version"]
    except (OSError, KeyError, json.JSONDecodeError):
        version = "unknown"
    try:
        return f"{version}+{(pkg / '.git' / 'HEAD').read_text().strip()[:8]}"
    except OSError:
        return version


class Intercom(BridgeAdapter):
    shared_run = True
    shared_state = "intercom"
    name = "intercom"
    agents: frozenset[AgentName] = frozenset({"pi", "claude", "codex"})
    claims_cross_machine = CROSS_MACHINE
    claude_settings: str | None = None
    bridge_daemon = True

    def scenario_not_applicable(self, agent: AgentName, scenario: str) -> str | None:
        return {("claude", "S3"): CCI_YOLO_NA, ("codex", "S6"): COI_RESUME_NA}.get((agent, scenario))

    def restart_backend(self, target: Target) -> str | None:
        old = require_owned_daemon(run_dir(target.work_dir), broker_pid(target.work_dir), "intercom broker")
        t0 = time.time()
        stop_pid(old, group=False)
        t1 = time.time()
        new = wait_for(lambda: respawned_broker(target.work_dir, old), BROKER_RESPAWN_S)
        t2 = time.time()
        after = f"respawned by a client as pid {new} after {t2 - t1:.1f}s" if new else \
            f"not respawned within {BROKER_RESPAWN_S:.0f}s"
        return f"intercom broker stop, pid {old}; stop {t1 - t0:.1f}s; {after}"

    @classmethod
    def backend_for(cls, agent: AgentName) -> Backend:
        return "codex-app-server" if agent == "codex" else "none"

    def bridge_versions(self) -> dict[str, str]:
        return {"agent-intercom-pi": package_version(PI_PKG), "agent-intercom-claude": package_version(CLAUDE_PKG),
                "agent-intercom-codex": package_version(CODEX_PKG)}

    def prepare_launch(self, agent: AgentName, work_dir: Path, home_dir: Path) -> None:
        state_dir(work_dir).mkdir(parents=True, exist_ok=True, mode=0o700)
        SOCKET_DIR.mkdir(parents=True, exist_ok=True)
        link(agent_dir(work_dir), state_dir(work_dir).parent)
        if agent == "pi":
            link(home_dir / "intercom", state_dir(work_dir))
            link(pi_agent_dir(work_dir), home_dir)
        if agent == "claude":
            runtime_dir(work_dir).mkdir(parents=True, exist_ok=True, mode=0o700)

    def launch_mods(self, agent: AgentName, work_dir: Path, home_dir: Path) -> LaunchMods:
        if agent == "pi":
            return LaunchMods(host="tmux", extra_args=("-e", str(vendored(PI_EXTENSION))),
                              env={"PI_CODING_AGENT_DIR": str(pi_agent_dir(work_dir))})
        if agent == "codex":
            return LaunchMods(host="tmux", backend="codex-app-server",
                              launcher=(node(), str(vendored(COI)), "--name", work_dir.name, "--cwd", str(work_dir),
                                        "--no-intercom-shortcut", *codex_mcp_flags(node(), work_dir)),
                              env={"PI_CODING_AGENT_DIR": str(agent_dir(work_dir)),
                                   "CODEX_INTERCOM_CODEX_COMMAND": "codex"})
        extra = ("--settings", self.claude_settings) if self.claude_settings else ()
        launcher = (node(), str(vendored(CCI)), "--tui", "--transport", "native", "--claude", "claude", "--cwd",
                    str(work_dir), "--name", work_dir.name, "--id", f"{run_dir(work_dir).name}-{work_dir.name}",
                    "--yolo")
        return LaunchMods(host="tmux", launcher=launcher, args_in_shim=True, extra_args=extra,
                          env={"PI_CODING_AGENT_DIR": str(agent_dir(work_dir)),
                               "XDG_RUNTIME_DIR": str(runtime_dir(work_dir))})

    def ready_pids(self, target: Target) -> list[int]:
        pid = broker_pid(target.work_dir)
        return [pid] if pid else []

    def send(self, target: Target, text: str) -> SendReceipt:
        if not session_for(sessions(target.work_dir), target.work_dir):
            return receipt(now(), False, "intercom: no session registered for the target's work dir")
        return self.cli_send(send_argv("--cwd", str(target.work_dir)), cli_env(target.work_dir), text, "intercom",
                             cwd=run_dir(target.work_dir))

    def unwrap(self, recorded: str) -> str:
        return unwrap_intercom(recorded)

    def sender_argv(self, target: Target) -> list[str] | None:
        return None

    def agent_route(self, target: Target, sender_agent: AgentName) -> AgentRoute | None:
        found = session_for(sessions(target.work_dir), target.work_dir)
        if not found or not found.get("name"):
            return None
        identity = (found["name"], found.get("id", ""))
        if sender_agent == "claude":
            return AgentRoute("name", NATIVE_REPLY_PEER, identity, tool="SendMessage")
        return AgentRoute("name", found["name"], identity, tool="intercom_send")


class IntercomAccept(Intercom):
    name = "intercom-accept"
    claude_settings = ACCEPT
