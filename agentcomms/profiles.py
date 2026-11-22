import json
import re
import secrets
import shlex
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, replace
from functools import cache
from pathlib import Path

from agentcomms import isolation, sandbox
from agentcomms.isolation import Mode
from agentcomms.model import AgentName, Backend
from agentcomms.paths import REPO_ROOT

USER_HOME = Path.home()
SOPS_EXEC = USER_HOME / "ac" / "bin" / "sops-exec"
PI_PACKAGE = Path("node_modules") / "@earendil-works" / "pi-coding-agent"
PINNED_AGENTS = REPO_ROOT / "vendor" / "agents"

MODELS: dict[str, tuple[str, str]] = {
    "claude": ("haiku", ""),
    "codex": ("gpt-6-luna", "low"),
    "pi": ("openrouter/deepseek/deepseek-v4.1-flash", "off"),
    "opencode": ("opencode-go/gpt-6-luna", ""),
    "droid": ("gpt-6-luna", "low"),
}
ID_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


class ProfileError(Exception):
    pass


@dataclass(frozen=True)
class Binary:
    agent: AgentName
    path: Path
    version: str
    process: str | None = None
    runtime: Path | None = None
    runtime_version: str | None = None


def parse_version(output: str) -> str:
    m = re.search(r"(\d+\.\d+\.\d+\S*)", output)
    if not m:
        raise ProfileError(f"cannot parse version from {output!r}")
    return m.group(1)


def parse_daemon_version(output: str) -> str | None:
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return None
    return data.get("appServerVersion") if isinstance(data, dict) else None


def resolve_claude(link: Path, versions: Path, scratch: Path) -> Binary:
    target = link.resolve()
    if target.parent != versions.resolve() or not target.is_file():
        raise ProfileError(f"{link} does not point into {versions}")
    return Binary("claude", target, scratch_version("claude", [str(target), "--version"], scratch))


def resolve_codex(link: Path, releases: Path) -> Binary:
    target = link.resolve()
    if target.parent.name != "bin" or target.parent.parent.parent != releases.resolve():
        raise ProfileError(f"{link} does not resolve into a release dir under {releases}")
    out = subprocess.run([str(target), "--version"], capture_output=True, text=True, timeout=30)
    version = parse_version(out.stdout)
    if not target.parent.parent.name.startswith(f"{version}-"):
        raise ProfileError(f"{target.parent.parent.name} reports codex {version}")
    return Binary("codex", target, version)


AGENTS: tuple[AgentName, ...] = ("claude", "codex", "pi", "opencode", "droid")


def nono_wrapper(user_home: Path = USER_HOME) -> list[str] | None:
    nono = sandbox.nono_binary()
    if nono is None or not all(sandbox.profile_path(a, user_home).is_file() for a in AGENTS):
        return None
    return [nono, "run"]


def parse_sw_vers(output: str) -> str:
    fields = dict(line.split(":", 1) for line in output.splitlines() if ":" in line)
    try:
        return f"{fields['ProductVersion'].strip()} ({fields['BuildVersion'].strip()})"
    except KeyError as e:
        raise ProfileError(f"cannot parse sw_vers output {output!r}") from e


@cache
def os_label() -> str:
    out = subprocess.run(["/usr/bin/sw_vers"], capture_output=True, text=True, timeout=15)
    return parse_sw_vers(out.stdout)


def resolve_node(search_path: str) -> tuple[Path, str]:
    found = shutil.which("node", path=search_path)
    node = Path(found).resolve() if found else None
    if node is None or node.name != "node":
        raise ProfileError(f"no concrete node binary on PATH (found {found})")
    out = subprocess.run([str(node), "--version"], capture_output=True, text=True, timeout=30,
                         env={"PATH": "/usr/bin:/bin"})
    return node, parse_version(out.stdout)


def resolve_pi_dir(concrete: Path, expected: str, node: tuple[Path, str], scratch: Path) -> Binary:
    package = concrete / PI_PACKAGE
    meta = json.loads((package / "package.json").read_text())
    if expected != meta["version"]:
        raise ProfileError(f"{concrete} holds pi-coding-agent {meta['version']}")
    runtime, runtime_version = node
    cli = (package / meta["bin"]["pi"]).resolve()
    probe = Binary("pi", cli, meta["version"], "pi", runtime, runtime_version)
    reported = scratch_version("pi", [str(runtime), str(cli), "--version"], scratch,
                               {"NODE_PATH": pi_node_path(probe)})
    return replace(probe, version=reported)


def pi_node_path(binary: Binary) -> str:
    modules = next(p for p in reversed(binary.path.parents) if p.name == "node_modules")
    return f"{modules}:{modules / '.mise' / 'node_modules'}"


def probe_env(agent: AgentName, tmp: Path) -> dict[str, str]:
    return {"PATH": "/usr/bin:/bin", "HOME": str(tmp)} | isolation.PROBE_ENV[agent](tmp)


def scratch_version(agent: AgentName, argv: list[str], scratch: Path, extra_env: dict[str, str] | None = None) -> str:
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".version-", dir=scratch) as tmp:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=60,
                             env=probe_env(agent, Path(tmp)) | (extra_env or {}))
    return parse_version(out.stdout + out.stderr)


def resolve_opencode(scratch: Path, path: Path) -> Binary:
    target = path.resolve()
    return Binary("opencode", target, scratch_version("opencode", [str(target), "--version"], scratch))


def resolve_droid(scratch: Path, path: Path) -> Binary:
    target = path.resolve()
    return Binary("droid", target, scratch_version("droid", [str(target), "--version"], scratch))


def opencode_session_id(now_ms: int, rand: bytes) -> str:
    value = ~(now_ms * 0x1000 + 1) & 0xFFFFFFFFFFFF
    return "ses_" + f"{value:012x}" + "".join(ID_CHARS[b % 62] for b in rand[:14])


def new_session_id(agent: AgentName, now_ms: int) -> str | None:
    match agent:
        case "claude" | "pi":
            return str(uuid.uuid4())
        case "opencode":
            return opencode_session_id(now_ms, secrets.token_bytes(14))
    return None


def codex_daemon_version(binary: Binary, env: dict[str, str] | None = None) -> str | None:
    try:
        out = subprocess.run([str(binary.path), "app-server", "daemon", "version"],
                             capture_output=True, text=True, timeout=15, env=env)
    except subprocess.TimeoutExpired:
        return None
    return parse_daemon_version(out.stdout.strip())


def pinned_dir(agent: AgentName, root: Path) -> tuple[Path, str]:
    found = sorted(root.glob(f"{agent}-*"))
    if len(found) != 1:
        raise ProfileError(f"expected one pinned {agent} dir under {root}, found {[p.name for p in found]}")
    return found[0], found[0].name.removeprefix(f"{agent}-")


def codex_release_bin(pinned: Path) -> Path:
    releases = [p for p in pinned.iterdir() if (p / "bin" / "codex").is_file()]
    if len(releases) != 1:
        raise ProfileError(f"expected one codex release dir in {pinned}, found {[p.name for p in releases]}")
    return releases[0] / "bin" / "codex"


def pinned_path(agent: AgentName, root: Path | None = None) -> Path:
    pinned, version = pinned_dir(agent, root or PINNED_AGENTS)
    match agent:
        case "claude":
            return pinned / version
        case "codex":
            return codex_release_bin(pinned)
        case "pi":
            return pinned
        case "opencode" | "droid":
            return pinned / agent
    raise ProfileError(f"no profile for {agent} yet")


def resolve_unchecked(agent: AgentName, scratch: Path, search_path: str, root: Path) -> Binary:
    path = pinned_path(agent, root)
    match agent:
        case "claude":
            return resolve_claude(path, path.parent, scratch)
        case "codex":
            return resolve_codex(path, path.parent.parent.parent)
        case "pi":
            return resolve_pi_dir(path, pinned_dir("pi", root)[1], resolve_node(search_path), scratch)
        case "opencode":
            return resolve_opencode(scratch, path)
        case "droid":
            return resolve_droid(scratch, path)
    raise ProfileError(f"no profile for {agent} yet")


def resolve(agent: AgentName, scratch: Path, search_path: str, root: Path | None = None) -> Binary:
    root = root or PINNED_AGENTS
    binary = resolve_unchecked(agent, scratch, search_path, root)
    _, pinned = pinned_dir(agent, root)
    if binary.version != pinned:
        raise ProfileError(f"pinned {agent} dir says {pinned} but the binary reports {binary.version}")
    return binary


def versions_for(binary: Binary, daemon_version: str | None, os_version: str | None = None) -> dict[str, str]:
    versions = {binary.agent: binary.version}
    if os_version:
        versions["os"] = os_version
    if binary.runtime and binary.runtime_version:
        versions[binary.runtime.name] = binary.runtime_version
    if daemon_version:
        versions[f"{binary.agent}_daemon"] = daemon_version
    return versions


def claude_mode_args(mode: Mode) -> list[str]:
    return ["--permission-mode", "bypassPermissions" if mode == "auto" else "default"]


def codex_mode_args(mode: Mode) -> list[str]:
    if mode == "auto":
        return ["--dangerously-bypass-approvals-and-sandbox"]
    return ["-a", "on-request", "-s", "read-only"]


def pi_session_dir(home: Path) -> Path:
    return home / "sessions"


def pi_args(binary: Binary, home: Path) -> list[str]:
    model, thinking = MODELS["pi"]
    if binary.runtime is None:
        raise ProfileError("pi needs its resolved node runtime")
    return ["/usr/bin/env", f"HOME={home}", f"NODE_PATH={pi_node_path(binary)}", str(binary.runtime), str(binary.path),
            "--session-dir", str(pi_session_dir(home)), "--model", model, "--thinking", thinking]


def command_prefix(binary: Binary, home: Path | None = None) -> list[str]:
    return pi_args(binary, require_home(home))[:5] if binary.agent == "pi" else [str(binary.path)]


def shim_script(prefix: list[str]) -> str:
    return f'#!/bin/sh\nexec {shlex.join(prefix)} "$@"\n'


def opencode_mode_args(mode: Mode) -> list[str]:
    return ["--auto"] if mode == "auto" else []


def opencode_server_args(backend: Backend) -> list[str]:
    return ["--standalone"] if backend == "none" else []


def droid_mode_args(mode: Mode) -> list[str]:
    return ["--auto", "high"] if mode == "auto" else []


def tui_argv(binary: Binary, mode: Mode, work_dir: Path, session_id: str | None,
             backend: Backend = "none", extra: tuple[str, ...] = (), home: Path | None = None) -> list[str]:
    model, _ = MODELS[binary.agent]
    match binary.agent:
        case "claude":
            sid = ["--session-id", session_id] if session_id else []
            return [str(binary.path), *sid, "--model", model, *claude_mode_args(mode), *extra]
        case "codex" if backend != "none":
            return [str(binary.path), "-C", str(work_dir), *extra]
        case "codex":
            return [str(binary.path), "--no-daemon", "-C", str(work_dir), "-m", model, *codex_mode_args(mode), *extra]
        case "pi":
            sid = ["--session-id", session_id] if session_id else []
            return [*pi_args(binary, require_home(home)), *sid, *extra]
        case "opencode":
            sid = ["--session", session_id] if session_id else []
            return [str(binary.path), *opencode_server_args(backend), *opencode_mode_args(mode), *sid, *extra,
                    str(work_dir)]
        case "droid":
            return [str(binary.path), "--cwd", str(work_dir), *droid_mode_args(mode), *extra]
    raise ProfileError(f"no profile for {binary.agent} yet")


def require_home(home: Path | None) -> Path:
    if home is None:
        raise ProfileError("pi needs its isolated home for --session-dir")
    return home


def resume_argv(binary: Binary, mode: Mode, work_dir: Path, session_id: str,
                backend: Backend = "none", extra: tuple[str, ...] = (), home: Path | None = None) -> list[str]:
    model, _ = MODELS[binary.agent]
    match binary.agent:
        case "claude":
            return [str(binary.path), "--resume", session_id, "--model", model, *claude_mode_args(mode), *extra]
        case "codex" if backend != "none":
            return [str(binary.path), "resume", session_id, "-C", str(work_dir), *extra]
        case "codex":
            return [str(binary.path), "resume", session_id, "--no-daemon", "-C", str(work_dir), "-m", model,
                    *codex_mode_args(mode), *extra]
        case "pi":
            return [*pi_args(binary, require_home(home)), "--session", session_id, *extra]
        case "opencode":
            return [str(binary.path), *opencode_server_args(backend), *opencode_mode_args(mode), "--session",
                    session_id, *extra, str(work_dir)]
        case "droid":
            return [str(binary.path), "--resume", session_id, "--cwd", str(work_dir), *droid_mode_args(mode), *extra]
    raise ProfileError(f"no profile for {binary.agent} yet")


def launch_argv(argv: list[str], sops_exec: Path = SOPS_EXEC) -> list[str]:
    return [str(sops_exec), *argv]
