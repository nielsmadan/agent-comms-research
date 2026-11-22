import hashlib
import json
import re
import shlex
import shutil
import subprocess
import time
from functools import cache
from pathlib import Path

from agentcomms import backends
from agentcomms.adapters.bridge import (
    BASE_PATH,
    LIFECYCLE_NA,
    AgentRoute,
    BridgeAdapter,
    contained_path,
    pinned_inner,
    require_owned_daemon,
    run_cli,
    run_dir,
    stop_pid,
    tool_wrapper,
    tools_dir,
)
from agentcomms.adapters.csd import write_exec
from agentcomms.adapters.native import now, receipt
from agentcomms.adapters.opencode_server import free_port
from agentcomms.adapters.pi_ext import VENDOR, vendored
from agentcomms.adapters.tmux import unwrap_paste_reference
from agentcomms.hosts.tmux import env_wrapped, private_env_argv, socket_args, split_secret_env
from agentcomms.isolation import IsolationError
from agentcomms.model import AgentName, LaunchMods, SendReceipt, Target
from agentcomms.paths import REPO_ROOT, TMUX_SOCKET

GC = VENDOR / "gc" / "bin" / "gc"
GC_VERSION = "1.4.0"
GC_SHA256 = "be347301574e657a22a822e06d2c79d6fce949e6c89a2b3d8d7265dcb97ecc81"
SESSION_WAIT_S = 120.0
BLOCKED_TOOLS = ("gc", "mise")
HOOK_BIN_DIRS = ("go/bin", ".local/bin")
STARTUP_MARKER = "Run `gc prime`"
CROSS_MACHINE = ("Gas City README: runtime providers include k8s and ACP; `gc supervisor` manages cities machine-wide "
                 "(no cross-machine nudge path documented for the tmux provider)")


REMINDER = re.compile(r"\A\s*(?:<|&lt;)system-reminder(?:>|&gt;)\nYou have a deferred reminder that was queued until a "
                      r"safe boundary:\n\n- \[[^\]\n]*\] (.*?)\n\nHandle them after this turn\.\n"
                      r"(?:<|&lt;)/system-reminder(?:>|&gt;)\s*\Z", re.S)


def unwrap_reminder(recorded: str) -> str:
    m = REMINDER.match(recorded)
    return m.group(1) if m else recorded


def gc_root(work_dir: Path) -> Path:
    return run_dir(work_dir) / "gc" / work_dir.name


def city_dir(work_dir: Path) -> Path:
    return gc_root(work_dir) / "city"


def gc_home(work_dir: Path) -> Path:
    return gc_root(work_dir) / "home"


def agent_home(work_dir: Path) -> Path:
    return gc_root(work_dir) / "agent-home"


def agent_name(work_dir: Path) -> str:
    return f"recv-{work_dir.name}"


def city_name(work_dir: Path) -> str:
    return f"ac{run_dir(work_dir).name.replace('-', '')[-10:]}-{work_dir.name}"


def city_socket(work_dir: Path) -> str:
    return f"{TMUX_SOCKET}-{run_dir(work_dir).name}-{work_dir.name}"


def shim_dir(work_dir: Path) -> Path:
    return run_dir(work_dir) / "bin" / f"gc-{work_dir.name}"


def supervisor_pid_file(work_dir: Path) -> Path:
    return gc_home(work_dir) / "harness-supervisor.pid"


def send_script(work_dir: Path) -> Path:
    return gc_home(work_dir) / f"send-{work_dir.name}"


def gc_env(work_dir: Path) -> dict[str, str]:
    home = gc_home(work_dir)
    return {"PATH": f"{shim_dir(work_dir)}:{BASE_PATH}", "HOME": str(home), "GC_HOME": str(home),
            "GC_BEADS": "file", "GC_CEILING_DIRECTORIES": str(run_dir(work_dir)), "LANG": "en_US.UTF-8",
            "TERM": "xterm-256color"}


def pinned_gc_env(work_dir: Path) -> dict[str, str]:
    return gc_env(work_dir) | {"GC_CITY": str(city_dir(work_dir))}


def agent_pins(work_dir: Path, user_path: str) -> dict[str, str]:
    return {"HOME": str(agent_home(work_dir)), "PATH": contained_path(user_path, (str(tools_dir(work_dir)),),
                                                                      BLOCKED_TOOLS),
            "GC_CITY": str(city_dir(work_dir)), "GC_HOME": str(gc_home(work_dir)),
            "GC_CEILING_DIRECTORIES": str(run_dir(work_dir)), "GC_BEADS": "file"}


def gc_tool(work_dir: Path) -> str:
    return tool_wrapper(pinned_gc_env(work_dir), [str(GC), "--city", str(city_dir(work_dir))])


def tmux_bin() -> str:
    return shutil.which("tmux") or "/opt/homebrew/bin/tmux"


def tmux_shim(work_dir: Path, tmux: str, conf: Path) -> str:
    return f'#!/bin/sh\nexec {shlex.join([tmux, *socket_args(city_socket(work_dir)), "-f", str(conf)])} "$@"\n'


def city_toml(work_dir: Path, command: Path, process: str) -> str:
    return "\n".join([
        "[workspace]", f'name = "{city_name(work_dir)}"', 'provider = "acshim"', "",
        "[providers.acshim]", f"command = {json.dumps(str(command))}", 'prompt_mode = "none"', "ready_delay_ms = 3000",
        f"process_names = {json.dumps([process])}", "",
        "[session]", f'socket = "{city_socket(work_dir)}"', "",
        "[beads]", 'provider = "file"', "",
        "[[agent]]", f'name = "{agent_name(work_dir)}"', 'provider = "acshim"',
        f"work_dir = {json.dumps(str(work_dir))}", "",
        "[[named_session]]", f'template = "{agent_name(work_dir)}"', 'mode = "always"', "",
    ])


def registry_toml(work_dir: Path) -> str:
    return f'[[cities]]\npath = {json.dumps(str(city_dir(work_dir)))}\nname = "{city_name(work_dir)}"\n'


def gc(*args: str) -> list[str]:
    return [str(vendored(GC)), *args]


def session_name(listing: str, agent: str) -> str | None:
    try:
        data = json.loads(listing)
    except json.JSONDecodeError:
        return None
    rows = data if isinstance(data, list) else data.get("sessions", []) if isinstance(data, dict) else []
    live = [r for r in rows if isinstance(r, dict) and r.get("session_name")
            and agent in (r.get("alias"), r.get("template"), r.get("agent"), r.get("name"))]
    return live[0]["session_name"] if live else None


def send_wrapper(work_dir: Path) -> str:
    env = [f"{k}={v}" for k, v in sorted(pinned_gc_env(work_dir).items())]
    command = shlex.join(["/usr/bin/env", "-i", *env, str(GC), "--city", str(city_dir(work_dir)), "session", "nudge",
                          agent_name(work_dir)])
    return f'#!/bin/sh\nexec {command} "$(cat)"\n'


def supervisor_toml(port: int) -> str:
    return f'[supervisor]\nport = {port}\nbind = "127.0.0.1"\n'


def require_run_env(env: dict[str, str], root: Path) -> None:
    outside = [k for k in ("HOME", "GC_HOME", "GC_CITY", "GC_CEILING_DIRECTORIES")
               if k in env and not Path(env[k]).resolve().is_relative_to(root.resolve())]
    if outside:
        raise IsolationError(f"gc env outside the run: {', '.join(outside)}")


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@cache
def gc_version() -> str:
    digest = file_sha256(vendored(GC))
    return GC_VERSION if digest == GC_SHA256 else f"unknown (sha256 {digest[:12]})"


GC_PRIME_NA = ("not measured: gc's startup beacon makes the agent run `gc prime`, which in the prompting mode does "
               "not settle within the startup wait, so the approved.txt dialog cannot be isolated")


def start_supervisor(cwd: Path, env: dict[str, str]) -> subprocess.Popen:
    with open(gc_root(cwd) / "gc-supervisor.log", "ab") as log:
        proc = subprocess.Popen(gc("supervisor", "run"), env=env, cwd=city_dir(cwd), stdin=subprocess.DEVNULL,
                                stdout=log, stderr=log, start_new_session=True)
    supervisor_pid_file(cwd).write_text(str(proc.pid))
    return proc


def link_tools(home: Path, tool: Path) -> None:
    for sub in HOOK_BIN_DIRS:
        link = home / sub / tool.name
        link.parent.mkdir(parents=True, exist_ok=True)
        if not link.is_symlink():
            link.symlink_to(tool)


class GcNudge(BridgeAdapter):
    name = "gc-nudge"
    shared_state = "gc"
    agents: frozenset[AgentName] = frozenset({"claude", "codex", "droid"})
    claims_cross_machine = CROSS_MACHINE
    startup_marker = STARTUP_MARKER
    bridge_daemon = True
    scenario_na = {"S3": GC_PRIME_NA, "S6": LIFECYCLE_NA}

    def bridge_versions(self) -> dict[str, str]:
        return {"gc": gc_version()}

    def launch_mods(self, agent: AgentName, work_dir: Path, home_dir: Path) -> LaunchMods:
        return LaunchMods(host="tmux")

    def daemon_pids(self, work_dir: Path) -> list[int]:
        try:
            text = supervisor_pid_file(work_dir).read_text().strip()
        except OSError:
            return []
        return [int(text)] if text.isdigit() else []

    def agent_command(self, argv: list[str], env: dict[str, str], cwd: Path, secret_file: Path | None) -> list[str]:
        inner = pinned_inner(argv, agent_pins(cwd, env.get("PATH", "")))
        return private_env_argv(inner, env, secret_file) if split_secret_env(env)[1] else env_wrapped(inner, env)

    def write_tools(self, cwd: Path) -> None:
        tool = tools_dir(cwd) / "gc"
        write_exec(tool, gc_tool(cwd))
        link_tools(agent_home(cwd), tool)

    def start_session(self, name: str, argv: list[str], env: dict[str, str], cwd: Path,
                      secret_file: Path | None = None, state_dir: Path | None = None) -> str:
        env_ = gc_env(cwd)
        require_run_env(env_, run_dir(cwd))
        require_run_env(agent_pins(cwd, ""), run_dir(cwd))
        self.write_tools(cwd)
        command = shim_dir(cwd) / f"ac-{cwd.name}"
        write_exec(command, f"#!/bin/sh\nexec {shlex.join(self.agent_command(argv, env, cwd, secret_file))}\n")
        write_exec(shim_dir(cwd) / "tmux", tmux_shim(cwd, tmux_bin(), REPO_ROOT / "tmux.conf"))
        home, city = gc_home(cwd), city_dir(cwd)
        home.mkdir(parents=True, exist_ok=True)
        toml = gc_root(cwd) / "city.toml"
        toml.write_text(city_toml(cwd, command, Path(argv[1]).name if len(argv) > 1 else cwd.name))
        write_exec(send_script(cwd), send_wrapper(cwd))
        init = run_cli(gc("init", "--file", str(toml), "--no-start", "--skip-provider-readiness", "--yes", str(city)),
                       env_, cwd=gc_root(cwd), timeout_s=120)
        if init.code != 0:
            raise RuntimeError(f"gc init failed (exit {init.code}): {(init.stderr or init.stdout)[-300:]}")
        (home / "cities.toml").write_text(registry_toml(cwd))
        (home / "supervisor.toml").write_text(supervisor_toml(free_port()))
        return self.await_session(cwd, start_supervisor(cwd, env_))

    def await_session(self, cwd: Path, proc: subprocess.Popen) -> str:
        city = city_dir(cwd)
        deadline = time.monotonic() + SESSION_WAIT_S
        while time.monotonic() < deadline:
            listing = run_cli(gc("--city", str(city), "session", "list", "--json"), gc_env(cwd), cwd=city,
                              timeout_s=30)
            found = session_name(listing.stdout, agent_name(cwd))
            ref = f"{city_socket(cwd)}:{found}" if found else None
            if ref and self.host.alive(ref):
                return ref
            if proc.poll() is not None:
                raise RuntimeError(f"gc supervisor exited with {proc.returncode}; see gc-supervisor.log")
            time.sleep(3.0)
        raise RuntimeError(f"gc started no {agent_name(cwd)} session within {SESSION_WAIT_S:.0f}s")

    def restart_backend(self, target: Target) -> str | None:
        cwd = target.work_dir
        env_ = gc_env(cwd)
        require_run_env(env_, run_dir(cwd))
        old = require_owned_daemon(run_dir(cwd), next(iter(self.daemon_pids(cwd)), None), "gc supervisor")
        t0 = time.time()
        stop_pid(old, group=True)
        t1 = time.time()
        proc = start_supervisor(cwd, env_)
        try:
            ref = self.await_session(cwd, proc)
        except RuntimeError as e:
            raise backends.BackendError(str(e)) from e
        t2 = time.time()
        same = "same" if ref == target.host_ref else f"new {ref.split(':', 1)[-1]}"
        return (f"gc supervisor stop+start, pid {old} -> {proc.pid}; stop {t1 - t0:.1f}s + session up "
                f"{t2 - t1:.1f}s; session {same}")

    def send(self, target: Target, text: str) -> SendReceipt:
        script = send_script(target.work_dir)
        if not script.exists():
            return receipt(now(), False, "gc: no send wrapper for the target")
        return self.cli_send([str(script)], {"PATH": BASE_PATH}, text, "gc session nudge",
                             cwd=run_dir(target.work_dir))

    def unwrap(self, recorded: str) -> str:
        return unwrap_reminder(unwrap_paste_reference(recorded))

    def sender_argv(self, target: Target) -> list[str] | None:
        script = send_script(target.work_dir)
        return [str(script)] if script.exists() else None

    def agent_route(self, target: Target, sender_agent: AgentName) -> AgentRoute | None:
        argv = self.sender_argv(target)
        return AgentRoute("address", str(argv[0]), (agent_name(target.work_dir),), command=argv) if argv else None
