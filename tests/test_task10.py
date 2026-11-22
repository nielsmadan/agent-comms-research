import json
from pathlib import Path

import pytest

from agentcomms import backends, isolation, sandbox, scale, userconfig
from agentcomms.model import LaunchMods
from agentcomms.userconfig import Integration, Inventory

HOME = Path("/Users/me")
NONO = "/opt/nono/bin/nono"


def test_launch_wrapper_puts_nono_between_sops_exec_and_the_pinned_binary():
    env = {"PATH": "/usr/bin:/bin", "HOME": str(HOME), "CLAUDE_CONFIG_DIR": "/r/home/claude"}
    wrapped = sandbox.wrap_launch("claude", ["/Users/me/ac/bin/sops-exec", "/v/claude", "--model", "haiku"], env,
                                  NONO, HOME)
    assert wrapped.argv[:7] == ["/Users/me/ac/bin/sops-exec", NONO, "run", "--silent", "--no-audit", "-p",
                                "claude-local"]
    assert wrapped.argv[7] == "--"
    assert wrapped.argv[-3:] == ["/v/claude", "--model", "haiku"]


def test_only_claude_and_opencode_launch_silent_like_the_users_launcher():
    assert "--silent" in sandbox.nono_run(NONO, "opencode")
    assert sandbox.nono_run(NONO, "codex") == [NONO, "run", "--no-audit", "-p", "codex-local", "--"]
    assert sandbox.nono_run(NONO, "droid")[-2:] == ["droid-local", "--"]


def test_launcher_env_matches_agent_sandboxed():
    env = sandbox.wrap_launch("pi", ["sops", "/v/node"], {"PATH": "/usr/bin"}, NONO, HOME).env
    assert env["PATH"] == "/Users/me/ac/bin/sandbox-shims:/Users/me/ac/bin:/usr/bin"
    assert env["AGENT_SANDBOX"] == "1"
    assert env["AGENT_SANDBOX_PROFILE"] == "pi-local"
    assert env["SSL_CERT_FILE"] == "/etc/ssl/cert.pem"
    assert env["DISABLE_AUTOUPDATER"] == "1"
    assert env["AGENT_HARNESS"] == "pi"


def test_isolated_xdg_dirs_are_hidden_from_nono_and_restored_for_the_agent():
    env = {"PATH": "/usr/bin", "XDG_CONFIG_HOME": "/r/home/opencode/config", "XDG_DATA_HOME": "/r/home/opencode/data",
           "OPENCODE_PASSWORD": "pw"}
    wrapped = sandbox.wrap_command("opencode", ["/v/opencode", "serve"], env, NONO, HOME)
    assert "XDG_CONFIG_HOME" not in wrapped.env
    assert wrapped.env["OPENCODE_PASSWORD"] == "pw"
    inner = wrapped.argv[wrapped.argv.index("--") + 1:]
    assert inner[0] == "/usr/bin/env"
    assert "XDG_CONFIG_HOME=/r/home/opencode/config" in inner
    assert "XDG_DATA_HOME=/r/home/opencode/data" in inner
    assert inner[inner.index("XDG_DATA_HOME=/r/home/opencode/data") + 1:] == ["/v/opencode", "serve"]
    assert inner[1:3] == ["-u", "NONO_NO_UPDATE_CHECK"]
    assert inner[3:5] == ["-u", "XDG_STATE_HOME"]


def test_a_sandboxed_backend_spec_starts_through_nono():
    spec = backends.BackendSpec("codex-app-server", ["/v/codex", "app-server", "--listen", "unix:///tmp/ac/r.sock"],
                                {"PATH": "/usr/bin", "CODEX_HOME": "/r/home/codex"}, "/r/work", None, "/r/b.log",
                                {"agent": "codex", "nono": NONO, "user_home": str(HOME)})
    argv, env = backends.spec_command(spec, spec.argv)
    assert argv[:5] == [NONO, "run", "--no-audit", "-p", "codex-local"]
    assert argv[-4:] == spec.argv
    assert env["CODEX_HOME"] == "/r/home/codex"
    plain = backends.BackendSpec("codex-app-server", spec.argv, spec.env, "/r/work", None, "/r/b.log")
    assert backends.spec_command(plain, plain.argv) == (plain.argv, plain.env)


def test_sender_output_hides_the_nono_banner():
    stderr = "\n  nono v0.80.0\n  Capabilities:\n   r+w  /Users/me/wrksp (dir)\n  Applying sandbox...\n"
    assert sandbox.sender_detail("queued followUp\n", stderr) == "queued followUp"
    assert sandbox.sender_detail("", stderr + "refused: not a run socket\n") == "refused: not a run socket"
    assert sandbox.sender_accepted(0, "sent\n")
    assert sandbox.sender_accepted(0, "refused: x") is False
    assert sandbox.sender_accepted(1, "sent") is False


def record(agent: str, delivery: str, latency: float | None, ack: str = "acked") -> dict:
    return {"agent": agent, "delivery": delivery, "latency_s": latency, "ack": ack}


def test_scale_aggregation_counts_deliveries_and_spreads_latency():
    records = [record("claude", "delivered", 0.02), record("claude", "delivered", 0.04),
               record("codex", "delivered", 0.5), record("codex", "lost", None, "none"),
               record("pi", "delivered", 0.01)]
    summary = scale.aggregate(records)
    assert summary["delivered"] == (4, 5)
    assert summary["acked"] == (4, 5)
    assert summary["latency"] == scale.Spread(4, 0.01, 0.03, 0.5)
    assert summary["per_agent"]["codex"]["delivered"] == (1, 2)
    assert summary["per_agent"]["codex"]["latency"] == scale.Spread(1, 0.5, 0.5, 0.5)
    assert summary["per_agent"]["pi"]["latency"].median == 0.01


def test_scale_receivers_are_numbered_per_agent_and_reps_do_not_collide():
    mix = scale.receivers()
    assert [r.label for r in mix] == ["claude#1", "claude#2", "codex#1", "codex#2", "pi#1", "pi#2", "opencode#1",
                                      "droid#1"]
    claude = [r for r in mix if r.agent == "claude"]
    reps = [scale.message_rep(r, n) for r in claude for n in range(1, scale.MESSAGES + 1)]
    assert reps == [1, 2, 3, 4, 5, 6]


def test_scale_load_is_summed_per_sample_and_per_receiver():
    owner = {10: "pi#1", 11: "pi#1", 20: "codex#1"}
    first = scale.parse_load("   10  10240  1.5\n   11  2048 0.5\n   20  20480  3.0\n   99 1 1\n", owner)
    second = scale.parse_load("10 20480 0.0\n20 10240 9.0\n", owner)
    summary = scale.load_summary([first, second])
    assert summary["samples"] == 2
    assert summary["processes_max"] == 3
    assert summary["total_rss_mb_peak"] == 32.0
    assert summary["total_cpu_pct_peak"] == 9.0
    assert summary["per_receiver_rss_mb_peak"] == {"codex#1": 20.0, "pi#1": 20.0}
    assert summary["per_receiver_cpu_pct_peak"] == {"codex#1": 9.0, "pi#1": 2.0}


def test_user_config_cells_skip_on_trust_before_anything_else():
    inv = Inventory("droid", (Integration("mcp", "jina", True, None),), "accepting writes settings.json")
    assert userconfig.skip_reason(inv, "tmux-paste") == "skipped: trust: accepting writes settings.json"


def test_user_config_cells_skip_an_outward_integration_without_a_per_launch_switch():
    inv = Inventory("codex", (Integration("notify", "Notifier", True, "-c notify=[]"),
                              Integration("mcp", "remote-mcp", True, None),
                              Integration("mcp", "other", True, None)))
    assert userconfig.skip_reason(inv, "codex-remote-start") == ("skipped: outward-facing integration remote-mcp, "
                                                                 "other")


def test_user_config_cells_run_when_every_outward_integration_can_be_switched_off():
    inv = Inventory("codex", (Integration("notify", "Notifier", True, "-c notify=[]"), Integration("hook", "fmt")),
                    None, {"codex-queue": "attaches to the user's live Codex daemon"})
    assert userconfig.skip_reason(inv, "codex-remote-start") is None
    assert userconfig.skip_reason(inv, "codex-queue") == "skipped: attaches to the user's live Codex daemon"


def test_inventory_classifies_known_outward_integrations():
    assert userconfig.classify("claude", "plugin", "telegram@claude-plugins-official").outward
    assert userconfig.classify("codex", "hook", "hooklinesinker").disable.startswith("XDG_STATE_HOME=")
    assert userconfig.classify("codex", "plugin", "computer-use@openai-bundled").disable == (
        '-c plugins."computer-use@openai-bundled".enabled=false')
    assert userconfig.classify("droid", "mcp", "jina").disable is None
    assert userconfig.classify("opencode", "mcp", "context7").disable is None
    assert userconfig.classify("pi", "extension", "pi-ringleader-finish.ts").outward
    assert userconfig.classify("codex", "plugin", "pdf@openai-primary-runtime").disable == (
        '-c plugins."pdf@openai-primary-runtime".enabled=false')
    assert userconfig.classify("codex", "app", "connector_x").outward
    assert userconfig.classify("codex", "app", "connector_x").disable is None
    assert userconfig.classify("claude", "plugin", "telegram@claude-plugins-official").disable is None


def test_codex_user_config_overlay_points_at_the_users_home_with_the_switches(tmp_path):
    inv = Inventory("codex", (Integration("notify", "Notifier", True, "-c notify=[]"),))
    mods = LaunchMods(host="tmux", backend="codex-app-server", extra_args=("--remote", "unix:///tmp/ac/r.sock"),
                      backend_argv=("/v/codex", "app-server", "--listen", "unix:///tmp/ac/r.sock"))
    ov = userconfig.overlay(inv, {"CODEX_HOME": "/r/home/codex"}, mods, tmp_path / "home", tmp_path / "work",
                            tmp_path / "r", HOME, "gpt-6-luna", "low")
    assert ov.env["CODEX_HOME"] == "/Users/me/.codex"
    assert ov.env["XDG_STATE_HOME"] == str(tmp_path / "r" / "xdg-state")
    assert ov.home == HOME / ".codex"
    assert ov.mods.backend_argv[:3] == ("/v/codex", "-c", "notify=[]")
    assert ov.mods.backend_argv[-3:] == ("app-server", "--listen", "unix:///tmp/ac/r.sock")
    assert ov.mods.extra_args[-2:] == ("--remote", "unix:///tmp/ac/r.sock")
    assert 'model="gpt-6-luna"' in ov.mods.extra_args
    assert f'projects={{"{tmp_path / "work"}"={{trust_level="trusted"}}}}' in ov.mods.extra_args


def test_user_config_backend_checks_allow_only_the_run_listen_socket(tmp_path):
    run_dir = tmp_path / "runs" / "20261028-170000-abcd"
    argv = ["/v/codex", "app-server", "--listen", f"unix:///tmp/ac/{run_dir.name}.sock"]
    spec = backends.BackendSpec("codex-app-server", argv, {"CODEX_HOME": str(HOME / ".codex")}, "/w", None, "/l",
                                None, True)
    assert backends.user_config_codex_problem(spec, run_dir, HOME / ".codex", HOME) is None
    daemon = backends.BackendSpec("codex-daemon", argv, spec.env, "/w", None, "/l", None, True)
    assert "never runs with the user's CODEX_HOME" in backends.user_config_codex_problem(daemon, run_dir,
                                                                                         HOME / ".codex", HOME)
    other = backends.BackendSpec("codex-app-server", [*argv[:3], "ws://0.0.0.0:9"], spec.env, "/w", None, "/l",
                                 None, True)
    assert "must listen on the run socket" in backends.user_config_codex_problem(other, run_dir, HOME / ".codex",
                                                                                 HOME)


def test_a_transcript_in_the_users_store_is_named_by_its_full_path(tmp_path):
    from types import SimpleNamespace

    from agentcomms.paths import Layout
    from agentcomms.scenarios.common import transcript_note
    cell = SimpleNamespace(engine=SimpleNamespace(layout=Layout(tmp_path / "repo")))
    outside = SimpleNamespace(path=tmp_path / "home" / ".codex" / "sessions" / "rollout-x.jsonl")
    inside = SimpleNamespace(path=tmp_path / "repo" / "runs" / "r" / "rollout-y.jsonl")
    assert transcript_note(cell, outside) == [f"transcript={outside.path}"]
    assert transcript_note(cell, inside) == ["transcript=runs/r/rollout-y.jsonl"]


def test_user_config_cells_skip_an_agent_that_writes_its_global_config_at_startup():
    inv = Inventory("pi", (), None, {}, "rewrote settings.json at startup")
    assert userconfig.skip_reason(inv, "pi-ext") == "skipped: writes global config: rewrote settings.json at startup"


def test_a_sops_exec_backend_keeps_sops_exec_outside_nono():
    spec = backends.BackendSpec("opencode-server", ["/Users/me/ac/bin/sops-exec", "/v/opencode", "serve"],
                                {"PATH": "/usr/bin"}, "/r/work", None, "/r/b.log",
                                {"agent": "opencode", "nono": NONO, "user_home": str(HOME)})
    argv, _ = backends.spec_command(spec, spec.argv)
    assert argv[:3] == ["/Users/me/ac/bin/sops-exec", NONO, "run"]
    assert argv[-2:] == ["/v/opencode", "serve"]


def test_the_agents_runtime_dir_is_hidden_from_nono_and_restored_inside():
    wrapped = sandbox.wrap_command("pi", ["/v/node"], {"PATH": "/usr/bin", "XDG_RUNTIME_DIR": "/tmp/ac/r-cl"}, NONO,
                                   HOME)
    assert "XDG_RUNTIME_DIR" not in wrapped.env
    assert "XDG_RUNTIME_DIR=/tmp/ac/r-cl" in wrapped.argv


def test_a_sandboxed_sender_falls_back_to_the_adapters_agent_route(tmp_path):
    from types import SimpleNamespace

    from agentcomms.adapters.bridge import AgentRoute

    class Adapter:
        name = "codex-remote-start"
        kind = "native"

        def sender_argv(self, target):
            return None

        def agent_route(self, target, agent):
            return AgentRoute("address", "thread t", ("t",), command=["python3", "-I", "send.py", "--thread", "t"])

    target = SimpleNamespace(work_dir=tmp_path)
    assert sandbox.route_command(Adapter(), target, "codex") == ["python3", "-I", "send.py", "--thread", "t"]
    adapter = Adapter()
    adapter.agent_route = lambda target, agent: None
    assert sandbox.route_command(adapter, target, "codex") is None


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def fake_home(tmp_path: Path) -> tuple[Path, Path]:
    home, runs = tmp_path / "home", tmp_path / "repo" / "runs"
    runs.mkdir(parents=True)
    return home, runs


CODEX_TOML = """notify = ["/Applications/Notifier.app/Contents/client"]
[mcp_servers.context7]
command = "npx"
[plugins."browser@openai-bundled"]
enabled = true
[plugins."pdf@openai-primary-runtime"]
enabled = true
[plugins."retired@x"]
enabled = false
"""


def codex_home(tmp_path: Path, extra: str = "") -> tuple[Path, Path]:
    home, runs = fake_home(tmp_path)
    write(home / ".codex" / "config.toml", CODEX_TOML + extra)
    return home, runs


def test_codex_inventory_switches_every_outward_integration_with_a_c_override(tmp_path):
    home, runs = codex_home(tmp_path)
    inv = userconfig.codex_inventory(home, runs)
    assert {i.name: i.disable for i in inv.integrations if i.outward} == {
        "client": "-c notify=[]",
        "context7": "-c mcp_servers.context7.enabled=false",
        "browser@openai-bundled": '-c plugins."browser@openai-bundled".enabled=false',
        "pdf@openai-primary-runtime": '-c plugins."pdf@openai-primary-runtime".enabled=false'}
    assert userconfig.skip_reason(inv, "codex-remote-start") is None
    flags = userconfig.codex_overrides(inv, tmp_path / "w", "m", "low")
    pairs = [flags[i + 1] for i, f in enumerate(flags) if f == "-c"]
    assert {"notify=[]", "mcp_servers.context7.enabled=false", 'plugins."browser@openai-bundled".enabled=false',
            'plugins."pdf@openai-primary-runtime".enabled=false'} <= set(pairs)
    assert not any("retired@x" in p for p in pairs)


def test_codex_app_connectors_skip_the_cell_because_no_switch_is_verified(tmp_path):
    home, runs = codex_home(tmp_path, "[apps.connector_openai_codex_document_control]\n")
    inv = userconfig.codex_inventory(home, runs)
    assert userconfig.skip_reason(inv, "codex-remote-start") == (
        "skipped: outward-facing integration connector_openai_codex_document_control")


def test_both_codex_daemon_mechanisms_are_blocked(tmp_path):
    home, runs = codex_home(tmp_path)
    inv = userconfig.codex_inventory(home, runs)
    for mechanism in ("codex-queue", "codex-queue-embedded"):
        assert userconfig.skip_reason(inv, mechanism) == f"skipped: {userconfig.CODEX_DAEMON_BLOCK}"


def test_pi_cells_skip_because_pi_rewrites_the_users_config(tmp_path):
    home, runs = fake_home(tmp_path)
    write(home / ".pi" / "agent" / "trust.json", json.dumps({str(runs.resolve()): True}))
    write(home / ".pi" / "agent" / "extensions" / "pi-ringleader-finish.ts", "")
    inv = userconfig.pi_inventory(home, runs.resolve())
    assert inv.writes_problem == userconfig.PI_WRITES
    assert userconfig.skip_reason(inv, "pi-ext") == f"skipped: writes global config: {userconfig.PI_WRITES}"
    assert [i.disable for i in inv.integrations] == ["PATH=<run>/bin/user-config (no-op `rl`) first"]


def test_opencode_cells_skip_while_the_users_mcp_servers_cannot_be_switched_off(tmp_path):
    home, runs = fake_home(tmp_path)
    write(home / ".config" / "opencode" / "opencode.json", json.dumps({"mcp": {"context7": {}, "jina": {}}}))
    write(home / ".config" / "opencode" / "plugins" / "hooklinesinker-opencode.ts", "")
    inv = userconfig.opencode_inventory(home, runs.resolve())
    assert userconfig.skip_reason(inv, "opencode-server-queue") == (
        "skipped: outward-facing integration context7, jina")
    assert userconfig.skip_reason(inv, "opencode-service-steer").startswith("skipped: attaches to the user's")


def test_opencode_without_mcp_servers_runs_and_its_config_content_has_no_mcp_block(tmp_path):
    home, runs = fake_home(tmp_path)
    write(home / ".config" / "opencode" / "plugins" / "hooklinesinker-opencode.ts", "")
    inv = userconfig.opencode_inventory(home, runs.resolve())
    assert userconfig.skip_reason(inv, "opencode-server-queue") is None
    assert json.loads(userconfig.opencode_content(inv, "m")) == {"model": "m", "share": "disabled"}


def test_claude_and_droid_skip_for_lack_of_an_overlay_even_when_the_workspace_is_trusted(tmp_path):
    home, runs = fake_home(tmp_path)
    write(home / ".claude.json", json.dumps({"projects": {str(runs.resolve()): {"hasTrustDialogAccepted": True}}}))
    write(home / ".claude" / "settings.json", json.dumps({"enabledPlugins": {"telegram@claude-plugins-official":
                                                                            True}}))
    write(home / ".factory" / "settings.json", json.dumps({"trustedFolders": [str(runs.resolve())]}))
    claude = userconfig.claude_inventory(home, runs.resolve())
    droid = userconfig.droid_inventory(home, runs.resolve())
    assert claude.trust_problem is None and droid.trust_problem is None
    assert userconfig.skip_reason(claude, "claude-channel") == (
        "skipped: no user-config overlay for claude, so no integration switch is applied")
    assert userconfig.skip_reason(droid, "tmux-paste") == (
        "skipped: no user-config overlay for droid, so no integration switch is applied")
    with pytest.raises(ValueError, match="no user-config overlay for claude"):
        userconfig.overlay(claude, {}, LaunchMods(host="tmux"), tmp_path, tmp_path, tmp_path / "r", home, "m", "low")


def test_the_pi_overlay_redirects_state_and_puts_a_noop_rl_first(tmp_path):
    inv = Inventory("pi")
    env = {"PI_CODING_AGENT_DIR": "/r/home/pi", "PATH": "/usr/bin"}
    ov = userconfig.overlay(inv, env, LaunchMods(host="tmux"), tmp_path / "home", tmp_path / "w", tmp_path / "r", HOME,
                            "m", "low")
    assert "PI_CODING_AGENT_DIR" not in ov.env
    assert ov.env["XDG_STATE_HOME"] == str(tmp_path / "r" / "xdg-state")
    assert ov.env["CSD_WORKER_DIR"] == "/tmp/ac/r-csd"
    assert ov.mods.path_prepend == (str(tmp_path / "r" / "bin" / "user-config"),)
    assert (tmp_path / "r" / "bin" / "user-config" / "rl").read_text() == "#!/bin/sh\nexit 0\n"
    assert ov.argv_home == (f"HOME={tmp_path / 'home'}", f"HOME={HOME}")


def test_the_opencode_overlay_uses_the_user_config_dir_with_data_and_state_in_the_run(tmp_path):
    inv = Inventory("opencode")
    env = {"XDG_CONFIG_HOME": "/r/c", "OPENCODE_TEST_HOME": "/r/h", "XDG_DATA_HOME": "/r/d", "XDG_STATE_HOME": "/r/s"}
    ov = userconfig.overlay(inv, env, LaunchMods(host="tmux"), tmp_path / "home", tmp_path / "w", tmp_path / "r", HOME,
                            "m", "low")
    assert "XDG_CONFIG_HOME" not in ov.env and "OPENCODE_TEST_HOME" not in ov.env
    assert (ov.env["XDG_DATA_HOME"], ov.env["XDG_STATE_HOME"]) == ("/r/d", "/r/s")
    assert json.loads(ov.env["OPENCODE_CONFIG_CONTENT"]) == {"model": "m", "share": "disabled"}


class LaunchProbe:
    def __init__(self, tmp_path, monkeypatch, agent: str, home: Path):
        from agentcomms import engine as engine_mod
        from agentcomms import profiles
        from agentcomms.paths import Layout
        auth = {"codex": isolation.CODEX_USER_AUTH, "opencode": isolation.OPENCODE_USER_AUTH}.get(agent)
        if auth is not None and not auth.exists():
            pytest.skip(f"isolated {agent} home links the user's {auth}, which is absent")
        self.engine = engine_mod.Engine(Layout(tmp_path / "repo"), environ={"HOME": str(home), "PATH": "/usr/bin"},
                                        user_config=True)
        self.started: dict = {}
        binary = profiles.Binary(agent, Path(f"/m/node_modules/{agent}/cli.js"), "1.0.0", agent, Path("/n/node"), "24")
        monkeypatch.setattr(self.engine, "resolve", lambda _: binary)
        monkeypatch.setattr(profiles, "codex_daemon_version", lambda *a, **k: None)
        monkeypatch.setattr(self.engine, "start", self.capture)
        self.agent = agent

    def capture(self, m, launched, argv, *rest):
        self.started = {"argv": argv, "env": launched.env, "notes": launched.notes, "home": launched.home}
        return m, launched

    def launch(self) -> dict:
        m = self.engine.new_run()
        self.engine.launch(m, self.agent)
        return self.started


def test_engine_launch_with_user_config_builds_the_codex_switches_into_argv_and_env(tmp_path, monkeypatch):
    home, _ = codex_home(tmp_path)
    started = LaunchProbe(tmp_path, monkeypatch, "codex", home).launch()
    argv = started["argv"]
    flags = [argv[i + 1] for i, a in enumerate(argv) if a == "-c"]
    assert {"notify=[]", "mcp_servers.context7.enabled=false", 'plugins."browser@openai-bundled".enabled=false',
            'plugins."pdf@openai-primary-runtime".enabled=false', 'model="gpt-6-luna"'} <= set(flags)
    assert started["env"]["CODEX_HOME"] == str(home / ".codex")
    assert started["env"]["XDG_STATE_HOME"].endswith("/xdg-state")
    assert started["notes"] == ("user-config: disabled notify client, mcp context7, plugin browser@openai-bundled, "
                                "plugin pdf@openai-primary-runtime",)


def test_engine_launch_with_user_config_redirects_pi_state_and_keeps_the_users_home(tmp_path, monkeypatch):
    home, _ = fake_home(tmp_path)
    write(home / ".pi" / "agent" / "extensions" / "pi-ringleader-finish.ts", "")
    started = LaunchProbe(tmp_path, monkeypatch, "pi", home).launch()
    env = started["env"]
    assert env["XDG_STATE_HOME"].endswith("/xdg-state")
    assert "PI_CODING_AGENT_DIR" not in env
    assert env["PATH"].startswith(str(Path(env["XDG_STATE_HOME"]).parent / "bin" / "user-config") + ":")
    assert f"HOME={home}" in started["argv"]


def test_engine_launch_with_user_config_leaves_opencode_state_in_the_run(tmp_path, monkeypatch):
    home, _ = fake_home(tmp_path)
    write(home / ".config" / "opencode" / "plugins" / "hooklinesinker-opencode.ts", "")
    started = LaunchProbe(tmp_path, monkeypatch, "opencode", home).launch()
    env = started["env"]
    assert "XDG_CONFIG_HOME" not in env
    assert env["XDG_STATE_HOME"].startswith(str(tmp_path / "repo" / "runs"))
    assert json.loads(env["OPENCODE_CONFIG_CONTENT"])["share"] == "disabled"


def test_a_sandboxed_launch_without_sops_exec_wraps_the_bare_binary_instead_of_eating_it(tmp_path):
    from agentcomms import engine as engine_mod
    from agentcomms.paths import Layout
    eng = engine_mod.Engine(Layout(tmp_path), environ={"HOME": str(HOME)}, sandbox="nono")
    eng.nono = NONO
    bare, _ = eng.sandboxed("claude", ["/v/claude", "--model", "haiku"], {"PATH": "/usr/bin"}, "r")
    assert bare[0] == NONO and bare[-3:] == ["/v/claude", "--model", "haiku"]
    sops, _ = eng.sandboxed("claude", ["/Users/me/ac/bin/sops-exec", "/v/claude"], {"PATH": "/usr/bin"}, "r")
    assert sops[:2] == ["/Users/me/ac/bin/sops-exec", NONO]


def test_a_preflight_for_some_agents_keeps_the_other_agents_rows():
    from agentcomms.nono_preflight import Check, render
    previous = render([Check("claude", "ps", True, "old"), Check("pi", "ps", False, "old"),
                       Check("droid", "ps", True, "old")], "0.80.0", "then")
    text = render([Check("pi", "ps", True, "new")], "0.80.0", "now", previous)
    assert [line for line in text.splitlines() if line.startswith("| ") and "---" not in line][1:] == [
        "| claude | ps | yes | old |", "| pi | ps | yes | new |", "| droid | ps | yes | old |"]
