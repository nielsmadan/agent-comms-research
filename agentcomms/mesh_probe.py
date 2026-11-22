import json
import subprocess
import time
from dataclasses import replace
from pathlib import Path

from agentcomms import manifest
from agentcomms.adapters.claude_channel import bun
from agentcomms.adapters.claude_uds import ClaudeUdsAccept
from agentcomms.adapters.pi_claude_link import PACKAGE, PiClaudeLink, runtime_dir
from agentcomms.engine import Engine, envelope, new_token, receiver_hits
from agentcomms.model import AgentName, LaunchMods, Target
from agentcomms.transcripts.claude import registry_entry

REPLY_WAIT_S = 150.0
PI_TO_CLAUDE = ("Call the claude-link tool exactly once with these JSON arguments: {args} "
                "Do nothing else and do not answer the message yourself.")
CLAUDE_TO_PI = ('Use the SendMessage tool once to send this exact text to the peer session at address "{to}": {text} '
                "Do nothing else.")


class ClaudeMeshPeer(ClaudeUdsAccept):
    name = "claude-mesh-peer"

    def launch_mods(self, agent: AgentName, work_dir: Path, home_dir: Path) -> LaunchMods:
        mods = super().launch_mods(agent, work_dir, home_dir)
        return replace(mods, env={"XDG_RUNTIME_DIR": str(runtime_dir(work_dir))})


def registry_pids(config_dir: Path) -> set[int]:
    return {int(p.stem) for p in (config_dir / "sessions").glob("*.json") if p.stem.isdigit()}


def mesh_problem(claude: Target, sock: str | None, pi_home: Path, registry: set[int]) -> str | None:
    expected = runtime_dir(claude.work_dir) / "cc-socks"
    if not sock or Path(sock).parent != expected:
        return f"harness Claude socket {sock} is not in {expected}"
    link = pi_home / ".claude"
    if not link.is_symlink() or link.resolve() != claude.home_dir.resolve():
        return f"{link} does not resolve to the harness Claude config dir {claude.home_dir}"
    if registry != {claude.agent_pid}:
        return f"registry {claude.home_dir / 'sessions'} lists pids {sorted(registry)}, not only the harness Claude"
    return None


def is_reply(text: str, token: str) -> bool:
    return f"ACK {token}" in text and "ACK-REQUEST" not in text


def observe(entries: list, token: str) -> tuple[list, list, list]:
    hits = [e for e in receiver_hits(entries, token) if "ACK-REQUEST" in e[2]]
    held = [e for e in entries if e[1] == "held" and token in e[2]]
    replies = [e for e in entries if is_reply(e[2], token)]
    return hits, held, replies


def wait_observed(engine: Engine, target: Target, token: str, timeout_s: float,
                  done=lambda hits, held, replies: bool(hits and replies)) -> tuple[list, list, list]:
    deadline = time.monotonic() + timeout_s
    seen: tuple[list, list, list] = ([], [], [])
    while time.monotonic() < deadline:
        transcript = engine.transcript_for(target)
        seen = observe(transcript.entries() if transcript else [], token)
        if done(*seen):
            break
        time.sleep(2.0)
    return seen


def summary(label: str, seen: tuple[list, list, list], sent_at: float) -> str:
    hits, held, replies = seen
    latency = f"{hits[0][0] - sent_at:.1f}s" if hits else "-"
    kinds = ",".join(sorted({k for _, k, _ in hits})) or "none"
    reply_kinds = ",".join(sorted({k for _, k, _ in replies})) or "none"
    return (f"{label}: received={'yes' if hits else 'no'} as {kinds} {latency} after typing; held={len(held)}; "
            f"reply entries={reply_kinds}")


def vendored_send_argv(sock: str, body: str, from_sock: str) -> list[str]:
    protocol = json.dumps(str(PACKAGE / "claude-protocol.ts"))
    call = json.dumps({"sock": sock, "body": body, "from": f"uds:{from_sock}", "fromName": "pi-pi"})
    return [bun(), "-e", f"const p = await import({protocol}); await p.sendToClaude({call});"]


def type_into(engine: Engine, target: Target, text: str) -> float:
    engine.check_owned(target)
    sent_at = time.time()
    engine.tmux.type_text(target.host_ref, text, submit=True)
    return sent_at


def probe(engine: Engine) -> list[str]:
    m = engine.new_run()
    report = [f"run_id: {m.run_id}"]
    try:
        exercise(engine, m, report)
    finally:
        report += manifest.cleanup(engine.layout, m.run_id)
        (engine.layout.run_dir(m.run_id) / "mesh-probe.txt").write_text("\n".join(report) + "\n")
    return report


def exercise(engine: Engine, m, report: list[str]) -> None:
    m, claude = engine.launch(m, "claude", "auto", ClaudeMeshPeer())
    entry = registry_entry(claude.target.home_dir, claude.target.agent_pid) or {}
    sock = entry.get("messagingSocketPath")
    pi_home = engine.layout.home_dir(m.run_id, "pi").resolve()
    pi_home.mkdir(parents=True, exist_ok=True)
    (pi_home / ".claude").symlink_to(claude.target.home_dir)
    problem = mesh_problem(claude.target, sock, pi_home, registry_pids(claude.target.home_dir))
    if problem:
        report.append(f"refused before launching Pi: {problem}")
        return
    report.append(f"claude pid {claude.target.agent_pid} socket {sock} session {entry.get('sessionId')}")
    m, pi = engine.launch(m, "pi", "auto", PiClaudeLink())
    pi_entry = registry_entry(claude.target.home_dir, pi.target.agent_pid) or {}
    deadline = time.monotonic() + 20
    while not pi_entry and time.monotonic() < deadline:
        time.sleep(1.0)
        pi_entry = registry_entry(claude.target.home_dir, pi.target.agent_pid) or {}
    pi_sock = pi_entry.get("messagingSocketPath")
    report.append(f"pi pid {pi.target.agent_pid} registered as {pi_entry.get('name')!r} socket {pi_sock}")
    if not pi_sock or Path(pi_sock).parent != Path(sock).parent:
        report.append("stopped: pi-claude-link did not register next to the harness Claude socket")
        return

    tok1 = new_token()
    args = json.dumps({"action": "send", "to": entry.get("sessionId"), "message": envelope(tok1, "Mesh test from pi.")})
    sent = type_into(engine, pi.target, PI_TO_CLAUDE.format(args=args))
    report.append(summary(f"pi->claude {tok1}", wait_observed(engine, claude.target, tok1, REPLY_WAIT_S), sent))
    pi_side = observe(engine.transcript_for(pi.target).entries(), tok1)
    report.append(f"claude reply back in pi: {','.join(sorted({k for _, k, _ in pi_side[2]})) or 'none'}")
    engine.wait_idle(pi.target, 60)
    engine.wait_idle(claude.target, 60)

    tok3 = new_token()
    sent = time.time()
    out = subprocess.run(vendored_send_argv(sock, envelope(tok3, "Wire test with the vendored sendToClaude."), pi_sock),
                         capture_output=True, text=True, timeout=30, cwd=engine.layout.run_dir(m.run_id))
    report.append(f"vendored sendToClaude exit {out.returncode} {out.stderr.strip()[:200]}")
    report.append(summary(f"pi-claude-link wire->claude {tok3}",
                          wait_observed(engine, claude.target, tok3, REPLY_WAIT_S), sent))
    pi_side = observe(engine.transcript_for(pi.target).entries(), tok3)
    report.append(f"claude reply to the wire frame back in pi: "
                  f"{','.join(sorted({k for _, k, _ in pi_side[2]})) or 'none'}")
    engine.wait_idle(pi.target, 60)
    engine.wait_idle(claude.target, 60)

    tok2 = new_token()
    sent = type_into(engine, claude.target, CLAUDE_TO_PI.format(to=f"uds:{pi_sock}",
                                                                 text=envelope(tok2, "Mesh test from Claude.")))
    report.append(summary(f"claude->pi {tok2}", wait_observed(engine, pi.target, tok2, REPLY_WAIT_S), sent))
    _, _, relayed = wait_observed(engine, claude.target, tok2, 30,
                                  lambda h, d, r: any(k != "assistant" for _, k, _ in r))
    report.append(f"pi reply back in claude: {','.join(sorted({k for _, k, _ in relayed})) or 'none'}")
    for t in (claude.target, pi.target):
        engine.snapshot(t, "mesh")
