import hashlib
import json
import os
import sqlite3
import subprocess
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from agentcomms.model import AgentName
from agentcomms.records import tildify
from agentcomms.transcripts.opencode import db_path as opencode_db

Mode = Literal["auto", "prompting"]

USER_HOME = Path.home()
CODEX_USER_AUTH = USER_HOME / ".codex" / "auth.json"
OPENCODE_USER_AUTH = USER_HOME / ".local" / "share" / "opencode" / "auth.json"
PASSTHROUGH_ENV = ("HOME", "USER", "LOGNAME", "PATH", "SHELL", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR",
                   "SOPS_SECRETS", "SOPS_AGE_KEY_FILE")

GLOBAL_CONFIG_FILES = (
    "~/.claude.json", "~/.claude/settings.json", "~/.codex/config.toml", "~/.pi/agent/settings.json",
    "~/.config/opencode/opencode.json", "~/.config/opencode/opencode.jsonc", "~/.factory/settings.json",
    "~/.gc/cities.toml", "~/.gc/supervisor.toml", "~/.hcom/config.toml",
)


class IsolationError(Exception):
    pass


@dataclass(frozen=True)
class IsolatedHome:
    agent: AgentName
    home: Path
    env: dict[str, str]


def base_env(environ: dict[str, str]) -> dict[str, str]:
    env = {k: environ[k] for k in PASSTHROUGH_ENV if k in environ}
    env["TERM"] = "tmux-256color"
    env["DISABLE_AUTOUPDATER"] = "1"
    env["AGENT_REQUIRE_SECRETS"] = "1"
    return env


def claude_global_config(work_dir: Path, version: str) -> dict:
    return {
        "hasCompletedOnboarding": True,
        "theme": "dark",
        "numStartups": 1,
        "autoUpdates": False,
        "bypassPermissionsModeAccepted": True,
        "lastReleaseNotesSeen": version,
        "officialMarketplaceAutoInstallAttempted": True,
        "projects": {
            str(work_dir): {
                "hasTrustDialogAccepted": True,
                "hasCompletedProjectOnboarding": True,
                "projectOnboardingSeenCount": 1,
            }
        },
    }


CLAUDE_MD_NAMES = ("CLAUDE.md", "CLAUDE.local.md", ".claude/CLAUDE.md", ".claude/rules/**")


def claude_md_excludes(work_dir: Path, user_home: Path) -> list[str]:
    dirs = [*work_dir.parents, user_home]
    return list(dict.fromkeys(str(d / name) for d in dirs for name in CLAUDE_MD_NAMES))


def resolved_links(paths: list[str]) -> list[str]:
    real = [str(Path(p).resolve()) for p in paths if "*" not in p and Path(p).exists()]
    return [r for r in real if r not in paths]


def claude_settings(md_excludes: list[str] | None = None) -> dict:
    excludes = {"claudeMdExcludes": md_excludes} if md_excludes else {}
    return {"skipDangerousModePermissionPrompt": True, "autoUpdates": False, **excludes}


def toml_str(s: str) -> str:
    return json.dumps(s)


CODEX_MODE_CONFIG = {"auto": ("never", "danger-full-access"), "prompting": ("on-request", "read-only")}


def codex_config(work_dir: Path, runs_root: Path, model: str, effort: str, mode: Mode | None = None) -> str:
    policy = ([f"approval_policy = {toml_str(CODEX_MODE_CONFIG[mode][0])}",
               f"sandbox_mode = {toml_str(CODEX_MODE_CONFIG[mode][1])}"] if mode else [])
    lines = [
        f"model = {toml_str(model)}",
        f"model_reasoning_effort = {toml_str(effort)}",
        *policy,
        "check_for_update_on_startup = false",
        "",
        "[analytics]",
        "enabled = false",
        "",
        "[feedback]",
        "enabled = false",
        "",
        "[features]",
        "shell_snapshot = false",
        "",
        "[notice]",
        "hide_full_access_warning = true",
        "hide_rate_limit_model_nudge = true",
        "",
    ]
    for project in dict.fromkeys([str(runs_root), str(work_dir)]):
        lines += [f"[projects.{toml_str(project)}]", 'trust_level = "trusted"', ""]
    return "\n".join(lines)


def build_claude_home(home: Path, work_dir: Path, version: str, environ: dict[str, str]) -> IsolatedHome:
    home.mkdir(parents=True, exist_ok=True)
    (home / ".claude.json").write_text(json.dumps(claude_global_config(work_dir.resolve(), version), indent=2))
    excludes = claude_md_excludes(work_dir.resolve(), Path(environ.get("HOME", USER_HOME)))
    (home / "settings.json").write_text(json.dumps(claude_settings(excludes + resolved_links(excludes)), indent=2))
    env = base_env(environ) | {"CLAUDE_CONFIG_DIR": str(home)}
    return IsolatedHome("claude", home, env)


def build_codex_home(home: Path, work_dir: Path, runs_root: Path, model: str, effort: str,
                     environ: dict[str, str], user_auth: Path = CODEX_USER_AUTH) -> IsolatedHome:
    if not user_auth.exists():
        raise IsolationError(f"{user_auth} missing; Codex cannot authenticate without writing global config")
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.toml").write_text(codex_config(work_dir.resolve(), runs_root.resolve(), model, effort))
    link = home / "auth.json"
    if not link.is_symlink():
        link.symlink_to(user_auth)
    env = base_env(environ) | {"CODEX_HOME": str(home)}
    return IsolatedHome("codex", home, env)


PI_KEEP_RECENT_TOKENS = 1


def pi_settings(model: str, thinking: str, version: str) -> dict:
    provider, model_id = model.split("/", 1)
    return {
        "defaultProvider": provider,
        "defaultModel": model_id,
        "defaultThinkingLevel": thinking,
        "defaultProjectTrust": "always",
        "packages": [],
        "extensions": [],
        "enableInstallTelemetry": False,
        "lastChangelogVersion": version,
        "quietStartup": True,
        "compaction": {"keepRecentTokens": PI_KEEP_RECENT_TOKENS},
    }


def build_pi_home(home: Path, model: str, thinking: str, version: str, environ: dict[str, str]) -> IsolatedHome:
    home.mkdir(parents=True, exist_ok=True)
    (home / "settings.json").write_text(json.dumps(pi_settings(model, thinking, version), indent=2))
    (home / "sessions").mkdir(exist_ok=True)
    env = base_env(environ) | {"PI_CODING_AGENT_DIR": str(home), "PI_SKIP_VERSION_CHECK": "1", "PI_TELEMETRY": "0"}
    return IsolatedHome("pi", home, env)


def opencode_dirs(home: Path) -> dict[str, Path]:
    return {"XDG_CONFIG_HOME": home / "config", "XDG_DATA_HOME": home / "data", "XDG_STATE_HOME": home / "state",
            "XDG_CACHE_HOME": home / "cache", "TMPDIR": home / "tmp"}


def opencode_auth_link(home: Path) -> Path:
    return home / "data" / "opencode" / "auth.json"


OPENCODE_PROMPTING_PERMISSION = {"edit": "ask", "bash": "ask"}


def opencode_config(model: str, mode: Mode = "auto") -> dict:
    permission = {"permission": OPENCODE_PROMPTING_PERMISSION} if mode == "prompting" else {}
    return {"$schema": "https://opencode.ai/config.json", "model": model, "update": "disable", "share": "disabled",
            **permission}


def opencode_env(home: Path) -> dict[str, str]:
    return {k: str(v) for k, v in opencode_dirs(home).items()} | {
        "OPENCODE_TEST_HOME": str(home), "OPENCODE_DISABLE_AUTOUPDATE": "1"}


def build_opencode_home(home: Path, model: str, environ: dict[str, str],
                        user_auth: Path = OPENCODE_USER_AUTH, mode: Mode = "auto") -> IsolatedHome:
    if not user_auth.exists():
        raise IsolationError(f"{user_auth} missing; OpenCode cannot authenticate without writing global config")
    dirs = opencode_dirs(home)
    for d in dirs.values():
        (d / "opencode").mkdir(parents=True, exist_ok=True)
    config = json.dumps(opencode_config(model, mode), indent=2)
    (dirs["XDG_CONFIG_HOME"] / "opencode" / "opencode.json").write_text(config)
    link = opencode_auth_link(home)
    if not link.is_symlink():
        link.symlink_to(user_auth)
    return IsolatedHome("opencode", home, base_env(environ) | opencode_env(home))


def git_root(path: Path) -> Path | None:
    return next((p for p in [path, *path.parents] if (p / ".git").exists()), None)


def iso_millis(now: float) -> str:
    return datetime.fromtimestamp(now, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def droid_settings(trusted_roots: list[Path], model: str, effort: str, mode: Mode, trusted_at: str) -> dict:
    autonomy = {"autonomyLevel": "high" if mode == "auto" else "off"}
    return {
        "sessionDefaultSettings": {"model": model, "reasoningEffort": effort, **autonomy},
        "trustedFolders": {root: {"trustedAt": trusted_at} for root in dict.fromkeys(map(str, trusted_roots))},
        "logoAnimation": "off",
        "completionSound": "off",
        "awaitingInputSound": "off",
        "enableCompletionBell": False,
        "hasSeenMissionOnboarding": True,
        "includeCoAuthoredByDroid": False,
    }


def droid_dir(home: Path) -> Path:
    return home / ".factory"


def droid_env(home: Path) -> dict[str, str]:
    return {"FACTORY_HOME_OVERRIDE": str(home), "FACTORY_DROID_AUTO_UPDATE_ENABLED": "false",
            "FACTORY_DISABLE_KEYRING": "1"}


def claude_probe_env(tmp: Path) -> dict[str, str]:
    return {"CLAUDE_CONFIG_DIR": str(tmp / ".claude")}


def pi_probe_env(tmp: Path) -> dict[str, str]:
    return {"PI_CODING_AGENT_DIR": str(tmp / ".pi"), "PI_SKIP_VERSION_CHECK": "1", "PI_TELEMETRY": "0"}


PROBE_ENV: dict[str, Callable[[Path], dict[str, str]]] = {
    "claude": claude_probe_env, "pi": pi_probe_env, "opencode": opencode_env, "droid": droid_env}


def build_droid_home(home: Path, work_dir: Path, model: str, effort: str, mode: Mode, environ: dict[str, str],
                     now: float) -> IsolatedHome:
    work = work_dir.resolve()
    roots = [p for p in (work, git_root(work)) if p]
    droid_dir(home).mkdir(parents=True, exist_ok=True)
    settings = droid_settings(roots, model, effort, mode, iso_millis(now))
    (droid_dir(home) / "settings.json").write_text(json.dumps(settings, indent=2))
    return IsolatedHome("droid", home, base_env(environ) | droid_env(home))


def global_config_hashes(files: tuple[str, ...] = GLOBAL_CONFIG_FILES) -> dict[str, str | None]:
    result = {}
    for name in files:
        path = Path(name).expanduser()
        result[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    return result


CHURNING_CONFIG = "~/.claude.json"
USER_STATE_DIRS: dict[str, tuple[str, ...]] = {
    "pi": ("~/.pi/agent",),
    "opencode": ("~/.config/opencode", "~/.local/share/opencode", "~/.opencode"),
    "droid": ("~/.factory",),
}


USER_STORES: dict[str, tuple[str, ...]] = {
    "codex": ("~/.codex",),
    "pi": ("~/.pi/agent",),
    "opencode": ("~/.config/opencode",),
}
STORE_WRITES = "user-store-writes.txt"


def user_store_mtimes(agent: str, home: Path) -> dict[str, float]:
    return {k: v for d in USER_STORES.get(agent, ()) for k, v in tree_mtimes(home / d.removeprefix("~/")).items()}


def store_writes_text(paths: list[str], home: str) -> str:
    return "".join(f"{tildify(p, home)}\n" for p in paths)


def user_state_mtimes(agent: str) -> dict[str, float]:
    return {k: v for d in USER_STATE_DIRS.get(agent, ())
            for k, v in tree_mtimes(Path(d).expanduser(), skip=("node_modules",)).items()}


def marker_refs(node, marker: str, path: str = "") -> set[str]:
    if isinstance(node, dict):
        refs = {f"{path}/{k}" for k in node if marker in str(k)}
        return refs.union(*(marker_refs(v, marker, f"{path}/{k}") for k, v in node.items()))
    if isinstance(node, list):
        return set().union(*(marker_refs(v, marker, f"{path}[{i}]") for i, v in enumerate(node)))
    return {path} if isinstance(node, str) and marker in node else set()


def new_harness_refs(before_text: str, after_text: str, marker: str) -> bool:
    try:
        before, after = json.loads(before_text or "{}"), json.loads(after_text)
    except json.JSONDecodeError:
        return marker in after_text
    return bool(marker_refs(after, marker) - marker_refs(before, marker))


def attribute_changes(before: dict[str, str | None], after: dict[str, str | None],
                      before_texts: dict[str, str], after_texts: dict[str, str],
                      marker: str) -> tuple[list[str], list[str]]:
    changed = [k for k in before if before[k] != after.get(k)]
    ours = [k for k in changed if k != CHURNING_CONFIG
            or new_harness_refs(before_texts.get(k, ""), after_texts.get(k, ""), marker)]
    return ours, [k for k in changed if k not in ours]


def read_texts(names: list[str]) -> dict[str, str]:
    texts = {}
    for name in names:
        path = Path(name).expanduser()
        texts[name] = path.read_text(errors="replace") if path.is_file() else ""
    return texts


def link_intact(link: Path, target: Path) -> bool:
    return link.is_symlink() and os.readlink(link) == str(target)


def auth_link_intact(home: Path, user_auth: Path = CODEX_USER_AUTH) -> bool:
    return link_intact(home / "auth.json", user_auth)


def auth_link_problems(agent: AgentName, home: Path) -> list[str]:
    match agent:
        case "codex" if not auth_link_intact(home):
            return [f"codex auth.json in {home} is no longer a symlink to {CODEX_USER_AUTH}"]
        case "opencode" if not link_intact(opencode_auth_link(home), OPENCODE_USER_AUTH):
            return [f"opencode {opencode_auth_link(home)} is no longer a symlink to {OPENCODE_USER_AUTH}"]
    return []


def tree_mtimes(root: Path, skip: tuple[str, ...] = ()) -> dict[str, float]:
    result = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip]
        for name in filenames:
            path = Path(dirpath) / name
            try:
                result[str(path)] = path.lstat().st_mtime
            except OSError:
                continue
    return result


def changed_paths(before: dict[str, float], after: dict[str, float]) -> list[str]:
    return sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))


BRIDGE_WATCH = (".gc", ".pi/agent/intercom", ".hcom", ".agent-deck", ".config/agent-deck", "Library/LaunchAgents")
APPEND_ONLY = (".gc/events.jsonl", ".gc/supervisor.log")
Stat = tuple[int, float]


def tree_stats(root: Path, skip: tuple[str, ...] = ()) -> dict[str, Stat]:
    result: dict[str, Stat] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip]
        result[dirpath] = (-1, 0.0)
        for name in filenames + [d for d in dirnames if (Path(dirpath) / d).is_symlink()]:
            path = Path(dirpath) / name
            try:
                st = path.lstat()
            except OSError:
                continue
            result[str(path)] = (st.st_size, st.st_mtime)
    return result


def bridge_snapshot(home: str) -> dict[str, Stat]:
    return {k: v for d in BRIDGE_WATCH for k, v in tree_stats(Path(home) / d, skip=("node_modules",)).items()}


@dataclass(frozen=True)
class BridgeDelta:
    stops: list[str]
    appends: list[tuple[str, int]]


def bridge_delta(before: dict[str, Stat], after: dict[str, Stat], home: str) -> BridgeDelta:
    changed = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
    logs = {str(Path(home) / f) for f in APPEND_ONLY}
    grown = [k for k in changed if k in logs and k in before and k in after and after[k][0] >= before[k][0]]
    return BridgeDelta([k for k in changed if k not in grown], [(k, after[k][0] - before[k][0]) for k in grown])


def gc_supervisors(rows: list, vendor: Path) -> list[int]:
    prefix = f"{vendor.resolve()}/"
    return [r.pid for r in rows if " supervisor run" in r.args and Path(r.args.split(" ", 1)[0]).name == "gc"
            and not r.args.startswith(prefix)]


def append_note(appends: list[tuple[str, int]], home: str, user_supervisors: list[int]) -> str | None:
    if not appends:
        return None
    grown = ", ".join(f"{tildify(p, home)} +{n} B" for p, n in appends)
    who = (f"the user's own gc supervisor (pid {', '.join(map(str, user_supervisors))}; harness gc is pinned to "
           "run cities and ports)" if user_supervisors else "unattributed (no user gc supervisor running)")
    return f"note: append-only bridge logs grew: {grown}; attributed to {who}"


def user_state_note(agent: str, touched: list[str], home: str, shown: int = 5) -> str | None:
    if not touched:
        return None
    paths = [tildify(p, home) for p in touched[:shown]]
    more = f" (+{len(touched) - shown} more)" if len(touched) > shown else ""
    return (f"note: {agent} user state changed during run, likely by live user sessions "
            f"({len(touched)} files): {', '.join(paths)}{more}")


def purge_credentials(db: Path) -> int:
    if not db.is_file():
        return 0
    with closing(sqlite3.connect(db, timeout=5.0)) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'credential'").fetchone():
            return 0
        conn.execute("PRAGMA secure_delete = ON")
        removed = conn.execute("DELETE FROM credential").rowcount
        conn.commit()
        conn.execute("VACUUM")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return removed


def credential_dbs(agent: AgentName, home: Path) -> list[Path]:
    return [opencode_db(home)] if agent == "opencode" else []


def init_work_repo(work_dir: Path, environ: dict[str, str]) -> None:
    if (work_dir / ".git").exists():
        return
    env = {k: v for k, v in environ.items() if not k.startswith("GIT_")}
    subprocess.run(["git", "init", "-q", str(work_dir)], env=env, cwd=work_dir, check=True, capture_output=True,
                   timeout=30)


def build_home(agent: AgentName, home: Path, work_dir: Path, runs_root: Path, version: str, model: str,
               effort: str, mode: Mode, environ: dict[str, str], now: float) -> IsolatedHome:
    work_dir.mkdir(parents=True, exist_ok=True)
    init_work_repo(work_dir, environ)
    return with_private_tmp(build_agent_home(agent, home, work_dir, runs_root, version, model, effort, mode, environ,
                                             now))


def with_private_tmp(iso: IsolatedHome) -> IsolatedHome:
    tmp = iso.home / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    return replace(iso, env=iso.env | {"TMPDIR": str(tmp)})


def build_agent_home(agent: AgentName, home: Path, work_dir: Path, runs_root: Path, version: str, model: str,
                     effort: str, mode: Mode, environ: dict[str, str], now: float) -> IsolatedHome:
    match agent:
        case "claude":
            return build_claude_home(home, work_dir, version, environ)
        case "codex":
            return build_codex_home(home, work_dir, runs_root, model, effort, environ)
        case "pi":
            return build_pi_home(home, model, effort, version, environ)
        case "opencode":
            return build_opencode_home(home, model, environ, mode=mode)
        case "droid":
            return build_droid_home(home, work_dir, model, effort, mode, environ, now)
    raise IsolationError(f"isolation for {agent} is not implemented yet")
