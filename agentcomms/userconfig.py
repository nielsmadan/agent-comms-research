import itertools
import json
import os
import re
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path

from agentcomms.model import AgentName, LaunchMods
from agentcomms.paths import SOCKET_DIR

STAGE = "user-config"
HOOKLINESINKER = "hooklinesinker"
XDG_STATE = "xdg-state"
RL_SHIM_DIR = "bin/user-config"
PI_WRITES = ("Pi started with the user's ~/.pi/agent rewrites settings.json (lastChangelogVersion), auth.json and "
             "models-store.json and checks npm for package updates; there is no per-launch switch for the "
             "changelog write (results/notes.md, \"Global config write\")")
CODEX_DAEMON_BLOCK = ("attaches to the user's live Codex daemon: `codex app-server daemon start` with the user's "
                      "CODEX_HOME is the user's own daemon")
OVERLAY_AGENTS = frozenset({"codex", "pi", "opencode"})
CODEX_DEVICE_PLUGINS = ("computer-use", "unified-computer-use", "chrome", "browser")
LOCAL_KINDS = frozenset({"agent"})
REVIEWED_LOCAL = frozenset({("codex", "hook", "agent-sandbox-status"), ("opencode", "plugin", "mouthfeel.js"),
                            ("opencode", "plugin", "nono-sandbox.ts"), ("opencode", "plugin", "sandbox-status.ts")})
UNCLASSIFIED = "unclassified: not on the reviewed list of local-only integrations"


class UserConfigSkip(Exception):
    pass


@dataclass(frozen=True)
class Integration:
    kind: str
    name: str
    outward: bool = False
    disable: str | None = None
    why: str = ""


@dataclass(frozen=True)
class Inventory:
    agent: AgentName
    integrations: tuple[Integration, ...] = ()
    trust_problem: str | None = None
    blocked: dict[str, str] = field(default_factory=dict)
    writes_problem: str | None = None


def classify(agent: AgentName, kind: str, name: str) -> Integration:
    if HOOKLINESINKER in name:
        return Integration(kind, name, True, "XDG_STATE_HOME=<a dir inside the run>",
                           "forwards hook events to the consumers registered in ~/.local/state/hooklinesinker "
                           "(the user's Juggler app and ringleader); with XDG_STATE_HOME in the run (Codex, Pi: "
                           "<run>/xdg-state; OpenCode: its isolated <home>/state) it finds no consumers and keeps "
                           "its status in the run")
    if kind == "plugin" and name.startswith("telegram@"):
        return Integration(kind, name, True, None,
                           "channel plugin polling the user's Telegram bot; no overlay applies a switch for Claude")
    if kind == "notify":
        return Integration(kind, name, True, "-c notify=[]", "turn-end notification into a desktop app")
    if kind == "mcp":
        return Integration(kind, name, True, mcp_disable(agent, name), "MCP server of an external web service")
    if kind == "plugin" and agent == "codex":
        device = name.split("@", 1)[0] in CODEX_DEVICE_PLUGINS
        return Integration(kind, name, True, f'-c plugins."{name}".enabled=false',
                           "drives the user's browser or desktop (device integration)" if device
                           else "remote plugin catalog and plugin cache")
    if kind == "app" and agent == "codex":
        return Integration(kind, name, True, None,
                           "app connector with no verified per-launch switch (apps.<id>.enabled is documented, "
                           "but openai/codex#17588 reports connector config disables being ignored)")
    if kind == "extension" and "ringleader" in name:
        return Integration(kind, name, True, "PATH=<run>/bin/user-config (no-op `rl`) first",
                           "runs `rl session sweep` on session shutdown against the user's ringleader state")
    if kind == "plugin" and name.startswith("claude-session-driver@"):
        return Integration(kind, name, False, "CSD_WORKER_DIR=/tmp/ac/<run>-csd",
                           "hook writes worker events to /tmp/csd-workers; redirected into /tmp/ac")
    if kind in LOCAL_KINDS or (agent, kind, name) in REVIEWED_LOCAL:
        return Integration(kind, name)
    return Integration(kind, name, True, None, UNCLASSIFIED)


def mcp_disable(agent: AgentName, name: str) -> str | None:
    match agent:
        case "codex":
            return f"-c mcp_servers.{name}.enabled=false"
    return None


def skip_reason(inventory: Inventory, mechanism: str) -> str | None:
    if inventory.trust_problem:
        return f"skipped: trust: {inventory.trust_problem}"
    if inventory.writes_problem:
        return f"skipped: writes global config: {inventory.writes_problem}"
    if inventory.agent not in OVERLAY_AGENTS:
        return f"skipped: no user-config overlay for {inventory.agent}, so no integration switch is applied"
    if mechanism in inventory.blocked:
        return f"skipped: {inventory.blocked[mechanism]}"
    unknown = [i.name for i in inventory.integrations if i.why == UNCLASSIFIED]
    if unknown:
        return f"skipped: unclassified integration {', '.join(unknown)}"
    stuck = [i.name for i in inventory.integrations if i.outward and not i.disable]
    if stuck:
        return f"skipped: outward-facing integration {', '.join(stuck)}"
    return None


def declared(inventory: Inventory) -> list[Integration]:
    return [i for i in inventory.integrations if i.disable]


def has_pair(argv: tuple[str, ...] | list[str], flag: str, value: str) -> bool:
    return any(a == flag and b == value for a, b in itertools.pairwise(argv))


def under(value: str | None, root: Path) -> bool:
    return bool(value) and Path(value).resolve().is_relative_to(root.resolve())


def applied(disable: str, ov: Overlay, run_dir: Path) -> bool:
    mods = ov.mods
    if disable.startswith("-c "):
        value = disable[3:]
        return has_pair(mods.extra_args, "-c", value) and (not mods.backend_argv
                                                           or has_pair(mods.backend_argv, "-c", value))
    if disable.startswith("XDG_STATE_HOME="):
        return under(ov.env.get("XDG_STATE_HOME"), run_dir)
    if disable.startswith("CSD_WORKER_DIR="):
        return ov.env.get("CSD_WORKER_DIR") == str(SOCKET_DIR / f"{run_dir.name}-csd")
    if disable.startswith("PATH="):
        shim = run_dir / RL_SHIM_DIR
        return bool(mods.path_prepend) and Path(mods.path_prepend[0]) == shim and (shim / "rl").is_file()
    return False


def unapplied(inventory: Inventory, ov: Overlay, run_dir: Path) -> list[Integration]:
    return [i for i in declared(inventory) if not applied(i.disable, ov, run_dir)]


def verify(inventory: Inventory, ov: Overlay, run_dir: Path) -> None:
    missing = [i for i in unapplied(inventory, ov, run_dir) if i.outward]
    if missing:
        raise UserConfigSkip("skipped: switch not applied in the built argv/env for outward-facing integration "
                             + ", ".join(f"{i.name} ({i.disable})" for i in missing))


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def read_jsonc(path: Path) -> dict:
    try:
        text = re.sub(r",(\s*[}\]])", r"\1", re.sub(r"(?m)^\s*//.*$", "", path.read_text()))
        value = json.loads(text)
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def hook_names(hooks: dict) -> list[str]:
    commands = [h.get("command", "") for matchers in hooks.values() if isinstance(matchers, list)
                for m in matchers for h in m.get("hooks", []) if isinstance(h, dict)]
    return sorted({os.path.basename(c.split()[0]) for c in commands if c.strip()})


def ancestors_trusted(path: Path, trusted: list[str]) -> bool:
    return any(path == Path(t) or path.is_relative_to(Path(t)) for t in trusted)


def claude_inventory(home: Path, runs: Path) -> Inventory:
    settings = read_json(home / ".claude" / "settings.json")
    state = read_json(home / ".claude.json")
    plugins = sorted(k for k, v in (settings.get("enabledPlugins") or {}).items() if v)
    mods = [d for d in str((settings.get("env") or {}).get("CLAUDE_CODE_PLUGIN_DIRS", "")).split(":") if d]
    items = [*(classify("claude", "hook", n) for n in hook_names(settings.get("hooks") or {})),
             *(classify("claude", "plugin", p) for p in plugins),
             *(classify("claude", "plugin-dir", Path(d).name) for d in mods),
             *(classify("claude", "mcp", n) for n in sorted(state.get("mcpServers") or {})),
             *([classify("claude", "statusline", "statusLine command")] if settings.get("statusLine") else [])]
    trusted = [p for p, v in (state.get("projects") or {}).items() if (v or {}).get("hasTrustDialogAccepted")]
    problem = None if ancestors_trusted(runs, trusted) else (
        "Claude 2.1.312 shows the workspace trust dialog even with --permission-mode bypassPermissions (probe "
        "runs/.scratch/trustprobe) and no ancestor of runs/ is trusted in ~/.claude.json; accepting it writes "
        "projects[<work dir>].hasTrustDialogAccepted into ~/.claude.json and there is no per-launch trust switch")
    return Inventory("claude", tuple(items), problem)


def codex_inventory(home: Path, runs: Path) -> Inventory:
    try:
        config = tomllib.loads((home / ".codex" / "config.toml").read_text())
    except (OSError, tomllib.TOMLDecodeError):
        config = {}
    notify = config.get("notify") or []
    items = [*(classify("codex", "hook", n) for n in hook_names((read_json(home / ".codex" / "hooks.json")
                                                                 .get("hooks")) or {})),
             *([classify("codex", "notify", Path(notify[0]).name)] if notify else []),
             *(classify("codex", "mcp", n) for n in sorted(config.get("mcp_servers") or {})),
             *(classify("codex", "plugin", n) for n, v in sorted((config.get("plugins") or {}).items())
               if (v or {}).get("enabled", True)),
             *(classify("codex", "app", n) for n in sorted(config.get("apps") or {}))]
    blocked = {"codex-queue": CODEX_DAEMON_BLOCK, "codex-queue-embedded": CODEX_DAEMON_BLOCK}
    return Inventory("codex", tuple(items), None, blocked)


def pi_inventory(home: Path, runs: Path) -> Inventory:
    agent_dir = home / ".pi" / "agent"
    settings = read_json(agent_dir / "settings.json")
    packages = [p if isinstance(p, str) else str(p.get("source", "")) for p in settings.get("packages") or []]
    extensions = [str(e) for e in settings.get("extensions") or []]
    auto = sorted(p.name for p in (agent_dir / "extensions").glob("*") if not p.name.startswith("."))
    mcp = sorted(read_json(agent_dir / "mcp.json").get("mcpServers") or {})
    trusted = list(read_json(agent_dir / "trust.json"))
    items = [*(classify("pi", "package", Path(p).name or p) for p in packages),
             *(classify("pi", "extension", e) for e in extensions),
             *(classify("pi", "extension", n) for n in auto),
             *(Integration("mcp", n, False, mcp_disable("pi", n), "Pi has no MCP client of its own") for n in mcp)]
    problem = None if ancestors_trusted(runs, trusted) else "no ancestor of runs/ in ~/.pi/agent/trust.json"
    return Inventory("pi", tuple(items), problem, writes_problem=PI_WRITES)


def opencode_inventory(home: Path, runs: Path) -> Inventory:
    config_dir = home / ".config" / "opencode"
    config = read_jsonc(config_dir / "opencode.json") | read_jsonc(config_dir / "opencode.jsonc")
    plugins = sorted(p.name for p in (config_dir / "plugins").glob("*") if not p.name.startswith("."))
    items = [*(classify("opencode", "plugin", p) for p in plugins),
             *(classify("opencode", "plugin", str(p)) for p in config.get("plugin") or []),
             *(classify("opencode", "mcp", n) for n in sorted(config.get("mcp") or {})),
             *(classify("opencode", "agent", n) for n in sorted(config.get("agent") or {}))]
    blocked = {"opencode-service-steer": "attaches to the user's OpenCode background service: `opencode service "
                                         "start` with the user's config reads ~/.config/opencode/service.json"}
    return Inventory("opencode", tuple(items), None, blocked)


def droid_inventory(home: Path, runs: Path) -> Inventory:
    factory = home / ".factory"
    settings = read_json(factory / "settings.json")
    items = [*(classify("droid", "hook", n) for n in hook_names(read_json(factory / "hooks.json").get("hooks")
                                                                 or read_json(factory / "hooks.json"))),
             *(classify("droid", "mcp", n) for n in sorted(read_json(factory / "mcp.json").get("mcpServers") or {})),
             *([classify("droid", "statusline", "statusLine command")] if settings.get("statusLine") else [])]
    trusted = list(settings.get("trustedFolders") or {})
    problem = None if ancestors_trusted(runs, trusted) else (
        "Droid 0.251.0 asks to trust the work dir, no ancestor of runs/ is in ~/.factory/settings.json "
        "trustedFolders, accepting writes that file and `droid --help` lists no per-launch trust flag")
    return Inventory("droid", tuple(items), problem)


INVENTORIES = {"claude": claude_inventory, "codex": codex_inventory, "pi": pi_inventory,
               "opencode": opencode_inventory, "droid": droid_inventory}


def inventory(agent: AgentName, user_home: Path, runs: Path) -> Inventory:
    return INVENTORIES[agent](user_home, runs.resolve())


@dataclass(frozen=True)
class Overlay:
    env: dict[str, str]
    mods: LaunchMods
    home: Path
    argv_home: tuple[str, str] | None = None


def codex_overrides(inv: Inventory, work_dir: Path, model: str, effort: str) -> list[str]:
    switches = [a for i in declared(inv) if i.disable.startswith("-c ") for a in ("-c", i.disable[3:])]
    return [*switches, "-c", f'model="{model}"', "-c", f'model_reasoning_effort="{effort}"',
            "-c", 'approval_policy="never"', "-c", 'sandbox_mode="danger-full-access"',
            "-c", "check_for_update_on_startup=false", "-c", "features.shell_snapshot=false",
            "-c", f'projects={{"{work_dir}"={{trust_level="trusted"}}}}']


def opencode_content(inv: Inventory, model: str) -> str:
    return json.dumps({"model": model, "share": "disabled"})


def rl_shim(run_dir: Path) -> Path:
    shim_dir = run_dir / RL_SHIM_DIR
    shim_dir.mkdir(parents=True, exist_ok=True)
    rl = shim_dir / "rl"
    rl.write_text("#!/bin/sh\nexit 0\n")
    rl.chmod(0o755)
    return shim_dir


def overlay(inv: Inventory, env: dict[str, str], mods: LaunchMods, home: Path, work_dir: Path, run_dir: Path,
            user_home: Path, model: str, effort: str) -> Overlay:
    state = run_dir / XDG_STATE
    state.mkdir(parents=True, exist_ok=True)
    common = {"XDG_STATE_HOME": str(state), "CSD_WORKER_DIR": str(SOCKET_DIR / f"{run_dir.name}-csd")}
    match inv.agent:
        case "codex":
            flags = tuple(codex_overrides(inv, work_dir, model, effort))
            backend = mods.backend_argv
            argv = (backend[0], *flags, *backend[1:]) if backend else None
            return Overlay(env | common | {"CODEX_HOME": str(user_home / ".codex")},
                           replace(mods, extra_args=(*flags, *mods.extra_args), backend_argv=argv),
                           user_home / ".codex")
        case "pi":
            kept = {k: v for k, v in env.items() if k != "PI_CODING_AGENT_DIR"}
            return Overlay(kept | common, replace(mods, path_prepend=(str(rl_shim(run_dir)), *mods.path_prepend)),
                           home, (f"HOME={home}", f"HOME={user_home}"))
        case "opencode":
            kept = {k: v for k, v in env.items() if k not in ("XDG_CONFIG_HOME", "OPENCODE_TEST_HOME")}
            return Overlay(kept | {"CSD_WORKER_DIR": common["CSD_WORKER_DIR"],
                                   "OPENCODE_CONFIG_CONTENT": opencode_content(inv, model)}, mods, home)
    raise ValueError(f"no user-config overlay for {inv.agent}")


def overlay_note(inv: Inventory) -> str:
    return "user-config: disabled " + ", ".join(f"{i.kind} {i.name}" for i in declared(inv) if i.outward)
