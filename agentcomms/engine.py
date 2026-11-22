import contextlib
import difflib
import errno
import os
import re
import secrets
import subprocess
import sys
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

from agentcomms import backends, isolation, manifest, markers, procs, profiles, userconfig
from agentcomms import sandbox as sandboxing
from agentcomms.hosts import make_host, state_dir_for
from agentcomms.hosts.errors import HolderBlocked, HostError
from agentcomms.hosts.tmux import TmuxHost, write_private
from agentcomms.model import (
    Ack,
    Adapter,
    AgentName,
    Backend,
    Delivery,
    DraftFate,
    HostKind,
    LaunchMods,
    Manifest,
    Target,
    Transcript,
)
from agentcomms.paths import SOCKET_DIR, Layout, new_run_id
from agentcomms.records import ResultRecord, tildify
from agentcomms.transcripts.claude import ClaudeTranscript, registry_entry, transcript_path
from agentcomms.transcripts.codex import CodexTranscript
from agentcomms.transcripts.codex import session_meta as codex_meta
from agentcomms.transcripts.droid import DroidTranscript
from agentcomms.transcripts.opencode import OpenCodeTranscript
from agentcomms.transcripts.pi import PiTranscript

READY_TIMEOUT_S = {"claude": 90.0, "codex": 90.0, "pi": 90.0, "opencode": 120.0, "droid": 120.0}
STARTUP_APPEAR_S = 45.0
STARTUP_SETTLE_S = 150.0
RECEIVED_KINDS = ("user", "peer", "custom", "hook")
STARTUP_KINDS = RECEIVED_KINDS
REPLY_TIMEOUT_S = {"claude": 180.0, "codex": 180.0, "pi": 180.0, "opencode": 180.0, "droid": 180.0}
S1_BODY = "This is an idle-wake test from the agentcomms harness; no other action is needed."


@dataclass(frozen=True)
class Dialog:
    label: str
    pattern: re.Pattern
    keys: tuple[str, ...]


DIALOGS: dict[str, tuple[Dialog, ...]] = {
    "claude": (
        Dialog("trust-folder", re.compile(r"trust (the files in )?this folder", re.I), ("Enter",)),
        Dialog("bypass-warning", re.compile(r"Bypass Permissions mode.*\n?.*(No, exit|Yes, I accept)", re.I | re.S),
               ("Down", "Enter")),
        Dialog("theme", re.compile(r"Choose the text style", re.I), ("Enter",)),
        Dialog("dev-channels", re.compile(r"Loading development channels.*1\. I am using this for local development",
                                          re.S), ("Enter",)),
    ),
    "codex": (
        Dialog("trust-dir", re.compile(r"(trust the contents of this directory|allow Codex to work in this folder)",
                                       re.I), ("Enter",)),
        Dialog("model-nudge", re.compile(r"(Try new model|Choose how you'd like Codex to proceed)", re.I),
               ("Escape",)),
    ),
    "droid": (
        Dialog("trust-folder", re.compile(r"Trust this folder\?.*1\. Trust this folder", re.S), ("Enter",)),
    ),
}

AUTH_PANE = {
    "claude": re.compile(r"(Select login method|Please run /login|Invalid API key|OAuth token (has )?expired)", re.I),
    "codex": re.compile(r"(Sign in with ChatGPT|Provide your own API key|Please run `?codex login)", re.I),
    "pi": re.compile(r"No API key (found|configured)|\s{2,}(?!\()[\w./-]+ • thinking \w+", re.I),
    "opencode": re.compile(r"(No providers? (are )?(configured|connected)|Connect a provider)", re.I),
    "droid": re.compile(r"(Please log ?in with your Factory account|Sign into a Factory|Sign in to Factory|"
                        r"Invalid API key)", re.I),
}

READY_PANE = {
    "claude": (re.compile(r"^❯", re.M), re.compile(r"(\? for shortcuts|bypass permissions on|permissions on|mode on)")),
    "codex": (re.compile(r"^› ", re.M), re.compile(r"(\? for shortcuts|context left)")),
    "pi": (re.compile(r"^─{20,}$", re.M), re.compile(r"\(\w+\) \S+ • thinking \w+")),
    "opencode": (re.compile(r"┃\s+Build (auto )?· "), re.compile(r"ctrl\+p commands")),
    "droid": (re.compile(r"^│ >", re.M), re.compile(r"\? for help")),
}

STARTED_PANE = {
    "codex": (re.compile(r"^\s*\S+ (?:minimal|low|medium|high|xhigh) · |Context \d+% used", re.M),),
}
STARTING_PANE = {
    "codex": re.compile(r"Waiting for startup|OpenAI Codex \(v[\d.]+\)\s+loading"),
}


def envelope(token: str, body: str) -> str:
    return f'ACK-REQUEST {token}: reply with exactly "ACK {token}". {body}'


HEX = "0123456789abcdef"
DIGIT_FREE = "abcdef"


def new_token(alphabet: str = HEX) -> str:
    return "".join(secrets.choice(alphabet) for _ in range(8))


def match_dialog(agent: AgentName, pane: str) -> Dialog | None:
    return next((d for d in DIALOGS.get(agent, ()) if d.pattern.search(pane)), None)


AUTH_HOLD_S = 5.0


def auth_since(previous: float | None, auth: str | None, now: float) -> float | None:
    if not auth:
        return None
    return now if previous is None else previous


def auth_screen(agent: AgentName, pane: str) -> str | None:
    pattern = AUTH_PANE.get(agent)
    m = pattern.search(pane) if pattern else None
    return m.group(0) if m else None


def pane_ready(agent: AgentName, pane: str) -> bool:
    prompt, footer = READY_PANE[agent]
    started = all(p.search(pane) for p in STARTED_PANE.get(agent, ()))
    starting = STARTING_PANE.get(agent)
    return (bool(prompt.search(pane) and footer.search(pane)) and started
            and not (starting and starting.search(pane)) and match_dialog(agent, pane) is None)


def classify_delivery(accepted: bool, user_hits: list[tuple[float, str, str]], held: bool = False) -> Delivery:
    if not accepted:
        return Delivery.REJECTED
    if user_hits:
        return Delivery.DELIVERED
    return Delivery.HELD if held else Delivery.LOST


def classify_ack(delivered: bool, assistant_texts: list[str], token: str) -> Ack:
    if any(f"ACK {token}" in t for t in assistant_texts):
        return Ack.ACKED
    return Ack.MODEL_NONCOMPLIANT if delivered else Ack.NONE


def receiver_hits(entries: list[tuple[float, str, str]], token: str) -> list[tuple[float, str, str]]:
    return [e for e in entries if token in e[2] and e[1] in RECEIVED_KINDS]


HELD_GRACE_S = 20.0


def all_held(entries: list[tuple[float, str, str]], tokens: list[str]) -> bool:
    held = [t for _, k, t in entries if k == "held"]
    received = receiver_hits(entries, "")
    return all(any(tok in t for t in held) and not any(tok in e[2] for e in received) for tok in tokens)


def api_errors(entries: list[tuple[float, str, str]]) -> list[str]:
    return [t for _, k, t in entries if k == "api_error"]


def recorded_body(user_hits: list[tuple[float, str, str]], adapter: Adapter) -> str | None:
    return adapter.unwrap(user_hits[0][2]) if user_hits else None


ENV_ERRNOS = frozenset({errno.EPERM, errno.EACCES, errno.ENOSPC, errno.EAGAIN, errno.ETIMEDOUT, errno.ECONNREFUSED,
                        errno.ECONNRESET, errno.ENETUNREACH, errno.EHOSTUNREACH})


class AuthRequiredError(RuntimeError):
    pass


class AgentLostError(RuntimeError):
    pass


class UnsupportedAdapterError(ValueError):
    pass


def require_supported(adapter: Adapter | None, agent: AgentName) -> None:
    if adapter is not None and agent not in adapter.agents:
        raise UnsupportedAdapterError(f"adapter {adapter.name} does not support {agent} "
                                      f"(supports {', '.join(sorted(adapter.agents))})")


def failure_delivery(error: Exception) -> Delivery:
    if isinstance(error, subprocess.SubprocessError | HostError | AuthRequiredError):
        return Delivery.ENV_ERROR
    if isinstance(error, OSError) and error.errno in ENV_ERRNOS:
        return Delivery.ENV_ERROR
    return Delivery.ERROR


def pid_or_stop(host, host_ref: str) -> int:
    try:
        return host.pane_pid(host_ref)
    except Exception:
        with contextlib.suppress(Exception):
            host.stop(host_ref)
        raise


def failure_note(error: Exception) -> str:
    if isinstance(error, HolderBlocked):
        return str(error)
    cause = f"{type(error).__name__}: {error}"
    if isinstance(error, AuthRequiredError):
        return f"{markers.AUTH_REQUIRED}: {cause}"
    return f"skipped: cannot isolate; {cause}" if isinstance(error, isolation.IsolationError) else cause


def transcript_session(transcript: Transcript) -> str | None:
    sid = getattr(transcript, "session_id", None)
    return sid() if callable(sid) else transcript.path.stem


@dataclass
class Launched:
    target: Target
    binary: profiles.Binary
    versions: dict[str, str]
    pane_log: Path
    ready_signal: str
    dialogs: list[str]
    mode: profiles.Mode = "auto"
    env: dict[str, str] = field(default_factory=dict)
    adapter: Adapter | None = None
    label: str | None = None
    notes: tuple[str, ...] = ()
    mods: LaunchMods | None = None
    home: Path | None = None


def write_launch_files(files: dict[str, str], work_dir: Path, home: Path) -> None:
    for name, content in files.items():
        path = home / name[len("$HOME/"):] if name.startswith("$HOME/") else work_dir / name
        resolved = path.resolve()
        if not (resolved.is_relative_to(work_dir.parent.parent) or resolved.is_relative_to(home)):
            raise isolation.IsolationError(f"launch file {path} is outside the run")
        resolved.parent.mkdir(parents=True, exist_ok=True)
        write_private(resolved, content)


def backend_socket(mods: LaunchMods, home: Path, env: dict[str, str] | None = None) -> Path | str | None:
    if mods.backend == "codex-daemon":
        return backends.codex_daemon_socket(home)
    if mods.backend in backends.OPENCODE_KINDS:
        return backends.opencode_url(list(mods.backend_argv or ()), env or {})
    url = next((a for a in mods.backend_argv or () if a.startswith("unix://")), None)
    return Path(url[len("unix://"):]) if url else None


def resume_extra(target: Target) -> tuple[str, ...]:
    match target.backend:
        case "codex-app-server":
            return ("--remote", f"unix://{target.backend_ref}")
        case "opencode-server":
            return ("--server", str(target.backend_ref))
    return ()


def ready_sockets(adapter: Adapter | None, target: Target) -> list[Path]:
    return list(getattr(adapter, "ready_sockets", lambda _t: [])(target))


def bridge_versions(adapter: Adapter | None) -> dict[str, str]:
    return dict(getattr(adapter, "bridge_versions", dict)())


def with_path(env: dict[str, str], prepend: tuple[str, ...]) -> dict[str, str]:
    if not prepend:
        return env
    return env | {"PATH": ":".join([*prepend, env.get("PATH", "")]).rstrip(":")}


def bridge_launch(mods: LaunchMods, tui: list[str], prefix: list[str]) -> tuple[list[str], list[str]]:
    args = tui[len(prefix):]
    if mods.args_in_shim:
        return list(mods.launcher), [*prefix, *args]
    return [*mods.launcher, *args], prefix


def write_agent_shim(shim_dir: Path, agent: AgentName, prefix: list[str]) -> Path:
    shim_dir.mkdir(parents=True, exist_ok=True)
    path = shim_dir / agent
    path.write_text(profiles.shim_script(prefix))
    path.chmod(0o755)
    return shim_dir


def poll(check, timeout_s: float, interval_s: float = 1.0):
    deadline = time.monotonic() + timeout_s
    while True:
        value = check()
        if value or time.monotonic() >= deadline:
            return value
        time.sleep(interval_s)


def sandbox_mode_is_nono(mode: str) -> bool:
    return mode == "nono"


class Engine:
    def __init__(self, layout: Layout, environ: dict[str, str] | None = None, sandbox: str = "raw",
                 user_config: bool = False):
        self.layout = layout
        self.sandbox = sandbox
        self.user_config = user_config
        self.environ = dict(os.environ if environ is None else environ)
        self.user_home = self.environ.get("HOME", str(Path.home()))
        self.tmux = TmuxHost(layout.tmux_conf)
        self.extra_hosts: dict[str, object] = {}
        self.nono = sandboxing.nono_binary() if sandbox_mode_is_nono(sandbox) else None

    def host_for(self, kind: str):
        if kind == "tmux":
            return self.tmux
        if kind not in self.extra_hosts:
            self.extra_hosts[kind] = make_host(kind)
        return self.extra_hosts[kind]

    def host_of(self, target: Target):
        return self.host_for(target.host)

    def new_run(self, exclude: frozenset[str] = frozenset()) -> Manifest:
        manifest.refuse_if_live(self.layout, exclude)
        run_id = new_run_id(time.time())
        m = Manifest(run_id=run_id, pgids=[], targets=[], sockets=[], backends=[])
        manifest.save(self.layout, m)
        return m

    def launch(self, m: Manifest, agent: AgentName, mode: profiles.Mode = "auto",
               adapter: Adapter | None = None, label: str | None = None) -> tuple[Manifest, Launched]:
        require_supported(adapter, agent)
        binary = self.resolve(agent)
        daemon = profiles.codex_daemon_version(binary) if agent == "codex" else None
        slot = label or agent
        work_dir = self.layout.work_dir(m.run_id, slot)
        home = self.layout.home_dir(m.run_id, slot)
        model, effort = profiles.MODELS[agent]
        iso = isolation.build_home(agent, home, work_dir, self.layout.runs, binary.version, model, effort, mode,
                                   self.environ, time.time())
        host_kind = getattr(adapter, "host_kind", "tmux")
        mods = replace(adapter.launch_mods(agent, work_dir.resolve(), home.resolve()), host=host_kind) if adapter \
            else LaunchMods(host="tmux")
        getattr(adapter, "prepare_launch", lambda *_: None)(agent, work_dir.resolve(), home.resolve())
        write_launch_files(mods.files, work_dir.resolve(), home.resolve())
        for sock in adapter.run_sockets(work_dir.resolve()) if adapter else []:
            m = self.add_socket(m, sock)
        base_env, target_home, argv_home, notes = iso.env, home.resolve(), None, ()
        if self.user_config:
            inv = userconfig.inventory(agent, Path(self.user_home), self.layout.runs)
            run_dir = self.layout.run_dir(m.run_id).resolve()
            ov = userconfig.overlay(inv, iso.env, mods, home.resolve(), work_dir.resolve(), run_dir,
                                    Path(self.user_home), model, effort)
            userconfig.verify(inv, ov, run_dir)
            base_env, mods, target_home, argv_home = ov.env, ov.mods, ov.home, ov.argv_home
            notes = (userconfig.overlay_note(inv),)
        env = with_path(base_env | {"TERM": self.host_for(mods.host).term} | mods.env, mods.path_prepend)
        if agent == "codex" and mods.backend != "none":
            (home / "config.toml").write_text(isolation.codex_config(work_dir.resolve(), self.layout.runs.resolve(),
                                                                     model, effort, mode))
        backend_ref = None
        session_id = profiles.new_session_id(agent, int(time.time() * 1000))
        if mods.backend_argv:
            m, backend_ref = self.start_backend(m, mods, env, work_dir.resolve(), home.resolve(), agent)
            prepare = getattr(adapter, "prepare_backend", None)
            if prepare and backend_ref:
                session_id = prepare(backend_ref, session_id, work_dir.resolve(), home.resolve())
        tui = profiles.tui_argv(binary, mode, work_dir.resolve(), session_id, mods.backend, mods.extra_args,
                                home=home.resolve())
        if argv_home:
            tui = [argv_home[1] if a == argv_home[0] else a for a in tui]
        if mods.launcher:
            tui, shim = bridge_launch(mods, tui, profiles.command_prefix(binary, home.resolve()))
            shims = write_agent_shim(self.layout.run_dir(m.run_id).resolve() / "bin" / slot, agent, shim)
            env = with_path(env, (str(shims),))
        argv = profiles.launch_argv(tui)
        if mods.backend == "codex-daemon":
            daemon = profiles.codex_daemon_version(binary, env)
        versions = (profiles.versions_for(binary, daemon, profiles.os_label()) | bridge_versions(adapter)
                    | self.sandbox_versions())
        launched = Launched(None, binary, versions, Path(), "", [], mode, env, adapter, label, notes, mods,
                            target_home)
        return self.start(m, launched, argv, session_id, f"{m.run_id}-{slot}", f"pane-{slot}.log",
                          mods.backend, backend_ref, mods.host)

    def start_backend(self, m: Manifest, mods: LaunchMods, env: dict[str, str], work_dir: Path,
                      home: Path, agent: AgentName) -> tuple[Manifest, str | None]:
        run_dir = self.layout.run_dir(m.run_id).resolve()
        sock = backend_socket(mods, home, env)
        spec = backends.BackendSpec(mods.backend, list(mods.backend_argv or ()), env, str(work_dir),
                                    str(sock) if sock else None, str(run_dir / "backend.log"),
                                    self.backend_sandbox(agent), self.user_config)
        backends.require_isolated(spec, run_dir, Path(self.user_home))
        if isinstance(sock, Path):
            m = self.add_socket(m, sock)
        pid = backends.launch(run_dir, spec, Path(self.user_home))
        m = self.track_backend(m, mods.backend, pid, home)
        return m, str(sock) if sock else None

    def track_restarted_backend(self, m: Manifest, target: Target) -> Manifest:
        pid = backends.current_pid(self.layout.run_dir(m.run_id))
        return self.track_backend(m, target.backend, pid, target.home_dir, replace_kind=True) if pid else m

    def track_backend(self, m: Manifest, kind: str, pid: int, home: Path | None = None,
                      replace_kind: bool = False) -> Manifest:
        pids = [pid, *(backends.daemon_side_pids(home) if kind == "codex-daemon" and home else [])]
        return self.track(m, kind, pids, replace_kind, spawned=frozenset({pid}))

    def track(self, m: Manifest, kind: str, pids: list[int], replace_kind: bool = False,
              spawned: frozenset[int] = frozenset()) -> Manifest:
        pids = self.with_provenance(m, kind, pids, spawned)
        current = procs.identities({*pids, *manifest.tracked_pids(m)})
        m = manifest.with_tracked(m, kind, {p: current[p] for p in pids if p in current}, current, replace_kind)
        manifest.save(self.layout, m)
        return m

    def with_provenance(self, m: Manifest, kind: str, pids: list[int],
                        spawned: frozenset[int] = frozenset()) -> list[int]:
        if not pids:
            return pids
        rows = procs.ps_rows()
        agents = {t.agent_pid for t in m.targets if t.agent_pid}
        tracked = manifest.owned_tracked(m, procs.identities(manifest.tracked_pids(m)))
        roots = {*spawned, *procs.group_members(rows, set(m.pgids)), *agents, *tracked}
        kept = procs.with_provenance(rows, pids, roots, procs.cwds(set(pids)), self.layout.run_dir(m.run_id),
                                     self.layout.root / "vendor")
        for pid in (p for p in pids if p not in kept):
            print(f"note: not tracking {kind} pid {pid}: not started by this run, and its cwd is "
                  f"outside runs/{m.run_id}", file=sys.stderr)
        return kept

    def track_spawned(self, m: Manifest, pids: tuple[int, ...]) -> Manifest:
        return self.track(m, "deferred-sender", list(pids), spawned=frozenset(pids)) if pids else m

    def resume(self, m: Manifest, launched: Launched, session_id: str) -> tuple[Manifest, Launched]:
        old = launched.target
        owned = manifest.load(self.layout, m.run_id) or m
        manifest.assert_owned(owned, old, self.layout.runs)
        manifest.assert_session_owned(owned, session_id, {transcript_session(t) for t in self.all_transcripts(old)})
        mods = launched.mods
        extra = mods.extra_args if mods is not None else resume_extra(old)
        tui = profiles.resume_argv(launched.binary, launched.mode, old.work_dir, session_id, old.backend, extra,
                                   home=old.home_dir)
        slot = launched.label or old.agent
        if mods is not None and mods.launcher:
            tui, shim = bridge_launch(mods, tui, profiles.command_prefix(launched.binary, old.home_dir))
            write_agent_shim(self.layout.run_dir(m.run_id).resolve() / "bin" / slot, old.agent, shim)
        argv = profiles.launch_argv(tui)
        return self.start(m, replace(launched, target=old), argv, session_id, f"{m.run_id}-{slot}-resumed",
                          f"pane-{slot}-resumed.log", old.backend, old.backend_ref, old.host)

    def start(self, m: Manifest, launched: Launched, argv: list[str], session_id: str | None, name: str,
              log_name: str, backend: Backend = "none", backend_ref: str | None = None,
              host_kind: HostKind = "tmux") -> tuple[Manifest, Launched]:
        agent = launched.binary.agent
        host = self.host_for(host_kind)
        slot = launched.label or agent
        work_dir = self.layout.work_dir(m.run_id, slot).resolve()
        home = launched.home or self.layout.home_dir(m.run_id, slot).resolve()
        start = getattr(launched.adapter, "start_session", None) or host.start
        argv, env = self.sandboxed(agent, argv, launched.env, m.run_id)
        try:
            host_ref = start(name, argv, env, work_dir,
                             self.layout.run_dir(m.run_id).resolve() / f"env-{name}.sh",
                             state_dir_for(host_kind, m.run_id, SOCKET_DIR))
        finally:
            m = self.track_daemons(m, launched.adapter, work_dir)
        pane_pid = pid_or_stop(host, host_ref)
        transcript = transcript_path(home, work_dir, session_id) if agent == "claude" and session_id else None
        target = Target(run_id=m.run_id, agent=agent, host=host_kind, backend=backend, work_dir=work_dir,
                        home_dir=home, session_id=session_id, host_ref=host_ref, backend_ref=backend_ref,
                        transcript=transcript, agent_pid=None)
        m = manifest.with_target(replace(m, pgids=[*m.pgids, procs.owned_group(procs.ps_rows(), pane_pid)]), target)
        manifest.save(self.layout, m)
        pane_log = self.layout.run_dir(m.run_id) / log_name
        recorder = host.start_recording(host_ref, pane_log)
        if isinstance(recorder, int):
            m = self.track(m, "recorder", [recorder], spawned=frozenset({recorder}))
        target, signal, dialogs = self.await_ready(target, launched.binary, pane_pid)
        m = manifest.with_target(m, target)
        if target.agent_pid:
            m = manifest.with_identities(m, procs.identities({target.agent_pid}))
        entry = registry_entry(home, target.agent_pid) if agent == "claude" and target.agent_pid else None
        sid = (entry or {}).get("sessionId")
        if sid and sid != target.session_id:
            target = replace(target, session_id=sid, transcript=transcript_path(home, work_dir, sid))
            m = manifest.with_target(m, target)
        sock = (entry or {}).get("messagingSocketPath")
        new_sockets = ([Path(sock)] if sock else []) + ready_sockets(launched.adapter, target)
        m = replace(m, sockets=[*m.sockets, *(s for s in new_sockets if s not in m.sockets)])
        manifest.save(self.layout, m)
        daemons = list(getattr(launched.adapter, "ready_pids", lambda _t: [])(target))
        if daemons:
            m = self.track(m, "bridge-daemon", daemons)
        marker = getattr(launched.adapter, "startup_marker", None)
        notes = (*launched.notes, self.await_startup_turn(target, marker)) if marker else launched.notes
        return m, replace(launched, target=target, pane_log=pane_log, ready_signal=signal, dialogs=dialogs,
                          notes=notes)

    def require_nono(self) -> str:
        if not self.nono:
            raise profiles.ProfileError("--sandbox nono needs nono on PATH")
        return self.nono

    def sandbox_versions(self) -> dict[str, str]:
        return {"nono": sandboxing.nono_version(self.require_nono())} if sandbox_mode_is_nono(self.sandbox) else {}

    def sandboxed(self, agent: AgentName, argv: list[str], env: dict[str, str],
                  run_id: str) -> tuple[list[str], dict[str, str]]:
        if not sandbox_mode_is_nono(self.sandbox):
            return argv, env
        wrap = sandboxing.wrap_launch if argv and sandboxing.is_sops_exec(argv[0]) else sandboxing.wrap_command
        wrapped = wrap(agent, argv, env, self.require_nono(), Path(self.user_home))
        return wrapped.argv, wrapped.env

    def backend_sandbox(self, agent: AgentName) -> dict[str, str] | None:
        if not sandbox_mode_is_nono(self.sandbox):
            return None
        return {"agent": agent, "nono": self.require_nono(), "user_home": self.user_home}

    def await_startup_turn(self, target: Target, marker: str) -> str:
        t0 = time.monotonic()

        def seen() -> bool:
            transcript = self.transcript_for(target)
            return bool(transcript) and any(marker in t for _, k, t in transcript.entries() if k in STARTUP_KINDS)
        if not poll(seen, STARTUP_APPEAR_S):
            return "startup-turn=none"
        idle = self.wait_idle(target, STARTUP_SETTLE_S, settle_s=3.0)
        return f"startup-turn={time.monotonic() - t0:.1f}s" + ("" if idle else " (still busy)")

    def track_daemons(self, m: Manifest, adapter: Adapter | None, work_dir: Path) -> Manifest:
        daemons = list(getattr(adapter, "daemon_pids", lambda _w: [])(work_dir))
        return self.track(m, "bridge-daemon", daemons) if daemons else m

    def track_bridge_daemons(self, m: Manifest, adapter: Adapter, target: Target) -> Manifest:
        m = self.track_daemons(m, adapter, target.work_dir)
        pids = list(getattr(adapter, "ready_pids", lambda _t: [])(target))
        return self.track(m, "bridge-daemon", pids) if pids else m

    def readopt_agent(self, m: Manifest, target: Target, binary: profiles.Binary,
                      marker: str | None = None) -> tuple[Manifest, Target, bool]:
        old_pid = target.agent_pid
        if old_pid and procs.running(old_pid, m.identities.get(old_pid)):
            return m, target, False
        self.check_owned(target, live=False)
        pane_pid = self.host_of(target).pane_pid(target.host_ref)
        pgid = procs.owned_group(procs.ps_rows(), pane_pid)
        m = replace(m, pgids=list(dict.fromkeys([*m.pgids, pgid])))
        try:
            target, _, _ = self.await_ready(replace(target, agent_pid=None), binary, pane_pid)
        except AuthRequiredError:
            raise
        except (RuntimeError, TimeoutError) as e:
            raise AgentLostError(f"{target.agent} pid {old_pid} gone and nothing respawned it: {e}") from e
        if not target.agent_pid:
            raise AgentLostError(f"{target.agent} pid {old_pid} gone and no agent process is in the pane")
        m = manifest.with_target(m, target)
        m = manifest.with_identities(m, procs.identities({target.agent_pid}))
        manifest.save(self.layout, m)
        if marker:
            self.await_startup_turn(target, marker)
        return m, target, target.agent_pid != old_pid

    def add_pgid(self, m: Manifest, pgid: int) -> Manifest:
        m = replace(m, pgids=[*m.pgids, pgid])
        manifest.save(self.layout, m)
        return m

    def add_socket(self, m: Manifest, path: Path) -> Manifest:
        m = replace(m, sockets=[*m.sockets, path])
        manifest.save(self.layout, m)
        return m

    def await_ready(self, target: Target, binary: profiles.Binary, pane_pid: int) -> tuple[Target, str, list[str]]:
        deadline = time.monotonic() + READY_TIMEOUT_S[target.agent]
        dialogs: list[str] = []
        host = self.host_of(target)
        auth_seen: float | None = None
        while time.monotonic() < deadline:
            if not host.alive(target.host_ref):
                raise RuntimeError(f"{target.agent} exited before becoming ready")
            live = target.agent_pid if target.agent_pid and procs.alive(target.agent_pid) else None
            pid = live or procs.find_agent_pid(procs.ps_rows(), pane_pid, str(binary.path), binary.process)
            if pid and pid != target.agent_pid:
                target = replace(target, agent_pid=pid)
            pane = host.capture(target.host_ref)
            auth = auth_screen(target.agent, pane)
            auth_seen = auth_since(auth_seen, auth, time.monotonic())
            if auth and time.monotonic() - auth_seen >= AUTH_HOLD_S:
                raise AuthRequiredError(f"{target.agent} shows a login/auth screen: {auth!r}")
            if auth:
                time.sleep(0.5)
                continue
            dialog = match_dialog(target.agent, pane)
            if dialog and dialog.label not in dialogs[-3:]:
                dialogs.append(dialog.label)
                self.check_owned(target, live=False)
                for key in dialog.keys:
                    host.send_key(target.host_ref, key)
                    time.sleep(0.3)
                time.sleep(1.0)
                continue
            if target.agent == "claude" and pid:
                entry = registry_entry(target.home_dir, pid)
                if entry and entry.get("status") == "idle" and pane_ready("claude", pane):
                    return target, "registry:idle", dialogs
            elif pane_ready(target.agent, pane):
                time.sleep(1.0)
                return target, "pane-regex", dialogs
            time.sleep(0.5)
        if auth_seen is not None:
            raise AuthRequiredError(f"{target.agent} shows a login/auth screen at the ready timeout")
        raise TimeoutError(f"{target.agent} not ready after {READY_TIMEOUT_S[target.agent]:.0f}s; dialogs={dialogs}")

    def transcript_for(self, target: Target) -> Transcript | None:
        if target.agent == "claude":
            if not target.session_id:
                return None
            return ClaudeTranscript(transcript_path(target.home_dir, target.work_dir, target.session_id))
        if target.agent == "codex":
            return CodexTranscript.locate(target.home_dir, target.work_dir, target.session_id)
        if target.agent == "pi":
            return PiTranscript.locate(profiles.pi_session_dir(target.home_dir), target.work_dir, target.session_id)
        if target.agent == "opencode":
            return OpenCodeTranscript.locate(target.home_dir, target.work_dir, target.session_id)
        if target.agent == "droid":
            return DroidTranscript.locate(target.home_dir, target.work_dir, target.session_id)
        return None

    def idle(self, target: Target, transcript: Transcript | None) -> bool:
        state = transcript.is_idle() if transcript else None
        if state is None:
            return pane_ready(target.agent, self.host_of(target).capture(target.host_ref))
        return state

    def wait_for_token(self, target: Target, token: str, timeout_s: float) -> tuple[Transcript | None, bool]:
        return self.wait_for_acks(target, [token], timeout_s)

    def wait_for_acks(self, target: Target, tokens: list[str], timeout_s: float) -> tuple[Transcript | None, bool]:
        deadline = time.monotonic() + timeout_s
        transcript = None
        held_since = None
        while time.monotonic() < deadline:
            if transcript is None or not all(transcript.find_token(tok) for tok in tokens):
                transcript = self.token_transcript(target, tokens)
            if not self.host_of(target).alive(target.host_ref):
                break
            if transcript:
                entries = transcript.entries()
                texts = [t for _, k, t in entries if k == "assistant"]
                acked = all(any(f"ACK {tok}" in t for t in texts) for tok in tokens)
                if acked and self.idle(target, transcript):
                    return transcript, True
                if all_held(entries, tokens):
                    held_since = held_since or time.monotonic()
                    if time.monotonic() - held_since >= HELD_GRACE_S:
                        break
            time.sleep(1.0)
        return transcript, False

    def token_transcript(self, target: Target, tokens: list[str]) -> Transcript | None:
        holders = [t for t in self.all_transcripts(target) if all(t.find_token(tok) for tok in tokens)]
        return holders[-1] if holders else self.transcript_for(target)

    def wait_idle(self, target: Target, timeout_s: float, settle_s: float = 2.0) -> bool:
        def check() -> bool:
            transcript = self.transcript_for(target)
            return (pane_ready(target.agent, self.host_of(target).capture(target.host_ref))
                    and self.idle(target, transcript))
        ok = bool(poll(check, timeout_s))
        time.sleep(settle_s)
        return ok

    def current_target(self, m: Manifest, target: Target) -> tuple[Manifest, Target]:
        if target.agent == "claude" and target.agent_pid:
            sid = (registry_entry(target.home_dir, target.agent_pid) or {}).get("sessionId")
            if sid and sid != target.session_id:
                target = replace(target, session_id=sid, transcript=transcript_path(target.home_dir,
                                                                                    target.work_dir, sid))
        else:
            transcript = self.transcript_for(replace(target, session_id=None))
            if transcript is not None and hasattr(transcript, "session_id"):
                target = replace(target, session_id=transcript.session_id(), transcript=transcript.path)
        m = manifest.with_target(m, target)
        manifest.save(self.layout, m)
        return m, target

    def all_transcripts(self, target: Target) -> list[Transcript]:
        if target.agent == "claude":
            return [ClaudeTranscript(p) for p in sorted((target.home_dir / "projects").glob("*/*.jsonl"))]
        if target.agent == "codex":
            paths = sorted((target.home_dir / "sessions").rglob("rollout-*.jsonl"))
            metas = [(codex_meta(p) or {}, p) for p in paths]
            return [CodexTranscript(p) for meta, p in metas
                    if meta.get("cwd") == str(target.work_dir) and meta.get("thread_source") != "subagent"]
        if target.agent == "opencode":
            return OpenCodeTranscript.locate_all(target.home_dir, target.work_dir)
        found = self.transcript_for(replace(target, session_id=None))
        return [found] if found else []

    def check_owned(self, target: Target, live: bool = True) -> None:
        current = manifest.load(self.layout, target.run_id)
        if current is None:
            raise manifest.OwnershipError(f"no manifest for run {target.run_id}")
        rows = procs.ps_rows() if live and target.agent_pid else None
        manifest.assert_owned(current, target, self.layout.runs, rows)

    def receiver_gone(self, target: Target) -> str | None:
        if not self.host_of(target).alive(target.host_ref):
            return "pane-exited"
        if target.agent_pid and not procs.alive(target.agent_pid):
            return f"pid {target.agent_pid} gone"
        return None

    def snapshot(self, target: Target, label: str) -> str:
        host = self.host_of(target)
        pane = host.capture(target.host_ref) if host.alive(target.host_ref) else ""
        (self.layout.run_dir(target.run_id) / f"pane-{target.agent}-{label}.txt").write_text(pane)
        return pane

    def run_cell(self, m: Manifest, launched: Launched, adapter: Adapter, scenario: str, stage: str,
                 rep: int) -> ResultRecord:
        from agentcomms.scenarios import run_scenario
        return run_scenario(self, m, launched, adapter, scenario, stage, rep)

    def write_body_diff(self, run_id: str, agent: str, sent: str, received: str) -> str:
        diff = "\n".join(difflib.unified_diff(sent.splitlines(), received.splitlines(), "sent", "received",
                                              lineterm=""))
        path = self.layout.run_dir(run_id) / f"body-diff-{agent}.txt"
        path.write_text(f"{diff}\n\n--- received ---\n{received}\n")
        return str(path.relative_to(self.layout.root))

    def failure_record(self, m: Manifest, agent: AgentName, adapter_name: str, stage: str, scenario: str, rep: int,
                       versions: dict[str, str], error: Exception, backend: Backend = "none",
                       host: HostKind = "tmux") -> ResultRecord:
        return self.plain_record(m, agent, adapter_name, stage, scenario, rep, versions, failure_delivery(error),
                                 failure_note(error), backend, host)

    def plain_record(self, m: Manifest, agent: AgentName, adapter_name: str, stage: str, scenario: str, rep: int,
                     versions: dict[str, str], delivery: Delivery, note: str,
                     backend: Backend, host: HostKind) -> ResultRecord:
        extra = "; ".join(self.host_notes(host))
        extra = f"; {extra}" if extra else ""
        return ResultRecord(
            run_id=m.run_id, stage=stage, agent=agent, versions={**versions, "os": profiles.os_label()},
            mechanism=adapter_name, host=host, backend=backend, scenario=scenario, rep=rep, sandbox=self.sandbox,
            delivery=delivery, intact=None, draft_fate=DraftFate.NA, ack=Ack.NONE, harmful=False, retries=0,
            latency_s=None, evidence=[],
            notes=tildify(note, self.user_home)[:300 - len(extra)] + extra, ts=time.time(),
        )

    def host_notes(self, kind: str) -> list[str]:
        return getattr(self.extra_hosts.get(kind), "take_notes", lambda: [])()

    def resolved_session(self, m: Manifest, target: Target) -> Manifest:
        transcript = self.transcript_for(target)
        if isinstance(transcript, CodexTranscript | DroidTranscript | PiTranscript | OpenCodeTranscript):
            target = replace(target, session_id=transcript.session_id(), transcript=transcript.path)
            m = manifest.with_target(m, target)
            manifest.save(self.layout, m)
        return m

    def resolve(self, agent: AgentName) -> profiles.Binary:
        return profiles.resolve(agent, self.layout.runs, self.environ.get("PATH", ""))

    def check_versions(self, launched: Launched) -> bool:
        if self.resolve(launched.binary.agent) != launched.binary:
            return False
        recorded = launched.versions.get("codex_daemon")
        return not recorded or profiles.codex_daemon_version(launched.binary, launched.env) in (None, recorded)

    def post_session_checks(self, target: Target) -> list[str]:
        if not target.home_dir.resolve().is_relative_to(self.layout.runs.resolve()):
            return []
        return isolation.auth_link_problems(target.agent, target.home_dir)
