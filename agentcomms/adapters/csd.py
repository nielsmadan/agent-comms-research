import json
import shlex
import shutil
from functools import cache
from pathlib import Path

from agentcomms.adapters.bridge import BASE_PATH, LIFECYCLE_NA, AgentRoute, BridgeAdapter, run_cli, run_dir
from agentcomms.adapters.intercom import node
from agentcomms.adapters.native import now, receipt
from agentcomms.adapters.pi_ext import VENDOR, vendored
from agentcomms.adapters.tmux import unwrap_paste_reference
from agentcomms.hosts.tmux import env_wrapped, private_env_argv, split_secret_env
from agentcomms.model import AgentName, LaunchMods, SendReceipt, Target
from agentcomms.paths import REPO_ROOT, TMUX_SOCKET

CSD_ROOT = VENDOR / "claude-session-driver"
CSD = CSD_ROOT / "dist" / "csd.cjs"
LAUNCH_TIMEOUT_S = 150.0


def worker_dir(work_dir: Path) -> Path:
    return run_dir(work_dir) / "csd"


def csd_home(work_dir: Path) -> Path:
    return run_dir(work_dir) / f"csd-home-{work_dir.name}"


def shim_dir(work_dir: Path) -> Path:
    return run_dir(work_dir) / "bin" / f"csd-{work_dir.name}"


def send_script(work_dir: Path) -> Path:
    return worker_dir(work_dir) / f"send-{work_dir.name}"


def without_flag(argv: list[str], flag: str) -> list[str]:
    out, skip = [], False
    for arg in argv:
        if skip:
            skip = False
        elif arg == flag:
            skip = True
        else:
            out.append(arg)
    return out


def tmux_shim(conf: Path) -> str:
    tmux = shutil.which("tmux") or "/opt/homebrew/bin/tmux"
    return f'#!/bin/sh\nexec {shlex.join([tmux, "-L", TMUX_SOCKET, "-f", str(conf)])} "$@"\n'


def agent_shim(command: list[str]) -> str:
    return f'#!/bin/sh\nexec {shlex.join(command)} "$@"\n'


def csd_env(work_dir: Path) -> dict[str, str]:
    return {"PATH": f"{shim_dir(work_dir)}:{BASE_PATH}", "HOME": str(csd_home(work_dir)), "LANG": "en_US.UTF-8",
            "CSD_WORKER_DIR": str(worker_dir(work_dir)), "CSD_CLAUDE_BIN": str(shim_dir(work_dir) / "claude")}


def send_wrapper(work_dir: Path, name: str, node_bin: str) -> str:
    env = [f"{k}={v}" for k, v in sorted(csd_env(work_dir).items())]
    command = shlex.join(["/usr/bin/env", "-i", *env, node_bin, str(CSD), "--worker", name, "send"])
    return f'#!/bin/sh\nexec {command} "$(cat)"\n'


def write_exec(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o700)


@cache
def csd_version() -> str:
    try:
        return json.loads((CSD_ROOT / "package.json").read_text())["version"]
    except (OSError, KeyError, json.JSONDecodeError):
        return "unknown"


class Csd(BridgeAdapter):
    name = "csd"
    shared_state = "csd"
    agents: frozenset[AgentName] = frozenset({"claude"})
    scenario_na = {"S3": "csd launches Claude with --dangerously-skip-permissions, so no permission dialog shows",
                   "S6": LIFECYCLE_NA, "S12": "no backing daemon: csd drives tmux and reads hook event files"}

    def unwrap(self, recorded: str) -> str:
        return unwrap_paste_reference(recorded)

    def bridge_versions(self) -> dict[str, str]:
        return {"claude-session-driver": csd_version()}

    def launch_mods(self, agent: AgentName, work_dir: Path, home_dir: Path) -> LaunchMods:
        return LaunchMods(host="tmux", env={"CSD_WORKER_DIR": str(worker_dir(work_dir))})

    def prepare_launch(self, agent: AgentName, work_dir: Path, home_dir: Path) -> None:
        home = csd_home(work_dir)
        home.mkdir(parents=True, exist_ok=True)
        link = home / ".claude"
        if not link.is_symlink():
            link.symlink_to(home_dir)
        worker_dir(work_dir).mkdir(parents=True, exist_ok=True)

    def start_session(self, name: str, argv: list[str], env: dict[str, str], cwd: Path,
                      secret_file: Path | None = None, state_dir: Path | None = None) -> str:
        inner = without_flag(argv, "--session-id")
        wrapped = private_env_argv(inner, env, secret_file) if split_secret_env(env)[1] else env_wrapped(inner, env)
        node_bin = node()
        write_exec(shim_dir(cwd) / "claude", agent_shim(wrapped))
        write_exec(shim_dir(cwd) / "tmux", tmux_shim(REPO_ROOT / "tmux.conf"))
        write_exec(send_script(cwd), send_wrapper(cwd, name, node_bin))
        csd = [node_bin, str(vendored(CSD))]
        consent = run_cli([*csd, "grant-consent"], csd_env(cwd), stdin="yes\n", timeout_s=30)
        if consent.code != 0:
            raise RuntimeError(f"csd grant-consent failed: {consent.stderr.strip()[:200]}")
        launched = run_cli([*csd, "launch", name, str(cwd)], csd_env(cwd), cwd=cwd, timeout_s=LAUNCH_TIMEOUT_S)
        if launched.code != 0:
            raise RuntimeError(f"csd launch failed (exit {launched.code}): {launched.stderr.strip()[-300:]}")
        return f"{TMUX_SOCKET}:{name}"

    def send(self, target: Target, text: str) -> SendReceipt:
        script = send_script(target.work_dir)
        if not script.exists():
            return receipt(now(), False, "csd: no send wrapper for the target")
        return self.cli_send([str(script)], {"PATH": BASE_PATH}, text, "csd send",
                             cwd=run_dir(target.work_dir))

    def sender_argv(self, target: Target) -> list[str] | None:
        script = send_script(target.work_dir)
        return [str(script)] if script.exists() else None

    def agent_route(self, target: Target, sender_agent: AgentName) -> AgentRoute | None:
        argv = self.sender_argv(target)
        name = target.host_ref.split(":", 1)[-1]
        return AgentRoute("address", str(argv[0]), (name,), command=argv) if argv else None
