import json
import tomllib
from pathlib import Path

import pytest

from agentcomms import isolation, profiles
from agentcomms.profiles import Binary
from agentcomms.records import tildify


def test_claude_argv_preassigns_session_and_runs_under_sops_exec():
    b = Binary("claude", Path("/v/2.1.310"), "2.1.310")
    argv = profiles.launch_argv(profiles.tui_argv(b, "auto", Path("/w"), "sid"), Path("/ac/bin/sops-exec"))
    assert argv == ["/ac/bin/sops-exec", "/v/2.1.310", "--session-id", "sid", "--model", "haiku",
                    "--permission-mode", "bypassPermissions"]
    assert profiles.tui_argv(b, "prompting", Path("/w"), "sid")[-1] == "default"
    assert profiles.resume_argv(b, "auto", Path("/w"), "sid")[1:3] == ["--resume", "sid"]


def test_codex_argv_is_embedded_with_explicit_workdir():
    b = Binary("codex", Path("/c/codex"), "0.164.0")
    assert profiles.tui_argv(b, "auto", Path("/w"), None) == [
        "/c/codex", "--no-daemon", "-C", "/w", "-m", "gpt-6-luna", "--dangerously-bypass-approvals-and-sandbox"]
    assert profiles.tui_argv(b, "prompting", Path("/w"), None)[-4:] == [
        "-a", "on-request", "-s", "read-only"]
    assert profiles.resume_argv(b, "auto", Path("/w"), "tid")[1:3] == ["resume", "tid"]


def test_version_parsers():
    assert profiles.parse_version("codex-cli 0.164.0\n") == "0.164.0"
    assert profiles.parse_daemon_version('{"cliVersion":"0.163.0","appServerVersion":"0.164.0"}') == "0.164.0"
    assert profiles.versions_for(Binary("codex", Path("/c"), "0.164.0"), "0.164.0") == {
        "codex": "0.164.0", "codex_daemon": "0.164.0"}


def test_claude_resolution_pins_versions_dir_and_reports_the_binary_version(tmp_path):
    versions = tmp_path / "versions"
    fake_binary(versions / "2.1.310", "2.1.310 (Claude Code)")
    link = tmp_path / "claude"
    link.symlink_to(versions / "2.1.310")
    assert profiles.resolve_claude(link, versions, tmp_path / "scratch") == Binary(
        "claude", (versions / "2.1.310").resolve(), "2.1.310")


def test_codex_home_has_trusted_config_and_auth_symlink(tmp_path):
    user_auth = tmp_path / "user-codex" / "auth.json"
    user_auth.parent.mkdir()
    user_auth.write_text("{}")
    work = tmp_path / "runs" / "r1" / "work" / "codex"
    work.mkdir(parents=True)
    iso = isolation.build_codex_home(tmp_path / "runs" / "r1" / "home" / "codex", work, tmp_path / "runs",
                                     "gpt-6-luna", "low", {"PATH": "/bin", "SECRET": "x"}, user_auth)
    config = tomllib.loads((iso.home / "config.toml").read_text())
    assert config["model"] == "gpt-6-luna"
    assert config["projects"][str(work.resolve())]["trust_level"] == "trusted"
    assert config["projects"][str((tmp_path / "runs").resolve())]["trust_level"] == "trusted"
    assert isolation.auth_link_intact(iso.home, user_auth)
    assert iso.env == {"PATH": "/bin", "TERM": "tmux-256color", "DISABLE_AUTOUPDATER": "1",
                       "AGENT_REQUIRE_SECRETS": "1", "CODEX_HOME": str(iso.home)}


def test_auth_link_check_detects_replaced_file(tmp_path):
    user_auth = tmp_path / "auth.json"
    user_auth.write_text("{}")
    home = tmp_path / "home"
    home.mkdir()
    (home / "auth.json").write_text("{}")
    assert isolation.auth_link_intact(home, user_auth) is False


def test_claude_home_pretrusts_work_dir(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    iso = isolation.build_claude_home(tmp_path / "home", work, "2.1.310", {"HOME": "/Users/me"})
    config = json.loads((iso.home / ".claude.json").read_text())
    assert config["projects"][str(work.resolve())]["hasTrustDialogAccepted"] is True
    assert config["hasCompletedOnboarding"] is True
    assert iso.env["CLAUDE_CONFIG_DIR"] == str(iso.home)


def test_global_config_hashes_cover_listed_files(tmp_path):
    present = tmp_path / "a.json"
    present.write_text("x")
    hashes = isolation.global_config_hashes((str(present), str(tmp_path / "missing.json")))
    assert hashes == {str(present): "2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881",
                      str(tmp_path / "missing.json"): None}


def test_non_churning_config_change_is_always_ours():
    before = {"~/.codex/config.toml": "b", "~/.factory/settings.json": "c"}
    after = {"~/.codex/config.toml": "b2", "~/.factory/settings.json": "c"}
    texts = {"~/.codex/config.toml": '[notice]\nx = 1'}
    assert isolation.attribute_changes(before, after, {}, texts, "/repo/runs") == (["~/.codex/config.toml"], [])


def test_claude_json_churn_is_not_ours_but_new_harness_project_is():
    before, after = {"~/.claude.json": "a"}, {"~/.claude.json": "a2"}
    old = '{"numStartups": 1, "projects": {"/repo/runs/old": {}}}'
    churn = '{"numStartups": 2, "projects": {"/repo/runs/old": {}}}'
    leak = '{"numStartups": 2, "projects": {"/repo/runs/old": {}, "/repo/runs/new": {}}}'
    t = "~/.claude.json"
    assert isolation.attribute_changes(before, after, {t: old}, {t: churn}, "/repo/runs") == ([], [t])
    assert isolation.attribute_changes(before, after, {t: old}, {t: leak}, "/repo/runs") == ([t], [])


PI_CLI = Path("/m/1.4.0/node_modules/.mise/@p@1.4.0/node_modules/@earendil-works/pi-coding-agent/dist/cli.js")


def test_pi_argv_runs_pinned_node_with_isolated_home_and_session():
    b = Binary("pi", PI_CLI, "1.4.0", "pi", Path("/n/24.22.0/bin/node"), "24.22.0")
    argv = profiles.tui_argv(b, "auto", Path("/w"), "sid", home=Path("/h"))
    node_path = "NODE_PATH=/m/1.4.0/node_modules:/m/1.4.0/node_modules/.mise/node_modules"
    assert argv == ["/usr/bin/env", "HOME=/h", node_path, "/n/24.22.0/bin/node", str(PI_CLI), "--session-dir",
                    "/h/sessions", "--model", "openrouter/deepseek/deepseek-v4.1-flash", "--thinking", "off",
                    "--session-id", "sid"]
    assert profiles.resume_argv(b, "auto", Path("/w"), "sid", home=Path("/h"))[-2:] == ["--session", "sid"]


def test_pi_versions_record_node_runtime():
    b = Binary("pi", PI_CLI, "1.4.0", "pi", Path("/n/24.22.0/bin/node"), "24.22.0")
    assert profiles.versions_for(b, None) == {"pi": "1.4.0", "node": "24.22.0"}


def test_opencode_argv_is_standalone_with_session_and_directory():
    b = Binary("opencode", Path("/o/opencode"), "2.1.4")
    assert profiles.tui_argv(b, "auto", Path("/w"), "ses_x") == [
        "/o/opencode", "--standalone", "--auto", "--session", "ses_x", "/w"]
    assert profiles.tui_argv(b, "prompting", Path("/w"), "ses_x") == [
        "/o/opencode", "--standalone", "--session", "ses_x", "/w"]
    assert profiles.resume_argv(b, "auto", Path("/w"), "ses_x") == [
        "/o/opencode", "--standalone", "--auto", "--session", "ses_x", "/w"]


def test_droid_argv_sets_cwd_and_autonomy():
    b = Binary("droid", Path("/d/droid"), "0.249.0")
    assert profiles.tui_argv(b, "auto", Path("/w"), None) == ["/d/droid", "--cwd", "/w", "--auto", "high"]
    assert profiles.resume_argv(b, "prompting", Path("/w"), "sid") == ["/d/droid", "--resume", "sid", "--cwd", "/w"]


def test_node_resolution_follows_version_alias(tmp_path):
    real = tmp_path / "node" / "24.22.0" / "bin"
    real.mkdir(parents=True)
    (real / "node").write_text("#!/bin/sh\necho v24.22.0\n")
    (real / "node").chmod(0o755)
    (tmp_path / "node" / "24").symlink_to(tmp_path / "node" / "24.22.0")
    assert profiles.resolve_node(str(tmp_path / "node" / "24" / "bin")) == ((real / "node").resolve(), "24.22.0")


def test_opencode_session_id_is_descending_and_prefixed():
    first = profiles.opencode_session_id(1792850100000, bytes(14))
    later = profiles.opencode_session_id(1792850200000, bytes(14))
    assert first.startswith("ses_") and len(first) == 30
    assert later < first


def test_agent_process_matches_binary_path_or_title():
    from agentcomms.procs import ProcRow, find_agent_pid
    rows = [ProcRow(10, 1, 10, "sops exec-env x /m/pi --model m"), ProcRow(11, 10, 10, "pi"),
            ProcRow(12, 11, 10, "/bin/zsh -c ls")]
    assert find_agent_pid(rows, 10, "/m/pi", "pi") == 11


def test_pi_home_settings_pin_model_and_skip_packages(tmp_path):
    iso = isolation.build_pi_home(tmp_path / "pi", "openrouter/deepseek/deepseek-v4.1-flash", "off", "1.4.0",
                                  {"PATH": "/bin"})
    settings = json.loads((iso.home / "settings.json").read_text())
    assert (settings["defaultProvider"], settings["defaultModel"]) == ("openrouter", "deepseek/deepseek-v4.1-flash")
    assert settings["packages"] == [] and settings["extensions"] == []
    assert iso.env["PI_CODING_AGENT_DIR"] == str(iso.home)
    assert (iso.home / "sessions").is_dir()


def test_opencode_home_uses_isolated_xdg_dirs_and_auth_symlink(tmp_path):
    user_auth = tmp_path / "user" / "auth.json"
    user_auth.parent.mkdir()
    user_auth.write_text("{}")
    home = tmp_path / "home"
    iso = isolation.build_opencode_home(home, "opencode-go/gpt-6-luna", {"PATH": "/bin"}, user_auth)
    assert {k: iso.env[k] for k in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME",
                                    "TMPDIR", "OPENCODE_TEST_HOME")} == {
        "XDG_CONFIG_HOME": str(home / "config"), "XDG_DATA_HOME": str(home / "data"),
        "XDG_STATE_HOME": str(home / "state"), "XDG_CACHE_HOME": str(home / "cache"),
        "TMPDIR": str(home / "tmp"), "OPENCODE_TEST_HOME": str(home)}
    assert iso.env["OPENCODE_DISABLE_AUTOUPDATE"] == "1"
    config = json.loads((home / "config" / "opencode" / "opencode.json").read_text())
    assert (config["model"], config["update"]) == ("opencode-go/gpt-6-luna", "disable")
    assert isolation.link_intact(isolation.opencode_auth_link(home), user_auth)


def test_opencode_prompting_home_asks_before_edits_and_shell_commands(tmp_path):
    user_auth = tmp_path / "auth.json"
    user_auth.write_text("{}")
    work = tmp_path / "runs" / "r1" / "work" / "opencode"
    isolation.build_home("opencode", tmp_path / "home", work, tmp_path / "runs", "2.2.0", "m", "", "prompting", {}, 0.0)
    config = json.loads((tmp_path / "home" / "config" / "opencode" / "opencode.json").read_text())
    assert config["permission"] == {"edit": "ask", "bash": "ask"}


def test_opencode_auto_config_sets_no_permission_key():
    assert "permission" not in isolation.opencode_config("m", "auto")


def test_opencode_intact_auth_link_reports_no_problem(tmp_path, monkeypatch):
    user_auth = tmp_path / "user" / "auth.json"
    user_auth.parent.mkdir()
    user_auth.write_text("{}")
    monkeypatch.setattr(isolation, "OPENCODE_USER_AUTH", user_auth)
    isolation.build_opencode_home(tmp_path / "home", "m", {}, user_auth)
    assert isolation.auth_link_problems("opencode", tmp_path / "home") == []


def test_opencode_auth_link_problem_reported_when_replaced(tmp_path):
    link = isolation.opencode_auth_link(tmp_path)
    link.parent.mkdir(parents=True)
    link.write_text("{}")
    assert isolation.auth_link_problems("opencode", tmp_path) == [
        f"opencode {link} is no longer a symlink to {isolation.OPENCODE_USER_AUTH}"]


def test_droid_home_pretrusts_work_dir_and_repo_root(tmp_path):
    (tmp_path / ".git").mkdir()
    work = tmp_path / "runs" / "r1" / "work" / "droid"
    work.mkdir(parents=True)
    iso = isolation.build_droid_home(tmp_path / "home", work, "gpt-6-luna", "low", "auto", {"PATH": "/bin"},
                                     1792850100.0)
    settings = json.loads((iso.home / ".factory" / "settings.json").read_text())
    assert settings["trustedFolders"] == {str(work.resolve()): {"trustedAt": "2026-10-24T13:55:00.000Z"},
                                          str(tmp_path.resolve()): {"trustedAt": "2026-10-24T13:55:00.000Z"}}
    assert settings["sessionDefaultSettings"]["model"] == "gpt-6-luna"
    assert iso.env["FACTORY_HOME_OVERRIDE"] == str(iso.home)
    assert iso.env["FACTORY_DROID_AUTO_UPDATE_ENABLED"] == "false"


def test_droid_settings_set_high_autonomy_in_auto_mode_and_off_in_prompting_mode():
    auto = isolation.droid_settings([Path("/w")], "gpt-6-luna", "low", "auto", "t")
    prompting = isolation.droid_settings([Path("/w")], "gpt-6-luna", "low", "prompting", "t")
    assert auto["sessionDefaultSettings"] == {"model": "gpt-6-luna", "reasoningEffort": "low", "autonomyLevel": "high"}
    assert prompting["sessionDefaultSettings"] == {"model": "gpt-6-luna", "reasoningEffort": "low",
                                                   "autonomyLevel": "off"}


def test_build_home_threads_mode_into_droid_settings(tmp_path):
    work = tmp_path / "work"
    iso = isolation.build_home("droid", tmp_path / "home", work, tmp_path, "0.249.0", "gpt-6-luna", "low",
                               "prompting", {"PATH": "/usr/bin:/bin"}, 0.0)
    settings = json.loads((iso.home / ".factory" / "settings.json").read_text())
    assert settings["sessionDefaultSettings"]["autonomyLevel"] == "off"


def test_probe_env_points_every_isolated_dir_under_throwaway_home(tmp_path):
    for agent in ("opencode", "droid"):
        env = profiles.probe_env(agent, tmp_path)
        launch = isolation.PROBE_ENV[agent](tmp_path)
        assert env.items() >= launch.items()
        dirs = {k: v for k, v in env.items() if k != "PATH" and v.startswith("/")}
        assert all(Path(v).is_relative_to(tmp_path) for v in dirs.values())
        assert "HOME" in dirs
    assert profiles.probe_env("opencode", tmp_path)["OPENCODE_DISABLE_AUTOUPDATE"] == "1"
    assert set(profiles.probe_env("opencode", tmp_path)) >= {
        "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "TMPDIR", "OPENCODE_TEST_HOME"}
    droid = profiles.probe_env("droid", tmp_path)
    assert (droid["FACTORY_DROID_AUTO_UPDATE_ENABLED"], droid["FACTORY_DISABLE_KEYRING"]) == ("false", "1")


def test_version_probe_runs_binary_with_probe_env(tmp_path):
    dump = tmp_path / "env.json"
    fake = tmp_path / "fake-opencode"
    fake.write_text(f"#!/bin/sh\n/usr/bin/env > {dump}\necho 2.1.4\n")
    fake.chmod(0o755)
    scratch = tmp_path / "runs"
    assert profiles.resolve_opencode(scratch, fake) == Binary("opencode", fake.resolve(), "2.1.4")
    env = dict(line.split("=", 1) for line in dump.read_text().splitlines())
    probe_home = Path(env["HOME"])
    assert probe_home.parent == scratch and probe_home.name.startswith(".version-")
    assert {k: env[k] for k in isolation.opencode_env(probe_home)} == isolation.opencode_env(probe_home)


def test_user_state_change_detection_lists_modified_files():
    before = {"/u/.factory/a": 1.0, "/u/.factory/b": 2.0}
    after = {"/u/.factory/a": 1.0, "/u/.factory/b": 3.0, "/u/.factory/c": 4.0}
    assert isolation.changed_paths(before, after) == ["/u/.factory/b", "/u/.factory/c"]


def test_user_state_note_uses_tilde_paths_and_caps_list():
    touched = [f"/Users/me/.factory/f{i}" for i in range(7)]
    assert isolation.user_state_note("droid", touched, "/Users/me", shown=2) == (
        "note: droid user state changed during run, likely by live user sessions (7 files): "
        "~/.factory/f0, ~/.factory/f1 (+5 more)")


def test_tildify_rewrites_home_paths_and_slugs():
    text = "transcript=runs/x/sessions/-Users-me-wrksp-a-runs-x-work-droid/1.jsonl; /Users/me/.local/auth.json"
    assert tildify(text, "/Users/me") == (
        "transcript=runs/x/sessions/~-wrksp-a-runs-x-work-droid/1.jsonl; ~/.local/auth.json")


def test_claude_settings_exclude_every_ancestor_instruction_file(tmp_path):
    user_home = tmp_path / "me"
    work = user_home / "repo" / "runs" / "r1" / "work" / "claude"
    work.mkdir(parents=True)
    iso = isolation.build_claude_home(tmp_path / "home", work, "2.1.310", {"HOME": str(user_home)})
    excludes = json.loads((iso.home / "settings.json").read_text())["claudeMdExcludes"]
    assert str(user_home.resolve() / ".claude" / "CLAUDE.md") in excludes
    assert str(user_home.resolve() / "repo" / "CLAUDE.md") in excludes
    assert str(user_home.resolve() / "repo" / "runs" / "r1" / "work" / ".claude" / "rules" / "**") in excludes
    assert all(not e.startswith(f"{work.resolve()}/") for e in excludes)


def test_claude_excludes_add_the_resolved_path_of_a_linked_instruction_file(tmp_path):
    real = tmp_path / "dotfiles"
    real.mkdir()
    (real / "CLAUDE.md").write_text("x")
    (tmp_path / "me").mkdir()
    (tmp_path / "me" / ".claude").symlink_to(real)
    paths = isolation.claude_md_excludes(tmp_path / "me" / "w", tmp_path / "me")
    assert isolation.resolved_links(paths) == [str((real / "CLAUDE.md").resolve())]


def test_receiver_work_dir_is_its_own_git_root_and_droid_trusts_it(tmp_path):
    (tmp_path / ".git").mkdir()
    work = tmp_path / "runs" / "r1" / "work" / "droid"
    iso = isolation.build_home("droid", tmp_path / "home", work, tmp_path / "runs", "0.249.0", "gpt-6-luna", "low",
                               "auto", {"PATH": "/usr/bin:/bin"}, 1792850100.0)
    assert (work / ".git" / "HEAD").is_file()
    assert isolation.git_root(work) == work
    settings = json.loads((iso.home / ".factory" / "settings.json").read_text())
    assert list(settings["trustedFolders"]) == [str(work.resolve())]


def test_work_repo_init_ignores_a_hostile_git_dir(tmp_path):
    import subprocess
    sentinel = tmp_path / "sentinel"
    subprocess.run(["git", "init", "-q", str(sentinel)], check=True)
    before = sorted(p.name for p in (sentinel / ".git").iterdir())
    work = tmp_path / "runs" / "r1" / "work" / "codex"
    work.mkdir(parents=True)
    isolation.init_work_repo(work, {"PATH": "/usr/bin:/bin", "GIT_DIR": str(sentinel / ".git"),
                                    "GIT_WORK_TREE": str(sentinel)})
    assert (work / ".git" / "HEAD").is_file()
    assert sorted(p.name for p in (sentinel / ".git").iterdir()) == before


def fake_codex(releases: Path, name: str, version: str) -> Path:
    binary = releases / name / "bin" / "codex"
    binary.parent.mkdir(parents=True)
    binary.write_text(f"#!/bin/sh\necho 'codex-cli {version}'\n")
    binary.chmod(0o755)
    return binary


def test_codex_resolution_pins_release_dir_through_current(tmp_path):
    releases = tmp_path / "standalone" / "releases"
    binary = fake_codex(releases, "0.164.0-aarch64-apple-darwin", "0.164.0")
    (tmp_path / "standalone" / "current").symlink_to(releases / "0.164.0-aarch64-apple-darwin")
    link = tmp_path / "codex"
    link.symlink_to(tmp_path / "standalone" / "current" / "bin" / "codex")
    assert profiles.resolve_codex(link, releases) == Binary("codex", binary.resolve(), "0.164.0")


def test_codex_resolution_refuses_a_binary_outside_release_dirs(tmp_path):
    releases = tmp_path / "standalone" / "releases"
    releases.mkdir(parents=True)
    other = tmp_path / "elsewhere" / "bin" / "codex"
    other.parent.mkdir(parents=True)
    other.write_text("#!/bin/sh\necho 'codex-cli 0.164.0'\n")
    other.chmod(0o755)
    link = tmp_path / "codex"
    link.symlink_to(other)
    with pytest.raises(profiles.ProfileError, match="release dir"):
        profiles.resolve_codex(link, releases)


def test_codex_resolution_refuses_a_release_dir_with_another_version(tmp_path):
    releases = tmp_path / "standalone" / "releases"
    fake_codex(releases, "0.163.0-aarch64-apple-darwin", "0.164.0")
    link = tmp_path / "codex"
    link.symlink_to(releases / "0.163.0-aarch64-apple-darwin" / "bin" / "codex")
    with pytest.raises(profiles.ProfileError, match=r"reports codex 0\.164\.0"):
        profiles.resolve_codex(link, releases)


def fake_pi_package(concrete: Path, version: str) -> Path:
    package = concrete / profiles.PI_PACKAGE
    (package / "dist").mkdir(parents=True)
    (package / "dist" / "cli.js").write_text("")
    (package / "package.json").write_text(f'{{"version": "{version}", "bin": {{"pi": "dist/cli.js"}}}}')
    return package


def test_pi_resolves_from_its_pinned_package_copy(tmp_path, monkeypatch):
    package = fake_pi_package(tmp_path / "agents" / "pi-1.4.0", "1.4.0")
    node = fake_binary(tmp_path / "node", "1.4.0")
    monkeypatch.setattr(profiles, "resolve_node", lambda search_path: (node, "24.22.0"))
    assert profiles.resolve("pi", tmp_path, "/n/bin", tmp_path / "agents") == Binary(
        "pi", (package / "dist" / "cli.js").resolve(), "1.4.0", "pi", node, "24.22.0")


def fake_binary(path: Path, output: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\necho '{output}'\n")
    path.chmod(0o755)
    return path


def test_each_agent_resolves_to_its_pinned_copy(tmp_path):
    agents = tmp_path / "agents"
    claude = fake_binary(agents / "claude-2.1.312" / "2.1.312", "2.1.312 (Claude Code)")
    codex = fake_binary(agents / "codex-0.165.0" / "0.165.0-aarch64-apple-darwin" / "bin" / "codex",
                        "codex-cli 0.165.0")
    opencode = fake_binary(agents / "opencode-2.2.0" / "opencode", "2.2.0")
    droid = fake_binary(agents / "droid-0.251.0" / "droid", "0.251.0")
    resolved = {a: profiles.resolve(a, tmp_path / "runs", "/bin", agents)
                for a in ("claude", "codex", "opencode", "droid")}
    assert resolved == {"claude": Binary("claude", claude.resolve(), "2.1.312"),
                        "codex": Binary("codex", codex.resolve(), "0.165.0"),
                        "opencode": Binary("opencode", opencode.resolve(), "2.2.0"),
                        "droid": Binary("droid", droid.resolve(), "0.251.0")}


@pytest.mark.parametrize("agent,reported", [("droid", "0.252.0"), ("opencode", "2.2.1"), ("codex", "codex-cli 0.166.0"),
                                            ("claude", "2.1.313 (Claude Code)")])
def test_a_pinned_copy_reporting_another_version_is_refused(tmp_path, agent, reported):
    agents = tmp_path / "agents"
    paths = {"droid": agents / "droid-0.251.0" / "droid", "opencode": agents / "opencode-2.2.0" / "opencode",
             "codex": agents / "codex-0.165.0" / "0.165.0-aarch64-apple-darwin" / "bin" / "codex",
             "claude": agents / "claude-2.1.312" / "2.1.312"}
    fake_binary(paths[agent], reported)
    expected = {"droid": "0.251.0", "opencode": "2.2.0", "codex": "0.165.0", "claude": "2.1.312"}[agent]
    with pytest.raises(profiles.ProfileError, match=expected.replace(".", r"\.")):
        profiles.resolve(agent, tmp_path / "runs", "/bin", agents)


def test_a_pinned_pi_that_reports_another_version_is_refused(tmp_path, monkeypatch):
    fake_pi_package(tmp_path / "agents" / "pi-1.4.0", "1.4.0")
    node = fake_binary(tmp_path / "node", "1.5.0")
    monkeypatch.setattr(profiles, "resolve_node", lambda search_path: (node, "24.22.0"))
    with pytest.raises(profiles.ProfileError, match=r"dir says 1\.4\.0 but the binary reports 1\.5\.0"):
        profiles.resolve("pi", tmp_path / "runs", "/n/bin", tmp_path / "agents")


def test_two_pinned_dirs_for_one_agent_are_refused(tmp_path):
    fake_binary(tmp_path / "agents" / "opencode-2.2.0" / "opencode", "2.2.0")
    fake_binary(tmp_path / "agents" / "opencode-2.2.1" / "opencode", "2.2.1")
    with pytest.raises(profiles.ProfileError, match="expected one pinned opencode dir"):
        profiles.pinned_path("opencode", tmp_path / "agents")


def test_backend_adapters_start_the_pinned_codex_and_opencode(tmp_path, monkeypatch):
    from agentcomms.adapters.codex_remote import codex_binary
    from agentcomms.adapters.opencode_server import opencode_binary
    agents = tmp_path / "agents"
    codex = fake_binary(agents / "codex-0.165.0" / "0.165.0-aarch64-apple-darwin" / "bin" / "codex",
                        "codex-cli 0.165.0")
    opencode = fake_binary(agents / "opencode-2.2.0" / "opencode", "2.2.0")
    monkeypatch.setattr(profiles, "PINNED_AGENTS", agents)
    assert (codex_binary(), opencode_binary()) == (str(codex), str(opencode))


def test_sw_vers_output_becomes_os_version_and_build():
    out = "ProductName:\t\tmacOS\nProductVersion:\t\t27.2\nBuildVersion:\t\t26B123\n"
    assert profiles.parse_sw_vers(out) == "27.2 (26B123)"
    assert profiles.versions_for(Binary("claude", Path("/c"), "2.1.311"), None, "27.2 (26B123)") == {
        "claude": "2.1.311", "os": "27.2 (26B123)"}
