import json
import shlex
from functools import cache
from pathlib import Path

from agentcomms.adapters.bridge import (
    BASE_PATH,
    LIFECYCLE_NA,
    AgentRoute,
    BridgeAdapter,
    contained_path,
    forwarding_exec,
    run_cli,
    run_dir,
    tool_wrapper,
    tools_dir,
)
from agentcomms.adapters.csd import tmux_shim, write_exec
from agentcomms.adapters.native import now, receipt
from agentcomms.adapters.pi_ext import VENDOR, vendored
from agentcomms.adapters.tmux import unwrap_paste_reference
from agentcomms.hosts.tmux import env_wrapped, private_env_argv, split_secret_env
from agentcomms.model import AgentName, LaunchMods, SendReceipt, Target
from agentcomms.paths import REPO_ROOT, TMUX_SOCKET

AGENT_DECK = VENDOR / "agent-deck" / "bin" / "agent-deck"
START_TIMEOUT_S = 120.0
CONFIG = f"""[tmux]
socket_name = "{TMUX_SOCKET}"
inject_status_line = false
mouse = false

[updates]
auto_update = false
auto_update_remotes = false
auto_install = false
auto_restart = false
check_enabled = false
manage_timer = false
notify_in_cli = false
"""
CROSS_MACHINE = ("agent-deck README: `agent-deck add --ssh user@host` runs sessions on a remote host over SSH; "
                 "`agent-deck web` serves the TUI over HTTP/WebSocket (allowed_hosts for reverse proxies or Tailscale)")


def ad_home(work_dir: Path) -> Path:
    return run_dir(work_dir) / "ad-home"


def shim_dir(work_dir: Path) -> Path:
    return run_dir(work_dir) / "bin" / f"ad-{work_dir.name}"


def send_script(work_dir: Path) -> Path:
    return ad_home(work_dir) / f"send-{work_dir.name}"


TOOL_HOMES = ("CODEX_HOME", "CLAUDE_CONFIG_DIR", "FACTORY_HOME_OVERRIDE")
SESSION_ENV = ("AGENTDECK_INSTANCE_ID", "AGENTDECK_TITLE", "AGENTDECK_TOOL", "AGENTDECK_PROFILE")
NOTIFY_ENV = (*SESSION_ENV, "CODEX_SESSION_ID")


def ad_env(work_dir: Path, agent_env: dict[str, str] | None = None) -> dict[str, str]:
    home = ad_home(work_dir)
    tool_homes = {k: v for k, v in (agent_env or {}).items() if k in TOOL_HOMES}
    return tool_homes | {"PATH": f"{shim_dir(work_dir)}:{BASE_PATH}", "HOME": str(home), "LANG": "en_US.UTF-8",
            "XDG_CONFIG_HOME": str(home / ".config"), "XDG_DATA_HOME": str(home / ".local" / "share"),
            "XDG_CACHE_HOME": str(home / ".cache"), "XDG_STATE_HOME": str(home / ".local" / "state"),
            "TERM": "xterm-256color"}


def deck(*args: str) -> list[str]:
    return [str(vendored(AGENT_DECK)), *args]


def session_entry(listing: str, title: str) -> dict | None:
    try:
        data = json.loads(listing)
    except json.JSONDecodeError:
        return None
    rows = data if isinstance(data, list) else data.get("sessions", []) if isinstance(data, dict) else []
    return next((r for r in rows if isinstance(r, dict) and r.get("title") == title), None)


def send_wrapper(work_dir: Path, title: str, agent_env: dict[str, str], flags: tuple[str, ...] = ()) -> str:
    env = [f"{k}={v}" for k, v in sorted(ad_env(work_dir, agent_env).items())]
    command = ["/usr/bin/env", "-i", *env, str(AGENT_DECK), "session", "send", title, "--message-file", "-",
               "--json", *flags]
    return f"#!/bin/sh\nexec {shlex.join(command)}\n"


def deck_tool(work_dir: Path, agent_env: dict[str, str]) -> str:
    return tool_wrapper(ad_env(work_dir, agent_env), [str(AGENT_DECK)], NOTIFY_ENV)


def agent_env(work_dir: Path, env: dict[str, str]) -> dict[str, str]:
    return env | {"PATH": contained_path(env.get("PATH", ""), (str(tools_dir(work_dir)),), ("agent-deck",))}


@cache
def deck_version() -> str:
    scratch = REPO_ROOT / "runs" / ".version-agent-deck"
    env = {"PATH": BASE_PATH, "HOME": str(scratch), "XDG_CONFIG_HOME": str(scratch / ".config"),
           "XDG_DATA_HOME": str(scratch / ".local" / "share"), "XDG_CACHE_HOME": str(scratch / ".cache"),
           "XDG_STATE_HOME": str(scratch / ".local" / "state")}
    out = run_cli(deck("version"), env, timeout_s=15)
    words = out.stdout.split()
    return words[-1].lstrip("v") if out.code == 0 and words else "unknown"


class AgentDeck(BridgeAdapter):
    name = "agent-deck"
    shared_state = "agent-deck"
    agents: frozenset[AgentName] = frozenset({"claude", "codex", "droid"})
    claims_cross_machine = CROSS_MACHINE
    send_flags: tuple[str, ...] = ()
    scenario_na = {"S6": LIFECYCLE_NA, "S12": "no backing daemon: agent-deck drives the tmux sessions directly"}

    def unwrap(self, recorded: str) -> str:
        return unwrap_paste_reference(recorded)

    def bridge_versions(self) -> dict[str, str]:
        return {"agent-deck": deck_version()}

    def launch_mods(self, agent: AgentName, work_dir: Path, home_dir: Path) -> LaunchMods:
        return LaunchMods(host="tmux")

    def prepare_launch(self, agent: AgentName, work_dir: Path, home_dir: Path) -> None:
        config = Path(ad_env(work_dir)["XDG_CONFIG_HOME"]) / "agent-deck" / "config.toml"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(CONFIG)

    def start_session(self, name: str, argv: list[str], env: dict[str, str], cwd: Path,
                      secret_file: Path | None = None, state_dir: Path | None = None) -> str:
        write_exec(tools_dir(cwd) / "agent-deck", deck_tool(cwd, env))
        agent = shim_dir(cwd) / f"ac-{cwd.name}"
        write_exec(agent, self.agent_script(argv, env, cwd, secret_file))
        write_exec(shim_dir(cwd) / "tmux", tmux_shim(REPO_ROOT / "tmux.conf"))
        write_exec(send_script(cwd), send_wrapper(cwd, name, env, self.send_flags))
        env_ = ad_env(cwd, env)
        if "CODEX_HOME" in env:
            hooks = run_cli(deck("codex-hooks", "install"), env_, cwd=cwd, timeout_s=60)
            if hooks.code != 0:
                raise RuntimeError(f"agent-deck codex-hooks install failed: {(hooks.stderr or hooks.stdout)[-300:]}")
        added = run_cli(deck("add", str(cwd), "-t", name, "-c", str(agent), "--tmux-socket", TMUX_SOCKET,
                             "--no-parent", "--no-identity", "--json"), env_, cwd=cwd, timeout_s=60)
        if added.code != 0:
            raise RuntimeError(f"agent-deck add failed (exit {added.code}): {(added.stderr or added.stdout)[-300:]}")
        started = run_cli(deck("session", "start", name, "--json"), env_, cwd=cwd, timeout_s=START_TIMEOUT_S)
        if started.code != 0:
            raise RuntimeError(f"agent-deck session start failed (exit {started.code}): "
                               f"{(started.stderr or started.stdout)[-300:]}")
        listing = run_cli(deck("list", "--json"), env_, cwd=cwd, timeout_s=30)
        entry = session_entry(listing.stdout, name) or {}
        tmux_name = entry.get("tmux_session")
        if not tmux_name:
            raise RuntimeError(f"agent-deck list has no tmux session for {name}: {listing.stdout[-300:]}")
        return f"{TMUX_SOCKET}:{tmux_name}"

    def agent_script(self, argv: list[str], env: dict[str, str], cwd: Path, secret_file: Path | None) -> str:
        pinned = agent_env(cwd, env)
        wrapped = (private_env_argv(argv, pinned, secret_file) if split_secret_env(pinned)[1]
                   else env_wrapped(argv, pinned))
        return forwarding_exec(wrapped, SESSION_ENV)

    def send(self, target: Target, text: str) -> SendReceipt:
        script = send_script(target.work_dir)
        if not script.exists():
            return receipt(now(), False, "agent-deck: no send wrapper for the target")
        return self.cli_send([str(script)], {"PATH": BASE_PATH}, text, "agent-deck session send",
                             cwd=run_dir(target.work_dir))

    def sender_argv(self, target: Target) -> list[str] | None:
        script = send_script(target.work_dir)
        return [str(script)] if script.exists() else None

    def agent_route(self, target: Target, sender_agent: AgentName) -> AgentRoute | None:
        argv = self.sender_argv(target)
        return AgentRoute("address", str(argv[0]), (target.work_dir.name,), command=argv) if argv else None


class AgentDeckComposerFallback(AgentDeck):
    name = "agent-deck-composer-fallback"
    agents: frozenset[AgentName] = frozenset({"codex"})
    send_flags = ("--codex-composer-fallback",)
