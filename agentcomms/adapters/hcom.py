import json
import re
from functools import cache
from pathlib import Path

from agentcomms.adapters.bridge import BASE_PATH, AgentRoute, BridgeAdapter, run_cli, run_dir
from agentcomms.adapters.native import now, receipt
from agentcomms.adapters.pi_ext import VENDOR, vendored
from agentcomms.model import AgentName, LaunchMods, SendReceipt, Target
from agentcomms.paths import REPO_ROOT

HCOM = VENDOR / "hcom" / "bin" / "hcom"
CROSS_MACHINE = ('hcom README: "Connect agents across machines via MQTT relay" (`hcom relay new`, `hcom relay connect '
                 '<token>`); SECURITY.md: relay payloads are end-to-end encrypted with a shared PSK')
FRAME = re.compile(r"\A\s*(?:<hcom>)?\[[^\]\n]*\] [^\n]*? (?:→|->) [^\n:]*: (.*?)"
                   r"(?: \| \[[^\]\n]*\])?(?:</hcom>)?\s*\Z", re.S)


def hcom_dir(work_dir: Path) -> Path:
    return run_dir(work_dir) / "hcom"


def hcom_env(work_dir: Path) -> dict[str, str]:
    return {"HCOM_DIR": str(hcom_dir(work_dir)), "HCOM_TEST_ROOT": str(run_dir(work_dir))}


def cli_env(work_dir: Path) -> dict[str, str]:
    return {"PATH": BASE_PATH, "HOME": str(hcom_dir(work_dir)), "LANG": "en_US.UTF-8", **hcom_env(work_dir)}


def unwrap_hcom(recorded: str) -> str:
    m = FRAME.match(recorded)
    return m.group(1) if m else recorded


def instance_for(entries: list[dict], work_dir: Path) -> dict | None:
    wanted = str(work_dir)
    return next((e for e in entries if str(e.get("directory", "")).rstrip("/") == wanted), None)


def list_instances(work_dir: Path) -> list[dict]:
    out = run_cli([str(HCOM), "list", "--json"], cli_env(work_dir), timeout_s=15)
    try:
        data = json.loads(out.stdout) if out.code == 0 else []
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def instance_name(target: Target) -> str | None:
    found = instance_for(list_instances(target.work_dir), target.work_dir)
    return found.get("name") if found else None


@cache
def hcom_version() -> str:
    scratch = REPO_ROOT / "runs" / ".version-hcom"
    out = run_cli([str(HCOM), "--version"], {"PATH": BASE_PATH, "HOME": str(scratch), "HCOM_DIR": str(scratch),
                                             "HCOM_TEST_ROOT": str(scratch)}, timeout_s=15)
    return out.stdout.split()[-1] if out.code == 0 and out.stdout.split() else "unknown"


class Hcom(BridgeAdapter):
    shared_run = True
    shared_state = "hcom"
    name = "hcom"
    agents: frozenset[AgentName] = frozenset({"claude", "codex", "pi", "opencode"})
    claims_cross_machine = CROSS_MACHINE
    scenario_na = {"S12": "no backing daemon: hcom processes share an SQLite db and wake each other with local "
                          "TCP pings"}

    def launch_mods(self, agent: AgentName, work_dir: Path, home_dir: Path) -> LaunchMods:
        return LaunchMods(host="tmux", launcher=(str(vendored(HCOM)), agent), env=hcom_env(work_dir),
                          path_prepend=(str(HCOM.parent),))

    def bridge_versions(self) -> dict[str, str]:
        return {"hcom": hcom_version()}

    def send(self, target: Target, text: str) -> SendReceipt:
        name = instance_name(target)
        if not name:
            return receipt(now(), False, "hcom: no hcom instance for the target's work dir")
        return self.cli_send([str(HCOM), "send", f"@{name}", "-b"], cli_env(target.work_dir), text,
                             f"hcom @{name}")

    def unwrap(self, recorded: str) -> str:
        return unwrap_hcom(recorded)

    def sender_argv(self, target: Target) -> list[str] | None:
        name = instance_name(target)
        return [str(HCOM), "send", f"@{name}"] if name else None

    def agent_route(self, target: Target, sender: AgentName) -> AgentRoute | None:
        name = instance_name(target)
        if not name:
            return None
        return AgentRoute("name", name, (name,), command=["hcom", "send", f"@{name}"])
