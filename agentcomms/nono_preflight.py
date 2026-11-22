import json
import socket
import subprocess
import tempfile
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

from agentcomms import isolation, profiles, sandbox
from agentcomms.adapters.intercom import TSX
from agentcomms.adapters.native import SENDERS
from agentcomms.model import AgentName
from agentcomms.paths import REPO_ROOT, SOCKET_DIR, TMUX_SOCKET

TMUX_CONF = REPO_ROOT / "tmux.conf"

SENDER_SCRIPTS = ("claude_uds.py", "claude_link.py", "codex_queue.py", "codex_remote.py", "opencode_http.py",
                  "pi_bridge.py", "unix_send.py")
PS_PROBE = ("import subprocess, sys; "
            "out = subprocess.run(['ps', '-A', '-o', 'pid=,lstart=,ucomm='], capture_output=True, text=True); "
            "print(out.returncode, len(out.stdout.splitlines())); sys.exit(out.returncode)")
BIND_PROBE = ("import socket, sys; s = socket.socket(socket.AF_UNIX); s.bind(sys.argv[1]); s.listen(1); "
              "print('bound')")
CONNECT_PROBE = ("import socket, sys; s = socket.socket(socket.AF_UNIX); s.settimeout(3); s.connect(sys.argv[1]); "
                 "print('connected')")
TCP_PROBE = ("import socket, sys; s = socket.socket(); s.bind(('127.0.0.1', 0)); s.listen(1); "
             "c = socket.create_connection(('127.0.0.1', int(sys.argv[1])), timeout=3); print('tcp ok')")


@dataclass(frozen=True)
class Check:
    agent: str
    check: str
    ok: bool
    detail: str


def verdict(agent: AgentName, check: str, proc: subprocess.CompletedProcess, expect: str | None = None) -> Check:
    out = sandbox.strip_nono_output(proc.stdout)
    ok = proc.returncode == 0 and (expect is None or expect in out)
    detail = sandbox.sender_detail(proc.stdout, proc.stderr, 240) or f"exit {proc.returncode}"
    return Check(agent, check, ok, f"exit {proc.returncode}: {detail}")


def checks_for(agent: AgentName, binary: profiles.Binary, python3: str, node: str, run_dir: Path,
               connect_sock: Path, tcp_port: int) -> list[tuple[str, list[str], dict[str, str], str | None]]:
    scratch = Path(tempfile.mkdtemp(prefix=".version-", dir=run_dir))
    probe = isolation.PROBE_ENV.get(agent, lambda _tmp: {})(scratch)
    version_cmd = (["/usr/bin/env", f"HOME={scratch}", *(f"{k}={v}" for k, v in probe.items()),
                    *([f"NODE_PATH={profiles.pi_node_path(binary)}", str(binary.runtime)] if agent == "pi" else []),
                    str(binary.path), "--version"])
    bind_sock = SOCKET_DIR / f"{run_dir.name}-{agent}-bind.sock"
    return [
        (f"nono why --self --path {run_dir} --op readwrite",
         ["/usr/bin/env", "NONO_NO_UPDATE_CHECK=1", sandbox.nono_binary() or "nono", "why", "--self", "--path",
          str(run_dir), "--op", "readwrite"], {}, "ALLOWED"),
        ("ps (sender guard: ps -A -o pid,lstart,ucomm)", [python3, "-I", "-c", PS_PROBE], {}, None),
        (f"pinned {agent} {binary.version} --version from vendor/agents", version_cmd, {}, binary.version),
        *((f"sender {name} --help", [python3, "-I", str(SENDERS / name), "--help"], {}, "usage")
          for name in SENDER_SCRIPTS),
        (f"bind unix socket {bind_sock}", [python3, "-I", "-c", BIND_PROBE, str(bind_sock)], {}, "bound"),
        (f"connect unix socket {connect_sock}", [python3, "-I", "-c", CONNECT_PROBE, str(connect_sock)], {},
         "connected"),
        ("tcp listen + connect 127.0.0.1", [python3, "-I", "-c", TCP_PROBE, str(tcp_port)], {}, "tcp ok"),
        (f"tmux -L {TMUX_SOCKET} list-sessions", ["tmux", "-L", TMUX_SOCKET, "list-sessions"], {}, None),
        ("node + vendored tsx (intercom sender runtime)", [node, str(TSX), "-e", "console.log('tsx ok')"], {},
         "tsx ok"),
    ]


def listener(path: Path) -> socket.socket:
    path.unlink(missing_ok=True)
    s = socket.socket(socket.AF_UNIX)
    s.bind(str(path))
    s.listen(8)
    threading.Thread(target=accept_all, args=(s,), daemon=True).start()
    return s


def tcp_listener() -> socket.socket:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(8)
    threading.Thread(target=accept_all, args=(s,), daemon=True).start()
    return s


def accept_all(s: socket.socket) -> None:
    while True:
        try:
            conn, _ = s.accept()
        except OSError:
            return
        conn.close()


def run(run_dir: Path, agents: list[AgentName], user_home: Path, environ: dict[str, str]) -> list[Check]:
    nono = sandbox.nono_binary()
    if nono is None:
        return [Check(a, "nono on PATH", False, "nono not found") for a in agents]
    SOCKET_DIR.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)
    base = isolation.base_env(environ)
    python3 = sandbox_python()
    node, _ = profiles.resolve_node(base.get("PATH", ""))
    connect_sock = SOCKET_DIR / f"{run_dir.name}-listen.sock"
    unix, tcp = listener(connect_sock), tcp_listener()
    session = f"{run_dir.name}-tmux"
    subprocess.run(["tmux", "-L", TMUX_SOCKET, "-f", str(TMUX_CONF), "new-session", "-d", "-s", session, "sleep",
                    "600"], capture_output=True, timeout=30)
    results: list[Check] = []
    try:
        for agent in agents:
            binary = profiles.resolve(agent, run_dir, base.get("PATH", ""))
            for name, argv, extra, expect in checks_for(agent, binary, python3, str(node), run_dir, connect_sock,
                                                        tcp.getsockname()[1]):
                cmd = sandbox.wrap_command(agent, argv, base | extra, nono, user_home, silent=False)
                try:
                    proc = subprocess.run(cmd.argv, env=cmd.env, capture_output=True, text=True, timeout=60,
                                          cwd=run_dir, stdin=subprocess.DEVNULL)
                except subprocess.TimeoutExpired:
                    results.append(Check(agent, name, False, "timeout after 60s"))
                    continue
                results.append(verdict(agent, name, proc, expect))
            (SOCKET_DIR / f"{run_dir.name}-{agent}-bind.sock").unlink(missing_ok=True)
    finally:
        subprocess.run(["tmux", "-L", TMUX_SOCKET, "kill-session", "-t", f"={session}"], capture_output=True,
                       timeout=30)
        unix.close()
        tcp.close()
        connect_sock.unlink(missing_ok=True)
    (run_dir / "nono-preflight.json").write_text(json.dumps([asdict(c) for c in results], indent=1) + "\n")
    return results


def sandbox_python() -> str:
    return "python3"


AGENT_ORDER = ("claude", "codex", "pi", "opencode", "droid")


def row_agent(line: str) -> str:
    return line.split("|")[1].strip()


def kept_rows(previous: str, agents: set[str]) -> list[str]:
    return [line for line in previous.splitlines() if line.startswith("| ") and row_agent(line) in AGENT_ORDER
            and row_agent(line) not in agents]


def render(results: list[Check], nono_version: str, when: str, previous: str = "") -> str:
    rows = kept_rows(previous, {c.agent for c in results}) + [
        f"| {c.agent} | {c.check} | {'yes' if c.ok else 'NO'} | {c.detail.replace('|', '/')} |" for c in results]
    lines = ["# nono preflight", "", f"Updated: {when} · nono {nono_version} · profiles `<agent>-local` from "
             "`~/.config/nono/profiles` (read only, not edited) · launcher env from `~/ac/.airc.d/05-sandbox.zsh` "
             "(`agentcomms/sandbox.py`)", "",
             "Each check runs inside `nono run -p <agent>-local -- …` from an unsandboxed coordinator (R19/N7).", "",
             "| agent | check | ok | detail |", "|---|---|---|---|"]
    lines += sorted(rows, key=lambda line: AGENT_ORDER.index(row_agent(line)))
    return "\n".join(lines) + "\n"
