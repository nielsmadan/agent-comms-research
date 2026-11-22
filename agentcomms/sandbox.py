import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from agentcomms.hosts.tmux import TmuxError, TmuxHost
from agentcomms.model import AgentName, SendReceipt, Target

SILENT_AGENTS = frozenset({"claude", "opencode"})
NONO_CONFLICTS = ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR")
NONO_ONLY = {"NONO_NO_UPDATE_CHECK": "1"}
SENDER_WAIT_S = 5.0
NONO_LINE = re.compile(r"^\s*(nono v|\[nono\]|Capabilities:|Applying sandbox|Verified \d+ pack|─{5,}|"
                       r"\+ \d+ system|(r\+w|r|w|deny|sock\+?|net|ipc|warn)\s{2})")


def profile_name(agent: AgentName) -> str:
    return f"{agent}-local"


def nono_binary() -> str | None:
    found = shutil.which("nono")
    return str(Path(found).resolve()) if found else None


@cache
def nono_version(nono: str) -> str:
    out = subprocess.run([nono, "--version"], capture_output=True, text=True, timeout=15)
    m = re.search(r"(\d+\.\d+\.\d+\S*)", out.stdout)
    return m.group(1) if m else "unknown"


def profile_path(agent: AgentName, user_home: Path) -> Path:
    return user_home / ".config" / "nono" / "profiles" / f"{profile_name(agent)}.json"


def launcher_env(agent: AgentName, user_home: Path, path: str) -> dict[str, str]:
    return {
        "PATH": f"{user_home}/ac/bin/sandbox-shims:{user_home}/ac/bin:{path}",
        "AGENT_HARNESS": agent,
        "AGENT_SANDBOX": "1",
        "AGENT_SANDBOX_PROFILE": profile_name(agent),
        "DOCKER_HOST": f"unix://{user_home}/.colima/default/docker.sock",
        "OTHER_SWIFT_FLAGS": "$(inherited) -disable-sandbox",
        "AGENT_BROWSER_ARGS": "--no-sandbox",
        "VHS_NO_SANDBOX": "true",
        "DISABLE_AUTOUPDATER": "1",
        "SSL_CERT_FILE": "/etc/ssl/cert.pem",
    }


def nono_run(nono: str, agent: AgentName, silent: bool | None = None) -> list[str]:
    quiet = agent in SILENT_AGENTS if silent is None else silent
    return [nono, "run", *(["--silent"] if quiet else []), "--no-audit", "-p", profile_name(agent), "--"]


def restore_env(env: dict[str, str]) -> list[str]:
    unset = [*NONO_ONLY, *(k for k in NONO_CONFLICTS if k not in env)]
    return ["/usr/bin/env", *(a for k in unset for a in ("-u", k)), *(f"{k}={env[k]}" for k in NONO_CONFLICTS
                                                                      if k in env)]


def outer_env(agent: AgentName, env: dict[str, str], user_home: Path) -> dict[str, str]:
    kept = {k: v for k, v in env.items() if k not in NONO_CONFLICTS}
    return kept | launcher_env(agent, user_home, env.get("PATH", "")) | NONO_ONLY


@dataclass(frozen=True)
class Wrapped:
    argv: list[str]
    env: dict[str, str]


def wrap_command(agent: AgentName, argv: list[str], env: dict[str, str], nono: str, user_home: Path,
                 silent: bool | None = None) -> Wrapped:
    return Wrapped([*nono_run(nono, agent, silent), *restore_env(env), *argv], outer_env(agent, env, user_home))


def wrap_launch(agent: AgentName, argv: list[str], env: dict[str, str], nono: str, user_home: Path,
                silent: bool | None = None) -> Wrapped:
    sops, *command = argv
    inner = wrap_command(agent, command, env, nono, user_home, silent)
    return Wrapped([sops, *inner.argv], inner.env)


def is_sops_exec(arg: str) -> bool:
    return Path(arg).name == "sops-exec"


def strip_nono_output(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if line.strip() and not NONO_LINE.match(line))


def sender_detail(stdout: str, stderr: str, limit: int = 200) -> str:
    text = strip_nono_output(stdout) or strip_nono_output(stderr)
    return " ".join(text.split())[-limit:]


def sender_accepted(code: int, stdout: str) -> bool:
    out = strip_nono_output(stdout).strip()
    return code == 0 and not out.startswith(("refused", "error"))


class SandboxedTmuxHost(TmuxHost):
    def __init__(self, base: TmuxHost, prefix: list[str], env: dict[str, str]):
        super().__init__(base.conf, base.socket, base.width, base.height)
        self.prefix = prefix
        self.env = env

    def run(self, *args: str, check: bool = True, input_text: str | None = None, socket: str | None = None) -> str:
        proc = subprocess.run([*self.prefix, *self.base(socket), *args], capture_output=True, text=True,
                              input=input_text, env=self.env, timeout=60)
        if check and proc.returncode != 0:
            raise TmuxError(f"tmux {args[0]} inside nono failed: {sender_detail(proc.stdout, proc.stderr)}")
        return proc.stdout


class SandboxedSender:
    def __init__(self, adapter, agent: AgentName, nono: str, user_home: Path, environ: dict[str, str]):
        self.adapter = adapter
        self.agent = agent
        self.nono = nono
        self.user_home = user_home
        self.environ = environ
        self.terminal = getattr(adapter, "kind", None) == "terminal" and isinstance(getattr(adapter, "host", None),
                                                                                  TmuxHost)

    def __getattr__(self, name: str):
        return getattr(self.adapter, name)

    def wrapped(self, argv: list[str]) -> Wrapped:
        return wrap_command(self.agent, argv, self.environ, self.nono, self.user_home)

    def send(self, target: Target, text: str) -> SendReceipt:
        if self.terminal:
            probe = self.wrapped([])
            sandboxed = type(self.adapter)(SandboxedTmuxHost(self.adapter.host, probe.argv, probe.env))
            receipt = sandboxed.send(target, text)
            return SendReceipt(receipt.accepted, receipt.sent_at, receipt.sent_mono, receipt.retries,
                               f"nono {profile_name(self.agent)}: {receipt.detail}".strip(), receipt.spawned,
                               receipt.waited_s)
        return self.run_sender(target, text)

    def run_sender(self, target: Target, text: str) -> SendReceipt:
        sent_at, sent_mono = time.time(), time.monotonic()
        argv = self.adapter.sender_argv(target) or route_command(self.adapter, target, self.agent)
        if argv is None:
            return SendReceipt(False, sent_at, sent_mono, detail=f"{self.adapter.name} has no agent-usable sender")
        cmd = self.wrapped(argv)
        proc = subprocess.Popen(cmd.argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, env=cmd.env, cwd=target.work_dir, start_new_session=True)
        try:
            out, err = proc.communicate(text, timeout=SENDER_WAIT_S)
        except subprocess.TimeoutExpired:
            return SendReceipt(True, sent_at, sent_mono, detail=f"nono {profile_name(self.agent)}: sender still "
                                                                f"running after {SENDER_WAIT_S:.0f}s",
                               spawned=(proc.pid,))
        detail = f"nono {profile_name(self.agent)}: exit {proc.returncode}: {sender_detail(out, err)}"
        return SendReceipt(sender_accepted(proc.returncode, out), sent_at, sent_mono, detail=detail)


def route_command(adapter, target: Target, agent: AgentName) -> list[str] | None:
    route = getattr(adapter, "agent_route", None)
    found = route(target, agent) if route else None
    return list(found.command) if found and found.command else None


def sandboxed_adapter(adapter, agent: AgentName, nono: str, user_home: Path,
                      environ: dict[str, str]) -> SandboxedSender:
    return SandboxedSender(adapter, agent, nono, user_home, environ)
