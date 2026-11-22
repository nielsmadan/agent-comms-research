# Vendored third-party code review

Third-party code runs only from `vendor/<name>/`. Only this file and each package's `package.json` and
`package-lock.json` are committed. `node_modules/`, the downloaded tarballs (`vendor/_review/`) and the npm cache
(`vendor/.npm-cache/`) are gitignored.

Reinstall exactly what was reviewed:

```sh
export npm_config_cache="$PWD/vendor/.npm-cache"
npm ci --prefix vendor/pi-session-bridge --ignore-scripts --legacy-peer-deps
npm ci --prefix vendor/pi-claude-link --ignore-scripts --legacy-peer-deps
npm ci --prefix vendor/typescript --ignore-scripts
```

`--ignore-scripts` is required. `pi-session-bridge` has a `postinstall` that writes into the user's
`~/.pi/agent/APPEND_SYSTEM.md` (see below). `--legacy-peer-deps` stops npm from installing the peer
`@earendil-works/pi-coding-agent` and `typebox` into `vendor/`. Pi gives extensions both as virtual modules
(`dist/core/extensions/virtual-modules.js` in Pi 1.4.0), so neither package has a runtime dependency to install.

Both were installed on 2026-10-27 with `npm install --prefix vendor/<name> --ignore-scripts --legacy-peer-deps
--save-exact <pkg>@<version>`. `diff -r` of each installed tree against its reviewed tarball came back empty.
After install, `~/.pi/agent/APPEND_SYSTEM.md` did not exist. The first download (`npm pack`, before the cache was
redirected) went through the user's npm cache (`~/.npm/_cacache`, `~/.npm/_logs`). Every later npm command used
`vendor/.npm-cache`.

## @vanillagreen/pi-session-bridge 3.0.1

- Source: npm `@vanillagreen/pi-session-bridge@3.0.1` (repo `vanillagreencom/kendex`, `pi-extensions/pi-session-bridge`).
- Tarball sha256 `335ed4f39b661336c7696ca3fad627f45f92134e4f14479a372a82e5b63d06fe`; npm integrity
  `sha512-XlO+G/QsRow4toLaIfftrhlW+hxHtp80oWRFmAKsp8hR26Z1Z21vuHGs8jsLlRMp/ndXGK/juv6kBM5KTOlryg==`.
- Read in full: `package.json`, `scripts/append-system.mjs`, `extensions/session-bridge.ts`, `bin/pi-bridge.js`
  (argument parsing, discovery, request path), `instructions.md`, `README.md`. Grepped for filesystem, process,
  network and env access: `extensions/{package-config,event-history,activity-broker,child-session-id,
  event-sanitizer,diagnostics}.ts`. Tests and assets were not read.
- Install hooks: `postinstall: node scripts/append-system.mjs install` and `preuninstall: … remove`. The script
  walks up from the package dir looking for a `packages/` or `npm/node_modules/` install root. Under
  `vendor/pi-session-bridge/node_modules/` it finds neither, so it falls back to `PI_CODING_AGENT_DIR` or
  `~/.pi/agent` (when that dir exists) and upserts a marked block into `APPEND_SYSTEM.md` there. On this machine
  that would be the user's global Pi config, so the hook must never run.
- Runtime filesystem: everything lives under the bridge dir. That is `PI_BRIDGE_DIR`, else the `bridgeDir`
  setting, else `os.tmpdir()/pi-session-bridge-<uid>`. It holds `pi-<pid>.sock`, `instances/<pid>.json` (state
  heartbeat every 15 s) and `raw/<pid>.jsonl` (event spill). The harness sets `PI_BRIDGE_DIR=/tmp/ac/<run_id>-pb`,
  and `cleanup` removes that dir. Settings are read (never written) from `PI_CODING_AGENT_DIR/settings.json` (the
  isolated Pi home) and from `<work dir>/.pi/settings.json`, walking up to the work dir's own git root.
- Process/network: there is no network code. A message that starts with `/`, and is not a skill or prompt
  template, is pasted into the session's own tmux pane: `tmux list-panes -a`, a `ps` ancestry walk, then
  `load-buffer`/`paste-buffer`, with a temp file under `os.tmpdir()`. Harness envelopes never start with `/`, so this
  path does not run. Inside the harness it would only reach the `-L agentcomms` server named by the pane's `TMUX`.
- Protocol (`pi-session-bridge.v1`): JSON lines over the socket. The server sends `bridge_hello` first. Requests
  `prompt`/`send` (deliver now when idle, `steer` when busy), `steer`, `follow_up`, `abort`, `shutdown`
  (`confirm: true`), `history`, `get_state`, `subscribe`, `answer`/`reject`. Each gets a `response` with the same
  `id`. Delivery calls `pi.sendUserMessage`, so the message is an ordinary user message in the transcript.

## pi-claude-link 0.1.0

- Source: npm `pi-claude-link@0.1.0` (repo `alonw0/pi-claude-link`, published 2026-08-08).
- Tarball sha256 `88bccc68f42eb74d396af5b34c5bc87c61cc899c2612a139f2a273c74ebc4f5b`; npm integrity
  `sha512-NHNGnS+3APkd83fkWJtABOyjltsHV9z4ZweSdmdS09lJPOCjM/eQ5zUr3RYlDXDVCP6cWM57x7As5kv+r2omfA==`.
- Read in full: `package.json`, `index.ts`, `claude-protocol.ts`, `SECURITY.md`. No install scripts.
- Peer discovery (the safety question): the registry is `path.join(os.homedir(), ".claude", "sessions")`, a
  constant set at import. It does not use `CLAUDE_CONFIG_DIR`. `listClaudeSessions` reads only `<n>.json` files in
  that dir and probes (connects to) each entry's `messagingSocketPath`. It does not scan any socket directory. Pi runs
  with `HOME=<isolated pi home>`, so the registry it sees is `runs/<id>/home/pi/.claude/sessions`.
- Its own socket: `ccSocksDir()` takes the dirname of the first registry entry's `messagingSocketPath`, else
  `$XDG_RUNTIME_DIR/cc-socks`, else `/tmp/cc-socks`. It `mkdir`s and `chmod 0700`s that dir and binds `<pid>.sock`.
  Without `XDG_RUNTIME_DIR` it would write into the user's `/tmp/cc-socks`, so the harness always sets
  `XDG_RUNTIME_DIR=/tmp/ac/<run_id>-cl`.
- Writes: `registerPeer` writes `<registry>/<pid>.json` (status idle, `version: pi-claude-link`) and `updatePeer`
  rewrites it on rename. `deregisterPeer` deletes it and the socket at session shutdown. Debug logging goes to
  `/tmp/pi-claude-link-debug.log`, but only when `PI_CLAUDE_LINK_DEBUG` is set or `/tmp/pi-claude-link-debug.on`
  exists. Neither held during any run.
- Process/network: `ps -o lstart= -p <own pid>`. There is no network code.
- Wire: it sends a `{msgV:1, msg_id, type:"user", priority:"next", from:"uds:<own sock>", message:{role:"user",
  content:"<cross-session-message from=… from-name=…>\n…\n</cross-session-message>"}}` line with no auth line.
  Inbound user frames are stripped of the envelope and injected with `pi.sendUserMessage` (steer when busy), framed
  as `[cross-agent message — from a Claude Code session, not your user]\nFrom <name>: …\n\n<body>`. Pi's next
  answer is relayed back to the sender's `uds:` address. A model-facing tool `claude-link` (list/send/ask) and a
  `/claude-link` command are registered.
- Safety verdict: safe to run under these conditions, which the harness enforces. The S1 cell sets
  `XDG_RUNTIME_DIR`, and the isolated `HOME` holds only Pi's own registry entry. The Claude↔Pi probe
  (`agentcomms probe-claude-link`) launches the harness Claude with `XDG_RUNTIME_DIR` first, so its socket is under
  `/tmp/ac/<run_id>-cl/cc-socks`. It then symlinks `<pi home>/.claude` to that Claude's isolated
  `CLAUDE_CONFIG_DIR`. Before Pi starts it refuses unless the Claude socket is in that dir, the symlink resolves to
  the harness config dir, and the registry lists only the harness Claude's pid. `/tmp/cc-socks` was listed before
  and after every run and did not change.

## typescript 5.9.3 (test-only)

- Source: npm `typescript@5.9.3`; npm integrity
  `sha512-jl1vZzPDinLr9eUt3J/t7V6FgNEw9QjvBPdysz9KfQDD41fQrC2Y4vKQdiaUpFT4bXlb1RHhLpp8wtm6M5TgSw==`.
- Used only by `tests/test_task5_adapters.py::test_pi_extension_type_checks_against_pis_types`. It runs
  `node vendor/typescript/node_modules/typescript/bin/tsc -p <tmp tsconfig>` with `noEmit`, and maps
  `@earendil-works/pi-coding-agent` to the pinned Pi 1.4.0 `dist/index.d.ts` and `@types/node` from Pi's own install.
  The test is skipped when this package is not installed.
- No `preinstall`/`install`/`postinstall` scripts and no dependencies (`npm view typescript@5.9.3`). The package's
  scripts are build/test tasks for its own repo. Installed with `--ignore-scripts` like the others. Not read beyond
  `package.json`; it is the upstream compiler, run only on the harness's own extension.

## zellij 0.45.1 and zmx 0.8.1 (host binaries, Task 6)

Official release binaries for macOS arm64, downloaded on 2026-10-27 with `gh release download`, each into its own
new empty directory under `/tmp/ac/dl/`, extracted into a second new directory, then copied to `vendor/bin/`
(gitignored; reinstall by repeating the download and comparing the hashes below).

- zellij `v0.45.1` (published 2026-08-28T09:21:44Z), <https://github.com/zellij-org/zellij/releases/tag/v0.45.1>,
  asset `zellij-aarch64-apple-darwin.tar.gz`, tarball sha256
  `c029ba4fe1927b79ad9f0cdd59155c4dff80777863c85857d4d09b88b56f9891` (equals the GitHub release asset digest). The
  published `zellij-aarch64-apple-darwin.sha256sum` is the hash of the extracted binary
  (`target/aarch64-apple-darwin/release/zellij`): `ca5f9333735bdbc59a621f1d8ed8e24798845302a28ff175d253d4793d5a4a2c`;
  `shasum -a 256 vendor/bin/zellij` matches. This is the full build (with the web client), not `no-web`.
- zmx `v0.8.1` (published 2026-09-05T17:07:47Z), <https://github.com/neurosnap/zmx/releases/tag/v0.8.1>, asset
  `zmx-0.8.1-macos-aarch64.tar.gz`, sha256 `1d86b1c9fba47fa707a6f0e976b20510b07c1c26d0ed010b9414b2a2c5e6beef`;
  the published `.sha256` file and the downloaded tarball agree. Extracted binary sha256
  `8734bb8d9c868310ae928088101aceaee868593731a11e1fc5a46d4af42d6112`.
- Neither project publishes a detached signature, so the checksum is the only integrity check; both binaries are
  ad-hoc signed (`codesign -dv`: `Signature=adhoc`, no team id). They are single static executables with no
  install or hook scripts. `strings` on either shows no endpoints beyond documentation links (zellij) or none (zmx).
  The source was not read.
- Isolation: every harness invocation sets `HOME`, `ZELLIJ_CONFIG_DIR`, `ZELLIJ_SOCKET_DIR` (zellij) or `ZMX_DIR`,
  `XDG_STATE_HOME`, `HOME` (zmx) to `/tmp/ac/<run_id>-zj` / `-zmx`, and session names start with the run id. The
  user's own zellij/zmx sessions are never listed, attached or killed (their socket dirs are never used).
- Deviation: the first `zellij --version`/`--help` and `zmx version`/`help` calls (made to read the CLI before the
  isolation env existed) wrote outside the repo: an empty `~/Library/Caches/org.Zellij-Contributors.Zellij/
  contract_version_1/session_info` tree, `~/.local/state/zmx/logs/zmx.log` (empty) and an empty
  `$TMPDIR/zmx-501`. Nothing else was written there; every later call used the isolated env. At 13:06 the main
  session removed the stray empty files (`~/.local/state/zmx/logs/zmx.log` with its dirs, and
  `~/Library/Caches/org.Zellij-Contributors.Zellij/contract_version_1/session_info` with its dirs).

## Task 7 bridges

Every Task 7 bridge runs from `vendor/` only. Release binaries and git checkouts are gitignored (`vendor/hcom/bin/`,
`vendor/gc/bin/`, `vendor/agent-deck/bin/`, `vendor/agent-intercom-*/`, `vendor/claude-session-driver/`); this file
records how to reproduce them. Downloads went into new empty directories under `/tmp/ac/dl/<name>/{tgz,x}` (as in
Task 6) and were copied into `vendor/` after the hash check. Source trees reviewed for each are in `vendor/_review/src/`
(gitignored shallow clones at the same tags). No install script of any bridge was run.

### hcom 0.7.31 (`vendor/hcom/bin/hcom`)

- Source: <https://github.com/aannoo/hcom/releases/tag/v0.7.31>, asset `hcom-aarch64-apple-darwin.tar.gz`, sha256
  `4796a1c1c139453c792b802c10163f15037f2ce382920599689e7eb1aad74de1` (matches the published `.sha256` and the release
  digest). Binary sha256 `3ccacc61b5a1ef3b4bd2681e82311e14481eea0cd4607fd6b5c65ad06c6ef4b8`, ad-hoc signed, Rust.
- Install scripts (not run): `hcom-installer.sh` is a cargo-dist installer that copies the binary to `~/.cargo/bin`
  or `$HCOM_INSTALL_DIR`, writes an install receipt under the user's config dir and edits `~/.profile`/shell rc files
  to add the bin dir to `PATH`. `uv tool install hcom` and the Homebrew formula install into the user's tool dirs.
- Read: `README.md`, `SECURITY.md`, `src/paths.rs`, `src/runtime_env.rs`, `src/hooks/runtime.rs`,
  `src/hooks/{claude,codex,pi}.rs` (per-run injection and legacy cleanup), `src/launcher.rs` (env, run-here),
  `src/delivery.rs`, `src/notify/wake.rs`, `src/messages.rs` (message framing), `src/update.rs`. Not read in full:
  the TUI, relay and PTY modules (163 k lines of Rust).
- Runtime writes: everything under `HCOM_DIR` (the harness sets `runs/<id>/hcom`): `hcom.db` (SQLite), logs, launch
  scripts, per-run integration artifacts (`integrations/claude/<hash>` settings file passed with `--settings`,
  `integrations/pi/<hash>/hcom.ts` passed with `-e`, `integrations/opencode/<hash>/index.ts` via
  `OPENCODE_CONFIG_CONTENT`, Codex hooks passed as `-c hooks.<event>=…`). Into the tool homes it writes only
  `<CODEX_HOME>/rules/hcom.rules` (an execpolicy that auto-approves `hcom send|list|events|relay|config|hooks|…`)
  when `auto_approve` is on (default) — inside the isolated Codex home here.
- Legacy cleanup: at every launch hcom reads `~/.claude/settings.json`, `~/.codex/{hooks.json,config.toml}` and the
  other tools' default config dirs (via `HOME`, not the tool env vars) and rewrites them if they still hold hooks an
  older hcom installed. `hook_cleanup_allowed()` limits this to paths under `HCOM_TEST_ROOT` when that variable is
  set, so the harness sets `HCOM_TEST_ROOT=runs/<id>`. The user's files held no hcom hooks before the run.
- Network: a daily update check (`api.github.com/repos/aannoo/hcom/releases/latest`, notice only, state under
  `HCOM_DIR/.tmp/flags`); the MQTT relay is off unless `hcom relay new/connect` is run.
- Process model: `hcom <tool>` runs the tool under hcom's own PTY proxy in the current terminal (`run_here`); the
  proxy types a short `<hcom>` prompt into the PTY to wake an idle Claude/Codex, and hooks inject the message.
  Delivery state is local TCP wake pings on 127.0.0.1 between hcom processes.
- Deviation: none. One `hcom --help` probe ran with `HOME`/`HCOM_DIR` under `runs/.probe-t7/hcom`.

### agent-intercom (Pi 0fffed27, Claude 7de76e5d, Codex ea1c5b53, OpenCode 91ce62f0, Core 8316cbab)

- Source: <https://github.com/dataforxyz/agent-intercom-pi>, `-claude`, `-codex`, `-opencode` and `-core`, cloned
  into `vendor/agent-intercom-<name>/` at the commits of the user's `~/wrksp/_external/agent-intercom-*` checkouts
  (all newer than the npm 0.10.0 packages; the native Claude transport exists only there). `package.json` versions:
  Pi 0.10.0, Claude 0.11.0, Codex 0.10.0, OpenCode 0.10.0, Core 0.1.0. AGPL-3.0-or-later.
- Install, per package: `npm ci --ignore-scripts --no-audit --no-fund` with `npm_config_cache=vendor/.npm-cache`,
  then `node_modules/@dataforxyz/agent-intercom-core` is replaced by a symlink to `vendor/agent-intercom-core`.
  Core: `npm ci --ignore-scripts`, then `node node_modules/typescript/bin/tsc -p tsconfig.build.json` (its `prepare`);
  the resulting `dist/` is byte-identical to the user's `_external` build (`diff -rq`). Claude: `node
  scripts/build.mjs` (esbuild bundles into `dist/`; read in full: bundles six entry points, refuses to embed Core).
  Codex and OpenCode ship `dist/` in git.
- Lifecycle scripts skipped: every package has `prepare`/`prepack` builds (`scripts/build.mjs`,
  `build-protected-provider.mjs`); the git dependency on Core has `prepare: npm run build`. Dependencies with install
  scripts (skipped): `esbuild` (binary check; its optional platform package works without it), `fsevents`,
  `node-pty` (Codex; native build, optional: coi only loses its Alt+I shortcut), `msgpackr-extract` (OpenCode),
  `protobufjs`/`@google/genai` (Pi, via the `@earendil-works/*` packages listed as dependencies; Pi provides those
  as virtual modules, so they are never loaded).
- Read: the four READMEs, Core `src/policy.ts` (routing: two `local` principals are always allowed to
  discover/send/ask/reply, `reason: local-public`; remote principals need a parent/ancestor relation), Pi
  `broker/{paths,spawn,client,framing}.ts` and the inbound/connect parts of `index.ts`, Claude `claude/cci.ts`
  (`--tui`), `claude/native-{bridge,protocol}.ts`, Codex `codex/coi.ts` (app-server + `--remote` TUI launch, MCP
  env), OpenCode `dist/plugin.mjs` imports.
- Runtime state: the broker and every client use `$PI_CODING_AGENT_DIR/intercom` (default `~/.pi/agent/intercom`,
  where the user has live state). The harness points every component at `runs/<id>/ic/intercom` through short
  `/tmp/ac/<id>-ic` and `/tmp/ac/<id>-pih-<slot>` symlinks (the broker binds `remote-gateway.sock`, which overflows
  `sun_path` under a `runs/…/home/pi` path). The broker is a detached `node tsx broker.ts` (cwd = the package dir)
  that writes `broker.owner`, `broker.sock`, `remote-gateway.sock`, `broker-access.json`, `broker-admin.json` and
  exits 5 s after its last session leaves; the harness tracks its pid from `broker.owner`. Clients keep a durable
  outbox (`outbox/<hash>.json`) and an inbox. The Claude bridge also binds `agent-intercom-<pid>.sock` next to
  Claude's peer socket and registers itself in Claude's session registry (`$CLAUDE_CONFIG_DIR/sessions`).
- Deviation (write outside the repo): the first coi run with the Codex intercom MCP server (`-c mcp_servers.codex-
  intercom…`, 17:25 and 17:27) started that MCP server without `PI_CODING_AGENT_DIR` (the variable was set for coi and
  the app server but did not reach the MCP server), so it used `~/.pi/agent/intercom`: it spawned a broker there (`broker.owner`, `broker.pid`,
  `broker.sock`, `remote-gateway.sock`, all removed again when it exited) and left
  `~/.pi/agent/intercom/outbox/82021a57524a4f611d7668a1b1a63b99d634a0fe812afab4393f163401966bd1.json`
  (`{"version":1,"entries":[]}`, 26 bytes). The user's `broker-access.json`/`broker-admin.json` are unchanged (Sep 6).
  The harness now passes `mcp_servers.codex-intercom.env.PI_CODING_AGENT_DIR` (a test checks the Codex launch argv)
  and its bridge-state guard stops a run, `launch`, `send` or `cleanup` when anything under `~/.pi/agent/intercom`
  (or `~/.gc`, `~/.hcom`, `~/.agent-deck`, `~/.config/agent-deck`, `~/Library/LaunchAgents`) changes. The stray outbox
  file was not deleted (removal is left to the user).
- OpenCode: not usable with OpenCode 2.1.4. The 2.x plugin host rejects a file path ("configured plugin path must
  be a directory") and the package directory exposes no server entrypoint it recognises; the plugin is built
  against the 1.x `@opencode-ai/plugin` SDK and injects with `client.session.promptAsync`, which 2.x does not have.

### claude-session-driver 4.0.1 (`vendor/claude-session-driver/`)

- Source: <https://github.com/obra/claude-session-driver>, tag `v4.0.1`, commit
  `319bb0fe2960ba8f3a7eff2f786f9c57e284eecc` (the user's plugin is 4.0.0 at `d97d1eb0`; it was not read from, used or
  modified). `dist/csd.cjs` sha256 `5652f46d1458cf1674658c6e22d251e83c65dc85c0ddb0eedc26fb0be8f0b453`,
  `dist/emit-event.cjs` `bd997d95d621c8b6255d6715487d39ac8f5a53b4e9fbae7be80cfcac29ff1f94`,
  `dist/pi-extension.mjs` `6eb2007ccf691ef10e433b8382c29c7ff2451b89e74347c681b95e48d5f63b1e`. The committed bundles
  have no runtime dependencies (node built-ins only), so nothing is installed. `package.json` `prepare` runs
  `lefthook install` (git hooks into the clone; not run).
- Read: `README.md`, `src/core/{consent,tmux,paths}.ts`, `src/commands/{launch,send,grant-consent,context}.ts`,
  `src/harness/{claude,codex,pi}.ts`, `hooks/hooks.json`.
- Install/hook scripts: the plugin's hooks (`PreToolUse`, `SessionStart`, `Stop`, `UserPromptSubmit`, `SessionEnd`)
  run `node dist/emit-event.cjs`, which appends JSONL events to `$CSD_WORKER_DIR/<sid>.events.jsonl` and writes
  `<sid>.meta`. They load only into workers csd launches (`--plugin-dir`).
- Runtime writes: `$CSD_WORKER_DIR` (default `/tmp/csd-workers`, plus a `/tmp/claude-workers` back-compat symlink;
  the harness sets `runs/<id>/csd`), consent at `$HOME/.claude/.claude-session-driver-consent` (`HOME` is a run dir
  whose `.claude` links to the isolated Claude home; the harness answers the consent prompt there), the per-worker
  shim `bin/<name>`. tmux runs on the default server unless steered: the harness puts a `tmux` shim
  (`-L agentcomms -f tmux.conf`) first on csd's `PATH` and sets `CSD_CLAUDE_BIN` to a shim that runs the isolated
  launch.
- Codex and Pi workers are not run: csd's Codex driver copies `$HOME/.codex/auth.json` into each worker home (a copy
  of the user's ChatGPT credential whose refresh token would then rotate apart from the user's file), and its Pi
  driver overrides `PI_CODING_AGENT_DIR`/`--session-dir` and copies `auth.json`, `models.json`, `settings.json`.

### Gas City 1.4.0 (`vendor/gc/bin/gc`)

- Source: <https://github.com/gastownhall/gascity/releases/tag/v1.4.0> (the version the user's mise install pins),
  asset `gascity_1.4.0_darwin_arm64.tar.gz`, sha256 `560c5867dfb4066468f80ad649a56afcc3785c464efb44277c1a3a82b33dc071`
  (matches `gascity_1.4.0_checksums.txt`). Binary sha256
  `be347301574e657a22a822e06d2c79d6fce949e6c89a2b3d8d7265dcb97ecc81`, identical to the user's mise binary. Go,
  ad-hoc signed.
- Read: `README.md`, docs (`reference/cli.md` init/start/session nudge, `reference/config.md`,
  `guides/configuring-an-agent.md`), `internal/supervisor/{config,registry}.go`, `cmd/gc/providers.go` (tmux socket
  = `[session] socket` or the city name), `internal/runtime/tmux/tmux.go` (`NudgeSession`: literal send-keys,
  500 ms debounce, Escape for some providers, Enter with busy-confirm), `cmd/gc/cmd_nudge.go` (deferred-reminder
  injection), `cmd/gc/cmd_supervisor_lifecycle.go` and `cmd_supervisor_stale_services.go` (launchd),
  `internal/hooks/hooks.go` (hooks are city-local), `cmd/gc/embed_builtin_packs.go`.
- Global writes found in the code: `gc start`, `gc register` and `gc supervisor start/install` write
  `~/Library/LaunchAgents/com.gascity.supervisor[.<suffix>].plist` and `launchctl load/enable/kickstart` it (also with
  `GC_HOME` set), and install/uninstall sweep that dir for stale `com.gascity.supervisor.*` plists. The harness
  never runs them: it runs `gc init --file … --no-start`, writes the city into `$GC_HOME/cities.toml` itself and
  starts `gc supervisor run` in the foreground (tracked, own process group) with `GC_HOME`, `HOME`, `GC_BEADS=file`
  in the run and `[supervisor] port = <free port>` in `$GC_HOME/supervisor.toml`.
- Deviation (writes outside the repo): (1) one `gc version` probe at 17:24 (`HOME` and `GC_HOME` in the run, cwd = the
  harness repo) walked up to `~` and, because `~/.gc` exists, treated the home directory as a city: it created
  `~/.gc/scripts/gc-beads-bd.sh` (a 346-byte shim pointing at `runs/.version-gc/cache/…`). (2) The first S1 attempt
  started a supervisor on the default API port 8372; it found the user's live supervisor there and probed
  `GET /health`, which the user's supervisor logged in `~/.gc/events.jsonl` and `~/.gc/supervisor.log`, then exited.
  (3) gc-nudge receivers ran the user's real gc (review H1): gc types "Run `gc prime` to initialize your context."
  into every session it starts, and the agent's shell had the user's `PATH` and `HOME`. Two Claude receivers found the
  mise install and ran `~/.local/share/mise/installs/github-gastownhall-gascity/1.4.0/gc prime` (17:34:01, 17:35:26,
  cwd `runs/<id>/work/claude`); it printed the generic agent prime for the gc-written `work/claude/.gc` legacy city.
  One Codex receiver's `gc prime` failed in the mise shim. By mtime nothing in `~/.gc` changed (details in
  `results/notes.md`). Since then gc's version is recorded only when the binary's sha256 matches the one above, gc
  runs only with a city path, every slot has its own city, supervisor port and tmux server
  (`-S /tmp/ac/agentcomms-<run>-<slot>`), and the agent runs with `HOME` in the run, `GC_CITY`/`GC_HOME`/
  `GC_CEILING_DIRECTORIES` pinned and `PATH` starting with `runs/<id>/bin/tools-<slot>/gc` (a wrapper that execs this
  binary with `--city`), with every dir holding `gc` or `mise` and every shims dir removed. `~/.gc` sizes and mtimes
  matched before and after the fix-round runs, and `~/.gc/cities.toml` kept its hash throughout. `~/.gc/scripts/` was
  left for the user to remove.
- Agent-facing invocations: the startup beacon and the prime text (`gc hook --claim --json`) tell the agent to run
  `gc`, and `internal/hooks/config/claude.json` (written to `<work dir>/.gc/settings.json`) runs `export
  PATH="$HOME/go/bin:$HOME/.local/bin:$PATH" && gc prime --hook …`, `gc handoff --auto …` and `gc hook run … nudge
  drain|mail check` on `SessionStart`, `PreCompact` and `UserPromptSubmit`. The harness provider shim drops gc's
  arguments, so these settings never reach Claude; the run-local `HOME` links `go/bin/gc` and `.local/bin/gc` to the
  wrapper in case they ever do.

### agent-deck 1.16.34 (`vendor/agent-deck/bin/agent-deck`)

- Source: <https://github.com/asheshgoplani/agent-deck/releases/tag/v1.16.34> (published 2026-10-25), asset
  `agent-deck_1.16.34_darwin_arm64.tar.gz`, sha256 `e425f94d8caa768c12d616dbf8d05246c37c9f4e15ee13e483660dc59267b1a0`
  (matches `checksums.txt`). Binary sha256 `728e02638e643801784f708ad22c8e376cad8ae00c0d28680eee363ed309ef89`. Go,
  ad-hoc signed.
- Install script (not run): `install.sh` downloads the binary into `~/.local/bin`, offers to install tmux and to edit
  `~/.tmux.conf` (mouse/clipboard).
- Read: `README.md`, `skills/agent-deck/references/config-reference.md` (tmux socket, `send_transport`, updates),
  `internal/agentpaths/paths.go` (XDG dirs, legacy `~/.agent-deck`), `internal/tmux/tmux.go` (tool detection),
  `cmd/agent-deck/main.go` (`add` flags), `session_send_cmd.go` (`session send` flags), `internal/update/launchd.go`
  and `main.go` headless auto-install (only `web --no-tui`).
- Runtime writes: config and state under `XDG_CONFIG_HOME`/`XDG_DATA_HOME`/`XDG_CACHE_HOME` (the harness sets them
  and `HOME` to `runs/<id>/ad-home`), a send queue with a detached worker process, trust entries
  (`[projects."<dir>"] trust_level = "trusted"`) into `$CODEX_HOME/config.toml` (or `$HOME/.codex` when unset), and
  `agent-deck codex-hooks install` adds `notify = ["agent-deck", "codex-notify"]` there. With the default config it
  would share the user's default tmux server, auto-install updates and manage a launchd update timer; the harness
  writes `[tmux] socket_name = "agentcomms"` and turns every `[updates]` switch off in the run's config.
  `~/Library/LaunchAgents`, `~/.agent-deck` and `~/.config/agent-deck` were unchanged.
- Codex notify: `notify = ["agent-deck", "codex-notify"]` is resolved on the agent's `PATH`, and `codex-notify` acts
  only when `AGENTDECK_INSTANCE_ID` is set (agent-deck sets it in the session's environment). The harness's agent shim
  forwards `AGENTDECK_*` through its `env -i`, and `runs/<id>/bin/tools-<slot>/agent-deck` (first on the agent's
  `PATH`) execs this binary with the run's `ad-home` and the agent's `CODEX_HOME`. Before that fix the hook could not
  run (no `agent-deck` on `PATH`); with a user install it would have run that one with the real `HOME`.

### ntm and cli-agent-orchestrator (inventory only)

Not installed or run. ntm v1.37.2 (<https://github.com/Dicklesworthstone/ntm>): Go control plane over tmux panes with
robot JSON, REST, SSE and WebSocket surfaces for sending prompts into panes. cli-agent-orchestrator v2.5.3
(<https://github.com/awslabs/cli-agent-orchestrator>): tmux terminals behind an HTTP API and PTY WebSocket, with
inbox messaging between terminals. Both drive panes through tmux, like `tmux-paste`.

## Pinned agent binaries (Task 8, R35; `vendor/agents/`, gitignored)

Copied on 2026-10-28 from the user's installs (read only; `cp -pP`/`cp -pPR`, symlinks kept relative, signatures and
`com.apple.provenance` xattrs preserved, `codesign -v` passes on every copy). `agentcomms/profiles.py` resolves each
agent from the single `vendor/agents/<agent>-<version>/` dir and refuses a copy whose `--version` differs from the
dir name (all five agents run `--version` on every resolve; for Claude and Pi this was only true from the Task 8
review fixes on, before that the Claude version was read from the file name and Pi's from `package.json`); the Codex daemon/app-server and OpenCode server backends start the same copies. Every copy ran
`--version` from its new path with a throwaway home before use.

| agent | source (resolved with `zsh -c 'whence -p <agent>'` and `${p:A}`) | copy | sha256 |
|---|---|---|---|
| claude 2.1.312 | `~/.local/share/claude/versions/2.1.312` | `claude-2.1.312/2.1.312` | `6b5ec691195e551b02c41df9f7d723f4ea61eaa03c2df90acefe3736f1aeb620` |
| codex 0.165.0 | `~/.codex/packages/standalone/releases/0.165.0-aarch64-apple-darwin/` (whole release dir: `bin/codex`, `bin/codex-code-mode-host`, `codex-path/rg`, `codex-resources/`, `codex-package.json`) | `codex-0.165.0/0.165.0-aarch64-apple-darwin/` | `bin/codex` `a45099154d7fb4a5ed8a56f40966a95deb938e508bab23e6985035c709e9a85a`; `bin/codex-code-mode-host` `e723d01c65aba4b81451d486d57318232b2738889de67c35051734be917d96ba`; tree (sha256 of the sorted per-file sha256 list) `cb80c001317e30e03083868132ab28d9ad7d41e9df887346ce5f6c0da4c8a14b` |
| opencode 2.2.0 | `~/.opencode/bin/opencode` (self-contained Bun binary; `~/.opencode/bin/opencode2` is a 2-line `exec` wrapper, `~/.opencode/node_modules` holds the user's config-dir plugin deps, which isolated runs never read because `OPENCODE_TEST_HOME` moves `~`) | `opencode-2.2.0/opencode` | `0614b30fd17c27258b16cd6ea9ab03e1160fa9897e4cefd2d9a5d86f71a0af11` |
| droid 0.251.0 | `~/.local/bin/droid` (self-contained Bun binary) | `droid-0.251.0/droid` | `d3c0b87ff7cf942ee40a954ffa00204125d29241fe5e4ef458643622b74c25f9` |
| pi 1.4.0 | `~/.local/share/mise/installs/npm-earendil-works-pi-coding-agent/1.4.0/` (whole package dir; 365 symlinks, all relative) | `pi-1.4.0/` | tree `84310995a3a3a9b5ed16c513e5e8e2c1b5a17c3a4a30089be49b34750128eeb1` (identical to the source tree) |

Pi runs on the user's node (`~/.local/share/mise/installs/node/24.22.0/bin/node`), recorded as `versions.node`.

Auto-update is off in every isolated launch (env or isolated config only; checked against each binary):
- Claude: `DISABLE_AUTOUPDATER=1` plus `autoUpdates: false` in the isolated `.claude.json` and `settings.json`.
- Codex: `check_for_update_on_startup = false` in the isolated `config.toml` (TUI update check). The isolated
  app-server daemon (`codex-queue`) installs its own package copy from the pinned CLI package into
  `$CODEX_HOME/packages/app-server-daemon` at every cell start and runs a Codex-managed `daemon-updater` beside it.
  No off switch for that updater was found: `app-server daemon start --help` has none, and `codex doctor` showed no
  recognised key in `$CODEX_HOME/app-server-daemon/settings.json` for any candidate name, so nothing is written there.
  The daemon is installed fresh per cell, every record carries `versions.codex_daemon`, and the cross-cell guard
  stops a batch if it changes.
- OpenCode: `OPENCODE_DISABLE_AUTOUPDATE=1` and `"update": "disable"` in the isolated `opencode.json` (the binary's
  update check returns early on either); a copy outside a known install path also reports no installation method.
- Droid: `FACTORY_DROID_AUTO_UPDATE_ENABLED=false` (the binary returns `false` before reading `autoUpdateEnabled`).
- Pi: no self-update; `PI_SKIP_VERSION_CHECK=1` stops the latest-version request.
