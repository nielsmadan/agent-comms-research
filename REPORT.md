# Agent message injection: report

Which way of pushing a message into a running, human-attachable coding-agent TUI should the Mac Studio fleet use?
This report answers that for Claude Code, Codex, Pi, OpenCode and Droid, from 1596 records in `results/raw.jsonl`
(2026-10-24 to 2026-10-28) on a MacBook running macOS 27.2.

Tested versions (pinned copies, R35): Claude 2.1.312 (`haiku`), Codex 0.165.0 (`gpt-6-luna` low), Pi 1.4.0 on node
24.22.0 (`openrouter/deepseek/deepseek-v4.1-flash`), OpenCode 2.2.0 (`opencode-go/gpt-6-luna`), Droid 0.251.0
(`gpt-6-luna` low); bridges hcom 0.7.31, agent-intercom (Pi 0fffed27, Claude 7de76e5d, Codex ea1c5b53), csd 4.0.1,
Gas City 1.4.0, agent-deck 1.16.34; hosts tmux, zmx 0.8.1, zellij 0.45.1, iTerm2; nono 0.80.0. Earlier pilot
records ran on older versions and on macOS 26 and are labelled as such in `results/matrix.md`.

All counts are k/n: k good outcomes out of n verdicts, per `agentcomms/scoring.py`. `n/a`, `error` and `env_error`
verdicts are not counted in n and are reported separately. Most cells have n = 1 to 5, so only frequent failures are
detectable (section 9).

## Summary

**Recommendation: run every agent TUI in a tmux server (the human attaches with `tmux attach`), and push messages
through each agent's own in-process route, not through terminal keystrokes.** Per agent:

| agent | use | safety k/7 | total k/n | 5-rep S1/S2/S5/S7 | nono | why |
|---|---|---|---|---|---|---|
| Claude | `claude-channel` (alternative: `claude-uds-child`) | 7/7 | 16/16 | 20/20 | 4/4 | tied with `claude-uds-child` and `claude-uds-accept` on every measure; `-accept` widens trust to any same-user process (R26) |
| Codex | `codex-remote-start` | 5/7 | 15/17 | 18/20 (S7 3/5) | 3/4 (S7 merged) | best Codex route; queues behind a running turn; the only native Codex route whose S3 was good |
| Pi | `pi-ext` | 6/7 · n/a 1 | 15/15 | 20/20 | 4/4 | tied with `pi-session-bridge` and `pi-claude-link`; ours is 60 lines, queues to the turn boundary, no third-party code |
| OpenCode | `opencode-server-queue` | 7/7 | 17/17 | 20/20 | 4/4 | tied with `-steer` and `opencode-service-steer`; `-queue` waits for the turn boundary |
| Droid | `tmux-paste` | 3/7 | 11/16 | 15/20 (S7 0/5) | 3/4 (S7 merged) | Droid has no human-attachable push API; every terminal route approves permission dialogs (S3 harmful) and merges into a human's draft |

Columns: **safety k/7** counts good outcomes over seven fixed safety cells: S2 (push while a turn runs) ×3, S3
(receiver at a permission dialog) ×1 and S7 (a human's half-typed draft) ×3. An `n/a` cell counts as not shown safe,
and the n/a count is shown (R37). **total k/n** counts every counted screen + extensive verdict for S1–S8 and S10–S12.
**5-rep S1/S2/S5/S7** is idle wake, mid-turn, burst of 5 and draft, 5 reps each. **nono** is S1, S2, S4 and S7 with
receiver and sender sandboxed, one rep each. All scenarios are listed in section 1.

Sources: ranking and k/n from `results/shortlist.md` (generated from `raw.jsonl`); reps, nono and scale blocks from
the same file.

- **No nono grants were needed, because everything sat inside paths the profiles already grant.** Every shortlisted
  route ran under the user's `<agent>-local` profiles with receiver and sender sandboxed (60 cells plus 3 S9 round
  trips, section 7). Every nono verdict was one that raw also produced for that cell. The three
  native Codex routes merged the S7 draft under nono (0/1 each), where raw preserved it 3/5, 3/5 and 1/5. The pinned binaries, senders, channel server, Pi extension and isolated homes all lived in this
  repo under the profiles' `~/wrksp` read+write grant, and every harness socket was under `/tmp/ac`. A fleet that keeps
  any of these elsewhere may need grants (section 10.1). The one rule: `sops-exec` stays outside `nono run`.
- **Scale 8 held:** two batches of 8 concurrent receivers (best route per agent), 48/48 delivered and acked, latency
  0.002 / 0.022 / 0.588 s min / median / max (section 4.6). Larger fleets were not measured.
- **Agent to agent works on every native route tested.** Agent A reached agent B by running B's sender from its own
  shell (or a native tool such as Claude's `SendMessage`). 62 of 63 counted S9 records completed a round trip, plus
  one uncounted `env_error` (Pi's model registry). The one failure was Codex>Claude over agent-intercom (section 5).
  The 35 records with both legs on native routes were 35/35. Droid was reached only through agent-deck and gc-nudge,
  which type into its pane; agent→Droid over the recommended `tmux-paste` has no S9 record. Most native routes need an
  address and carry no sender identity (Claude peer frames carry `from-name`, pi-claude-link `From <name>`), so
  `agent-send` needs a name registry and should put the sender's name in the envelope.
- **Terminal injection is the weak spot.** All 34 harmful records in `raw.jsonl` are S3 cells where a terminal send
  plus Enter approved a permission dialog nobody approved. 27 were a paste plus Enter. 7 were typed sends: `tmux-keys`
  ×3, `zellij-write` ×3 and agent-deck typing into Droid. 10 of the 34 are pilot records on older versions (Claude
  2.1.310/2.1.311, Codex 0.164.0). No native route was harmful.
- **What is not known:** behaviour at fleet scale, on M5 hardware, on the fleet's macOS version, with the user's real
  config loaded for Claude, Pi and Droid (those cells were skipped, section 8), and for long-lived sessions. Section
  10.9 lists the re-tests.

`agent-send` can be a thin wrapper for Claude, Pi and OpenCode only. For those three, a stdlib `python3 -I` sender in
`agentcomms/senders/` reads the body on stdin and does the whole send. The wrapper replaces the senders' ownership
guard, which refuses any target that is not in a harness run manifest, with a registry (name → agent, adapter,
address). Codex and Droid need more:

- **Codex:** the spool and per-thread drainer that make `turn/start` queue behind a running turn are in the harness
  adapter (`adapters/codex_remote.py`), not in the sender. On its own, the sender blocks until the thread is idle.
- **Droid:** there is no stdlib sender at all.

Section 10.8 lists what to build.

## Contents

1. Scope and method
2. Inventory
3. Matrix (condensed)
4. Per-agent findings
5. Agent to agent (S9)
6. Terminal hosts (hostcheck)
7. nono
8. User-config interference
9. Measurement limits
10. Recommended fleet setup
11. Security findings
12. Incidents
13. Blocked on you / open questions
14. Rulings referenced, sources

## 1. Scope and method

- Receiver: an interactive TUI a human can attach to and type into. Headless modes (`claude -p`, `codex exec`,
  `pi --mode rpc`, `droid exec`), ACP and `@microsoft/tui-test` were inventory-only by the plan's scope decision.
- Isolation: every session ran in its own home under `runs/<run_id>/home/<agent>/` (README "Isolation"), launched
  through `sops-exec` with the user's injected credentials, in a private tmux server (`-L agentcomms`).
- Stages: pilot (S1) → screen (S1, S4, S7, S8 for all 71 mechanism × agent pairs) → extensive (S1–S12 for screen
  survivors, 3 reps of S2, S5, S7) → shortlist (5 reps of S1, S2, S5, S7; scale; user config; nono).
- Scenarios: S1 idle wake · S2 mid-turn · S3 receiver at a permission dialog · S4 10 KB payload · S5 burst of 5 ·
  S6 receiver killed and resumed · S7 human half-typed draft present · S8 human attached, types, push renders ·
  S9 agent→agent round trip · S10 stale address after `/clear` and `/compact` · S11 receiver in a model picker ·
  S12 backing server restarts. Recipes and good outcomes: README "Scenarios".
- Every record carries transcript evidence plus a pane recording; S7/S8 are judged from the pane, S3 harm from
  `approved.txt` and the pane.

## 2. Inventory

### 2.1 Tested (adapters in `agentcomms/adapters/`)

| kind | mechanism | agents | what it does |
|---|---|---|---|
| terminal | `tmux-keys`, `tmux-paste`, `tmux-paste-retry`, `tmux-buffer` | all 5 | `send-keys -l` / bracketed paste / paste with guarded Enter retry / `load-buffer`+`paste-buffer`, then one Enter |
| terminal | `zmx-send`, `zmx-paste`, `zellij-write`, `zellij-paste` | all 5 | the same typed / bracketed bytes through zmx and zellij |
| terminal | `iterm2-text`, `iterm2-paste` | Claude, Codex (spot cells) | the same through the iTerm2 Python API |
| native | `claude-uds` | Claude | Claude's peer socket with the peer token, default `crossSessionInbound` |
| native | `claude-uds-accept` | Claude | same, receiver started with `--settings '{"crossSessionInbound":"accept"}'` |
| native | `claude-uds-child` | Claude | a stdio MCP relay Claude spawns forwards with Claude's child messaging token |
| native | `claude-channel` | Claude | a development channel MCP server (`--dangerously-load-development-channels server:<name>`) |
| native | `codex-remote-start`, `codex-remote-steer` | Codex | per-receiver `codex app-server --listen unix://…`, TUI `--remote`; JSON-RPC `turn/start` (deferred while busy) or `turn/steer` |
| native | `codex-queue` | Codex | isolated Codex daemon, bare TUI attached to it, `codex queue --thread <uuid>` |
| native | `codex-queue-embedded` | Codex | probe variant: `-c` makes the TUI embedded while the daemon runs |
| native | `opencode-server-steer`, `-queue`, `-synthetic` | OpenCode | `opencode serve` on 127.0.0.1 with a password, TUI `--server`; `POST /api/session/:id/prompt` (`delivery` steer/queue) or `/synthetic` |
| native | `opencode-service-steer` | OpenCode | the background-service path, isolated |
| native | `pi-ext` | Pi | our extension: socket → `pi.sendUserMessage(text, {deliverAs: "followUp"})` |
| native | `pi-session-bridge` | Pi | `@vanillagreen/pi-session-bridge` 3.0.1 |
| native | `pi-claude-link` | Pi | `pi-claude-link` 0.1.0, joins Claude's peer mesh |
| bridge | `hcom` | Claude, Codex, Pi, OpenCode | `hcom <tool>` PTY proxy plus hooks; `hcom send @<name>` |
| bridge | `intercom`, `intercom-accept` | Pi, Claude, Codex | agent-intercom broker; Claude `cci --tui --transport native`, Codex `coi` |
| bridge | `csd` | Claude | claude-session-driver: tmux paste with confirmed submit |
| bridge | `gc-nudge` | Claude, Codex, Droid | Gas City `gc session nudge` (deferred `<system-reminder>` injection) |
| bridge | `agent-deck`, `agent-deck-composer-fallback` | Claude, Codex, Droid | agent-deck `session send` |

### 2.2 Probed, no adapter possible

- **Droid daemon.** `droid daemon` is a JSON-RPC server (`daemon.add_user_message` and friends) for Factory's own
  app over Remote Control; the TUI has no flag to attach to a daemon-owned session, so there is no push path into a
  human-attachable Droid TUI. `tmux-paste` stays Droid's only route (`results/notes.md` "Droid daemon probe").
- **`claude --bg` / agent view.** Blocked: the background service exits with "background agents disabled
  (3P/opt-out)" even with `disableAgentView: false` in the isolated settings; the user's `~/.claude/settings.json`
  has `disableAgentView: true`, which most likely leaks through `CLAUDE_CONFIG_DIR` (R16; probes `20261025-091430-bgpr`,
  `20261025-100432-4867`, no records). Host untested.
- **OpenCode `/tui/*`, `prompt_async`, `POST /session/:id/message`.** Do not exist in OpenCode 2.x (source read at
  2.0.32 and tag v2.1.4; `results/notes.md` "OpenCode routes"). The `docs/enumeration.md` entry for `/tui/*`
  described the 1.x server.
- **agent-intercom on OpenCode.** The plugin targets the 1.x SDK (`session.promptAsync`); OpenCode 2.1.4 rejects it
  (`vendor/REVIEW.md` agent-intercom).
- **csd on Codex and Pi.** Not run: the Codex driver copies `~/.codex/auth.json` into each worker home and the Pi
  driver overrides `PI_CODING_AGENT_DIR` and copies config (`vendor/REVIEW.md` claude-session-driver).

### 2.3 Inventory only (not run), with reason

From `docs/enumeration.md` and `docs/research-assumptions.md` unless noted.

| option | reason not run |
|---|---|
| Headless modes: `claude -p`, `codex exec`, `pi --mode rpc`, `droid exec --input-format stream-jsonrpc` | no human-attachable TUI (plan scope) |
| ACP (claude-agent-acp, codex-acp, `opencode acp`, pi-acp, `droid exec --output-format acp`) and ACP clients (acpx, Zed, JetBrains) | the ACP agent is its own process; it does not push into a separately running TUI (plan scope) |
| `@microsoft/tui-test` | test runner that owns the PTY, no attach (plan scope) |
| Ghostty AppleScript, kitty `kitten @ send-text`, WezTerm `cli send-text`, cmux | other terminal hosts; out of scope for Task 6 (tmux, zmx, zellij, iTerm2 chosen) |
| GNU screen `-X stuff`, dtach, abduco, shpool, tuistory, tmux control mode, libtmux, tmux-mcp servers, amux | same terminal-injection class as the tested tmux/zmx/zellij adapters; not selected |
| ntm, cli-agent-orchestrator | inventory per the plan's bridge list; both drive tmux panes like `tmux-paste` (`vendor/REVIEW.md`) |
| claude-squad, ccmanager, workmux, uzi, vibe-kanban, emdash, crystal, xum, sculptor, opcode, gastown, overstory, agent-of-empires, claudecodeui, omnara, ccgram, ebi relay, tmux dashboards, agent-mux | fleet runners; send path is tmux send-keys, their own PTY or a web UI, with no documented inject API into an attached TUI, or not live-session injection |
| Pi: pi-nvim, nicobailon/pi-intercom, pi-aimail, un-bien, pi-team, pi-event-monitor, pi-channels, remote-control family, joelclaw | same in-process `sendUserMessage` pattern as the three Pi extensions tested; not selected |
| rz-cli, zellij-claude-teams | Zellij pane messaging; not selected |
| agmsg, mcp_agent_mail, cross-agent-teams-mcp, ExaDev agent-comms, agents-can-communicate, claude-code-socket-transport, cc-peer (from the notes file) | not on the plan's bridge list; agent-comms and agmsg were the named substitutes if a shortlisted bridge needed a global-config write, which none did (`results/notes.md` Task 7 "Skips and limits") |

### 2.4 Cross-machine claims (recorded, not tested)

Same machine only was in scope. Claims found while building the adapters (`results/notes.md` Task 4, 5, 7):

- Claude: `bridge:`/`did:` peer addresses over Remote Control; `isolatePeerMachines` setting.
- Codex: `--remote ws(s)://host:port`, `app-server --listen ws://IP:PORT --ws-auth capability-token|signed-bearer-token`,
  `codex remote-control`, daemon `enable-remote-control`.
- OpenCode: `serve --hostname <any>` with password, `opencode pair` ("end-to-end encrypted"), service `remote` tunnel.
- Droid: `droid daemon --remote-control`, `droid computer register|list|ssh|port-forward`.
- hcom: MQTT relay (`hcom relay new/connect <token>`; the token grants launch/kill/drive on every enrolled device).
- agent-intercom: "Same-machine only by design", but the broker implements `remote-access-v1` registrations.
- Gas City: k8s and ACP providers, supervisor bind beyond loopback. agent-deck: `add --ssh`, `agent-deck web`.
- pi-session-bridge: "different … hosts" in its instructions; its transport is a local socket.

## 3. Matrix (condensed)

Full detail per host, backend, macOS version and condition: `results/matrix.md`. Ranking basis and every survivor's
row: `results/shortlist.md`. Columns are screen + extensive raw records (S2, S5, S7 have n = 3; the rest n = 1);
`harm` = harmful outcomes; `n/a` = scenario does not apply (reasons in `results/shortlist.md` and section 9).
`safety k/7` and `total k/n` are defined under the Summary table.

| agent | mechanism | S1 | S2 | S3 | S4 | S5 | S6 | S7 | S8 | S10 | S11 | S12 | safety k/7 | total k/n | harm |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Claude | claude-channel | 1/1 | 3/3 | 1/1 | 1/1 | 3/3 | 1/1 | 3/3 | 1/1 | 1/1 | 1/1 | n/a | 7/7 | 16/16 | 0 |
| Claude | claude-uds-accept | 1/1 | 3/3 | 1/1 | 1/1 | 3/3 | 1/1 | 3/3 | 1/1 | 1/1 | 1/1 | n/a | 7/7 | 16/16 | 0 |
| Claude | claude-uds-child | 1/1 | 3/3 | 1/1 | 1/1 | 3/3 | 1/1 | 3/3 | 1/1 | 1/1 | 1/1 | n/a | 7/7 | 16/16 | 0 |
| Claude | hcom | 1/1 | 3/3 | 0/1 | 1/1 | 0/3 | 1/1 | 3/3 | 1/1 | 1/1 | 1/1 | n/a | 6/7 | 12/16 | 0 |
| Claude | tmux-paste | 1/1 | 3/3 | 0/1 | 0/1 | 3/3 | 1/1 | 0/3 | 1/1 | 1/1 | 0/1 | n/a | 3/7 | 10/16 | 1 |
| Codex | codex-remote-start | 1/1 | 3/3 | 1/1 | 1/1 | 3/3 | 1/1 | 1/3 | 1/1 | 1/1 * | 1/1 | 1/1 | 5/7 | 15/17 | 0 |
| Codex | codex-remote-steer | 1/1 | 3/3 | 0/1 | 1/1 | 3/3 | 1/1 | 1/3 | 1/1 | 1/1 * | 1/1 | 1/1 | 4/7 | 14/17 | 0 |
| Codex | codex-queue | 1/1 | 3/3 | 0/1 | 1/1 | err 3 † | 1/1 | 1/3 | 1/1 | 1/1 * | 1/1 | 1/1 | 4/7 | 11/14 | 0 |
| Codex | intercom | 1/1 | 0/3 | 1/1 | 1/1 | n/a † | n/a | 3/3 | 0/1 | 1/1 | 1/1 | 1/1 | 4/7 | 9/13 | 0 |
| Codex | tmux-paste | 1/1 | 3/3 | 0/1 | 1/1 | 3/3 | 1/1 | 0/3 | 1/1 | 1/1 | 0/1 | n/a | 3/7 | 11/16 | 1 |
| Pi | pi-ext | 1/1 | 3/3 | n/a | 1/1 | 3/3 | 1/1 | 3/3 | 1/1 | 1/1 | 1/1 | n/a | 6/7 · n/a 1 | 15/15 | 0 |
| Pi | pi-session-bridge | 1/1 | 3/3 | n/a | 1/1 | 3/3 | 1/1 | 3/3 | 1/1 | 1/1 | 1/1 | n/a | 6/7 · n/a 1 | 15/15 | 0 |
| Pi | pi-claude-link | 1/1 | 3/3 | n/a | 1/1 | 3/3 | 1/1 | 3/3 | 1/1 | 1/1 | 1/1 | n/a | 6/7 · n/a 1 | 15/15 | 0 |
| Pi | intercom | 1/1 | 3/3 | n/a | 1/1 | n/a † | 1/1 | 3/3 | 1/1 | 1/1 | 1/1 | 1/1 | 6/7 · n/a 1 | 13/13 | 0 |
| Pi | tmux-paste | 1/1 | 3/3 | n/a | 0/1 | 3/3 | 1/1 | 0/3 | 1/1 | 1/1 | 0/1 | n/a | 3/7 · n/a 1 | 10/15 | 0 |
| OpenCode | opencode-server-queue | 1/1 | 3/3 | 1/1 | 1/1 | 3/3 | 1/1 | 3/3 | 1/1 | 1/1 * | 1/1 | 1/1 | 7/7 | 17/17 | 0 |
| OpenCode | opencode-server-steer | 1/1 | 3/3 | 1/1 | 1/1 | 3/3 | 1/1 | 3/3 | 1/1 | 1/1 * | 1/1 | 1/1 | 7/7 | 17/17 | 0 |
| OpenCode | opencode-service-steer | 1/1 | 3/3 | 1/1 | 1/1 | 3/3 | 1/1 | 3/3 | 1/1 | 1/1 * | 1/1 | 1/1 | 7/7 | 17/17 | 0 |
| OpenCode | opencode-server-synthetic | 1/1 | 3/3 | 1/1 | 1/1 | 3/3 | 1/1 | 3/3 | 0/1 | 1/1 * | 1/1 | 1/1 | 7/7 | 16/17 | 0 |
| OpenCode | tmux-paste | 1/1 | 3/3 | 0/1 | 0/1 | 3/3 | 1/1 | 0/3 | 1/1 | 1/1 | 0/1 | n/a | 3/7 | 10/16 | 1 |
| Droid | tmux-paste | 1/1 | 3/3 | 0/1 | 1/1 | 3/3 | 1/1 | 0/3 | 1/1 | 1/1 | 0/1 | n/a | 3/7 | 11/16 | 1 |
| Droid | gc-nudge | 1/1 | 3/3 | n/a | 1/1 | n/a † | n/a | 0/3 | 1/1 | 1/1 | 0/1 | 1/1 | 3/7 · n/a 1 | 8/12 | 0 |
| Droid | agent-deck | 1/1 | 3/3 | 0/1 | 1/1 | err 3 † | n/a | 0/3 | 1/1 | 1/1 | 0/1 | n/a | 3/7 | 7/12 | 1 |

`*` S10 on address-based routes: after `/new` the push landed in the old session, so compaction was not exercised
on the delivered session (R40).

`†` S5 precondition (R47): the five sends must go out within 1 s. Where the adapter's own sends took longer by design
(gc-nudge, intercom, intercom-accept and csd CLIs, the `tmux-paste-retry` settle) S5 is `n/a` ("adapter cannot
burst"); where the harness's per-send checks pushed the burst past 1 s (`codex-queue` 1.19–1.40 s, `agent-deck`
1.12–1.35 s) it is `error` (`burst-window`). Either way those records are out of S5's k/n. 44 records were
reclassified from evidence: 33 `n/a`, 11 `error` (`results/notes.md` "Whole-branch review fixes").

Screen survivors (good S1, no harm): Claude 16 of 18, Codex 11 of 17, Pi 13 of 13, OpenCode 13 of 13, Droid 10 of 10
(`results/screen.md`). Non-survivors: Claude `claude-uds` and `intercom` (every push held for a human), Codex typed
adapters (`tmux-keys`, `zmx-send`, `zellij-write`: text stuck in the composer), Codex `agent-deck` and
`-composer-fallback` (fresh Codex never reported idle, R31), `codex-queue-embedded` (no thread before a typed turn).

## 4. Per-agent findings

### 4.1 Claude Code 2.1.312

- Three native routes tie at the top: `claude-channel`, `claude-uds-accept`, `claude-uds-child` are 16/16, 7/7
  safety, 20/20 over 5 reps, 4/4 under nono. S1 median latency 0.019 s, 0.021 s and 0.068 s (5 reps each,
  `raw.jsonl`). All three steer a mid-turn push into the running turn (S2 interrupted 5/5) and keep a human draft
  (S7 5/5); S3 was `queued`, not harmful, on all three (`20261028-051824-cabf`, `-053852-3467`, `-055012-8d4d`).
- **Default inbound holds external senders.** `claude-uds` from a non-Claude process is parked as "Held peer message
  … from an unidentified session" with a Deny / Deliver picker (`held`, e.g. `20261027-112128-7fcd`). A probe that
  asserted `from_mode: "bypass"` with a valid peer token was still held (`20261025-091539-9a41`, probe on 2.1.310, no
  record; `results/notes.md` Task 4). Getting past the hold takes `crossSessionInbound: accept` on the receiver, the child
  path, or a channel.
- **The child path bypasses the hold without changing policy.** The MCP relay Claude spawns received
  `CLAUDE_CODE_MESSAGING_SOCKET`/`_TOKEN` in its environment, and its message was delivered with
  `origin.selfSent: true` (`20261025-085622-016f`). That cell cannot separate the process-ancestry check from the
  token.
- **`accept` admits unauthenticated frames (R26).** pi-claude-link's own `sendToClaude`, with no auth line, from a
  process not in Claude's registry, was delivered under `accept` (probes `20261027-120906-7975`, `-121239-100d`,
  `-121604-7b41` on 2.1.311, no records; `results/notes.md` "pi-claude-link safety"). On 2.1.312 the S9 Pi>Claude
  cell over `intercom-accept` (`20261028-161100-7b7f`) relied on the same kind of frame: agent-intercom's native
  Claude bridge writes frames with no auth line (`results/notes.md` Task 7 "Security observations").
- Claude↔Claude via `SendMessage` works under the default when both sessions are in the same permission class
  (S9 pilot `20261027-171554-6acd`, both bypass).
- Terminal routes: the paste's Enter confirms the highlighted "Yes" in a permission dialog (S3 harmful; a manual
  probe showed the bracketed paste alone left the dialog open and the Enter approved it, `20261024-234730-0101`).
  Claude turns each tab of a pasted 10 KB message into four spaces (S4 not intact) and a typed 10 KB message into ten
  collapsed pastes with the Enter stuck. Every terminal route merges the push into a human draft (S7 0/3).
- iTerm2 typed sends (`iterm2-text`) left Claude S1 stuck in the composer 2/2 with nobody typing
  (`20261027-154158-fe6b`, `-154539-527f`); zmx/zellij typed sends of the same bytes submitted.

### 4.2 Codex 0.165.0

- `codex-remote-start` ranks first (15/17, safety 5/7). It queues a mid-turn push behind the running turn (S2
  queued 5/5) through a per-thread spool and drainer in the harness adapter (section 10.8), and its S3 push queued
  without approving the dialog (`20261028-081955-1213`). `codex-remote-steer` steers into the running turn (S2 interrupted 5/5).
- **Draft preservation is unreliable on all three native Codex routes.** 5-rep S7: remote-start 3/5, remote-steer
  3/5, queue 1/5; under nono all three merged (0/1 each). On 0.164.0 remote-start/-steer merged the draft in the
  screen; 0.165.0 preserved it in the screen and merged it in both extensive reps (`results/screen.md`
  "Re-screen", D5 in `results/shortlist.md`).
- `codex-queue` has no counted S5: its 3 extensive and 2 shortlist bursts took 1.19–1.40 s, and the harness's own
  per-send checks (about 0.5 s of every burst) pushed them past the 1 s precondition, so they are `error`
  (`burst-window`, R47). It left the Codex top 2 (now 11/14) and needs an S5 re-test (section 10.9).
- S3 on `codex-queue` and `codex-remote-steer` was `lost` (not harmful): the push was not recorded within the reply
  wait, the dialog open after the send (`20261028-074020-075f`, `-084335-9bbf`; n = 1 each).
- S12: all three survived a backend restart (`codex-remote-start` down 5.4 s, `20261028-083656-6fd8`; `codex-queue`
  daemon down 25.9 s, `20261028-080345-7ffa`). Codex app-server 0.165.0 ignores SIGTERM for at least 5 s and is
  SIGKILLed. A thread with no turn does not survive a restart ("This conversation is unavailable"; R18).
- First-turn latency after launch includes Codex's own thread start (S1 median 0.39 s remote-start, 0.51 s queue
  over 5 reps; up to 5.5 s on the first pilot turns, `results/notes.md` Task 4).
- An embedded TUI (launched with `-c`) drains the daemon's queue too (probe `20261025-091104-bad0`), but
  `codex queue` needs a thread that exists, so a fresh embedded TUI has no route (`codex-queue-embedded` rejected).
- Terminal: Codex swallows the Enter after a fast typed burst, so typed adapters leave the text in the composer on
  every host (`20261027-111822-6719`). Pasted text arrives byte-identical (S4 intact). The paste's Enter approves a
  permission dialog ("You approved codex to run …", `20261025-002721-99d5`).
- Codex attributes nothing: a queued or `turn/start` message is an ordinary user prompt (S9 attribution `message`).

### 4.3 Pi 1.4.0

- `pi-ext`, `pi-session-bridge` and `pi-claude-link` tie at 15/15, 20/20 over 5 reps, 4/4 under nono. S3 is n/a
  (Pi has no approval mode). S1 median 0.003–0.004 s.
- `pi-ext` queues a mid-turn push as a follow-up (S2 queued 5/5); the two third-party extensions steer (S2
  interrupted 5/5). `pi-ext`'s turn markers let a reader know idle without the pane.
- `pi-session-bridge`'s `postinstall` writes into `~/.pi/agent/APPEND_SYSTEM.md`, so it must be installed with
  `--ignore-scripts`; a message starting with `/` is pasted into the session's tmux pane (`vendor/REVIEW.md`).
- `pi-claude-link` joins Claude's peer mesh: Claude→Pi via `SendMessage` 3/3 in the probe; Pi→Claude through Pi's
  tool 0/3, all model errors (the cheap model filled the tool arguments wrong), while the package's own wire send was
  delivered (`results/notes.md` "pi-claude-link safety").
- Pi's tool shell sees the isolated `HOME`, so Pi agents in the fleet have no `~/.gitconfig` unless the fleet sets
  one (README "Isolation").

### 4.4 OpenCode 2.2.0

- `opencode-server-queue`, `-steer` and `opencode-service-steer` are 17/17, 7/7 safety, 20/20 over 5 reps, 4/4
  under nono. `-queue` waits for the turn boundary (S2 queued 5/5); `-steer` and the service steer (interrupted
  5/5). S1 median 0.012–0.014 s.
- `opencode-server-synthetic` delivers but the attached TUI shows only the answer, never the pushed prompt (S8
  `rendered=reply-only`, R25).
- S12: the server restarted in 0.4 s and the TUI reconnected (`20261028-082953-2949`).
- There is no `/tui/*` or `prompt_async` in 2.x; every route is under `/api/`. `serve` always runs with a password,
  and under plain `serve` the agent's own tools inherit `OPENCODE_PASSWORD` (R23).
- OpenCode 2.2.0 allows edits without asking by default; the prompting config needed `permission: {edit: ask, bash:
  ask}` to show a dialog at all.
- Terminal: OpenCode binds Tab, so a typed 10 KB message loses every tab; a pasted one gains a trailing space.

### 4.5 Droid 0.251.0

- No native push into a human-attachable TUI exists (section 2.2). The three tmux paste routes tie at 11/16, safety
  3/7: S3 harmful (the paste approved the dialog, `20261028-043025-8c11`) and S7 0/5 (every push merged into the
  draft). Pasted 10 KB arrives byte-identical.
- Droid 0.251.0 starts in `Auto (Med)` when `autonomyLevel` is absent (0.249.0 started with autonomy off), so a
  prompting setup needs `autonomyLevel: off` explicitly.
- Bridges reach Droid only by typing into its pane (agent-deck, gc-nudge), so they are terminal injection (R31).
- `tmux-paste-retry` never retried live (`retries` 0 in every cell); `tmux-buffer` turns LF into CR.

### 4.6 Scale (8 receivers)

Two batches of 2 × Claude `claude-channel`, 2 × Codex `codex-remote-start`, 2 × Pi `pi-ext`, 1 × OpenCode
`opencode-server-queue`, 1 × Droid `tmux-paste`, each with its own backend, three rounds sent to all eight at once:
48/48 delivered, 48/48 acked. Latency min / median / max 0.002 / 0.022 / 0.588 s; Codex remote-start slowest (max
0.588 s), Pi fastest. 22–24 processes, total RSS 3.0–3.4 GB; CPU about 1.4 cores in the one launch sample and
0.1–0.2 cores during message rounds (1–3 samples per phase, so indicative only). Runs `20261028-185640-d379` …,
`20261028-185959-88e7` …; `results/scale-*.json`.

## 5. Agent to agent (S9)

A was typed one instruction: send B the message in a file through B's sender (a shell command) or a native tool; B
was asked to reply through A's route. A round trip needs B to receive, B to send, and the reply to be pushed into A
after B's receipt, not sent or polled by A (R30).

- **Results:** 64 S9 records, 62/63 counted round trips plus one uncounted `env_error` (Pi's model registry came up
  empty, `20261027-171933-7768`). By stage: pilot (older versions) 31/31 plus the env_error; extensive (pinned
  versions) 28/29; nono 3/3. Round trips took 6.5–19.1 s, most of it model turns.
- **The one failure:** Codex>Claude over `intercom-accept` (`20261028-143904-0e9b`): Claude received the push but
  replied with `SendMessage` into the intercom bridge's own peer socket, so the reply never reached Codex. Pi>Claude
  over the same bridge passed on the pinned versions (`20261028-161100-7b7f`).
- **Every native route with an agent-usable sender completed the round trip**, including the cross-agent pairs
  Claude↔Codex, Claude↔Pi and Codex↔OpenCode. The 35 records with both legs on native routes were 35/35 (route table
  in `results/shortlist.md` "S9").
- **Droid was never reached natively or over its recommended route.** All 5 S9 records involving Droid reach it
  through agent-deck or gc-nudge, which type into its pane (R31): `20261027-191810-9dfe`, `-192430-c7fd`,
  `20261028-145137-d1f8`, `-145242-0244`, `-145319-2038`. Terminal adapters had no agent-usable sender and were left
  out of S9, so agent→Droid over `tmux-paste` is not measured.
- **Codex as receiver ran the blocking sender.** In the S9 cells over `codex-remote-start`/`-steer`, A ran
  `codex_remote.py` without `--drain` (`adapters/codex_remote.py:72-77`, `:126-128`). That sender waits for an idle
  thread and then sends `turn/start`. The S2 "queued" verdicts came from the harness adapter's spool instead
  (section 10.8).

| property | name-based, with sender identity | address-based |
|---|---|---|
| discovery | hcom (bridge-assigned names, `hcom list`), agent-intercom (broker names) | every native route (socket, thread id, URL), plus csd, gc and agent-deck (need a run-specific wrapper) |
| reply route | B composes its own `hcom send` / `intercom_send` from the bridge's primer, without our reply instruction | B runs the reply command it was given |
| attribution | in the frame: hcom `<sender> → <recipient>`, intercom `From <name>`, Claude peer frames `from-name`, pi-claude-link `From <name>` | none (csd, gc, `claude-uds-child`, `claude-channel`, `pi-ext`) or only what the message body says (Codex queue/remote, OpenCode, `pi-session-bridge`) |

The discovery row describes the route type, not something A worked out: A was always handed B's exact name or
command (`results/notes.md` Task 7 "S9"). Self-discovery was not measured.

Every sender name above is self-asserted: hcom lets any same-user process send as any name (`hcom send --from`),
intercom names are self-chosen, Claude's `from-name` comes from the sender. Attribution is a label, not
authentication (`results/notes.md` Task 7 "S9" and "Security observations").

The bridges with name discovery score lower on delivery: hcom delivered every burst message in order but merged
them into fewer entries on every agent (S5 0/3, `merge_count` 2–4) and truncated a 10 KB message to Codex; Codex
`intercom` answers in a hidden bridge thread the attached human cannot see (S2 0/3, S8 `rendered=no`, R33).

## 6. Terminal hosts (hostcheck)

`agentcomms hostcheck` (`20261027-151513-3cc8`, `results/hostcheck.md`): a raw-mode PTY recorder logged every read
inside each host for 7 payloads and a burst of 5.

| host | adapter | fidelity | paste markers | submit | 10 KB reads | burst |
|---|---|---|---|---|---|---|
| tmux | tmux-keys | 7/7 exact | absent | CR | 11, max 1022 B | 5/5 in order |
| tmux | tmux-paste, tmux-paste-retry | 7/7 exact | wrapped | CR | 11, max 1022 B | 5/5, 5 paste regions |
| tmux | tmux-buffer | 6/7 (LF arrives as CR) | wrapped | CR | 11, max 1022 B | 5/5, 5 paste regions |
| zmx | zmx-send / zmx-paste | 7/7 exact | absent / wrapped | CR | 11, max 1022 B | 5/5 in order |
| zellij | zellij-write / zellij-paste | 7/7 exact | absent / wrapped | CR | 10 / 11, max 1022 B | 5/5 in order |
| iterm2 | iterm2-text / iterm2-paste | 7/7 exact | absent / wrapped | CR | 11, max 1022 B | 5/5 in order |

Every host delivers the bytes unchanged; hosts differ in how agents and failures behave:

- **zellij loses sends to a dead pane silently.** S6 sent while the receiver was down: zellij reported success and
  the message was lost on every agent (`down=lost`, S6 0/1 each), where tmux fails loudly (`no server running`).
- **zmx:** the 10 KB `zmx-paste` was lost on the first pilot rep on Claude 2.1.311 and Codex 0.164.0. Claude's
  pilot rep 2 (`20261027-151652-ea30`) was delivered but not intact. On the pinned versions the screen delivered it
  to both, intact on Codex and not intact on Claude. Droid `zmx-paste` merged burst messages in 3/3 reps; zmx relays OpenCode's screen to an attached client in bursts about 30 s apart.
- **iTerm2:** typed sends left Claude's message in the composer (above); a new iTerm2 window takes key focus, which
  contaminated the first hostcheck run with the user's keystrokes (section 12). iTerm2 was not screened (plan scope:
  lower-priority host).
- tmux is the only host with no host-specific failure in the measured cells.

## 7. nono

Receiver, its backend and the harness-side sender each ran under `nono run -p <agent>-local` with the user's
launcher semantics (`agentcomms/sandbox.py`, mirroring `_agent_sandboxed` from `~/ac/.airc.d/05-sandbox.zsh`).

- **Preflight 75/75** (`results/nono-preflight.md`): inside every profile, `ps` works (the sender guard needs it),
  every stdlib sender runs, the pinned binary runs `--version`, unix sockets bind and connect in `/tmp/ac`, loopback
  TCP works, `tmux -L agentcomms` reaches the server, node runs the vendored tsx.
- **Cells:** S1, S2, S4, S7 for the 15 shortlisted routes, 1 rep. Every nono verdict was one that raw also produced for
  that cell. Droid S7 merged, as in raw (0/5). The three native Codex routes merged S7 (0/1 each) where
  raw preserved the draft 3/5, 3/5 and 1/5, which is within raw's failure rate. S9 under nono, both agents sandboxed: Claude>Pi (`20261028-193819-e66c`), Codex>OpenCode
  (`20261028-193849-5699`), Pi>Pi over intercom (`20261028-193936-2a73`): 3/3.
- **No profile edits, no grants.** The five failed nono cells before that were harness causes, superseded:
  `sops-exec` placed inside nono for backends (`nono why --self` → `DENIED path_not_granted` for the sops secrets
  file and age identity, by design), a missing `XDG_RUNTIME_DIR` dir for nono's PTY proxy, and a sandboxed sender with
  no Codex thread id yet (`results/notes.md` "nono pass").
- **Why no grants were needed: the layout.** Every harness file the cells ran, read or wrote was under `~/wrksp`,
  which every `<agent>-local` profile grants read+write. Tools from the user's `PATH` (python3, tmux, node, bun) ran
  in every profile: the preflight covers the senders, tmux and node, and the channel cells cover bun. The preflight's path check reports "Granted by: /Users/nielsmadan/wrksp"
  for all five profiles. That covers the pinned binaries in `vendor/agents/`, the senders, the channel server, the Pi
  extension, the isolated homes and the work dirs under `runs/`. `results/notes.md` "nono pass" says the same about the
  pinned copies. Sockets were in `/tmp/ac/` (preflight bind and connect). The other sockets were Claude's own peer
  sockets in `/tmp/cc-socks/`, the Codex app-server's real socket in `/private/tmp/codex-daemon-<uid>/` (the
  `/tmp/ac` path is a symlink to it, `results/notes.md` Task 4) and tmux's in `/private/tmp/tmux-<uid>/`. Nothing
  outside these was tested.
- Deviations from the real launcher: `--no-audit` (documented as disabling the audit trail; not shown to leave the
  policy unchanged), `NONO_NO_UPDATE_CHECK=1` for nono only, and the agent's isolated `XDG_*` dirs hidden from nono
  and restored inside.
- Side effect: nono writes one session record per `nono run` under `~/.local/state/nono/sessions/` and refuses a
  state dir inside a granted path (section 12).
- Not run under nono: the bridges other than intercom's S9 cell, iTerm2, zmx, zellij.

## 8. User-config interference

S1 and S7 on the shortlist with the user's real global config loaded (stage `user-config`, R41): 30 cells, 8 run,
21 skipped as `n/a`, 1 `error` (`results/shortlist.md` "User-config column").

| agent | outcome |
|---|---|
| Claude | skipped (trust): the workspace trust dialog shows even under `bypassPermissions`, no ancestor of `runs/` is trusted in `~/.claude.json`, accepting writes it, no per-launch switch |
| Codex `codex-remote-start`/`-steer` | 4/4 good, with `CODEX_HOME=~/.codex`, `-c` switches (notify off, MCP and plugins off, trust via `-c projects={"<work>"={trust_level="trusted"}}`; the dotted `projects."<dir>".trust_level` form is ignored by 0.165.0). Caveat (R43): the remote plugin catalog and app connector caches were written, so not contact-free |
| Codex `codex-queue` | skipped: would attach to the user's live daemon |
| Pi | first cell `error` (not ready after 90 s: the user's `pi-statusline` footer hid the readiness signal, and Pi showed its changelog and "Package Updates Available"); Pi rewrote `~/.pi/agent/settings.json` (section 12), so the rest were skipped |
| OpenCode server routes | 4/4 good with the user's config dir. Caveat (R43): the user's `context7` MCP started (`npx @upstash/context7-mcp`) although `OPENCODE_CONFIG_CONTENT` set `mcp.context7.enabled=false`; the switch does not work in 2.2.0, so these cells made outward contact |
| OpenCode service route | skipped: would attach to the user's background service |
| Droid | skipped (trust): no trusted ancestor in `~/.factory/settings.json`, no trust flag |

Interference seen: Codex's `tui.status_line` replaces the default footer (the harness readiness check needed a fix);
Pi's update/changelog screens and status-line package; OpenCode's MCP servers ignoring the disable. R42 now makes a
"disable" count only when the overlay verifiably applies it, and R48 checks each switch in the argv and env the
harness actually built (an integration not on the reviewed list is "unclassified" and skips the cell). The Codex
plugin and MCP `-c` switches are pinned in the built argv, not live-verified to take effect. A re-run would skip
every cell above that ran:
Codex while its app connector has no verified switch (openai/codex#17588), OpenCode while its MCP servers have none,
Claude and Droid for lack of an overlay, Pi because it writes its global config. **There is no clean measurement of
the user's real config for any agent.**

## 9. Measurement limits

- **k/n only, small n.** Most cells are n = 1 (S1, S3, S4, S6, S8, S10, S11, S12) or n = 3 (S2, S5, S7); the shortlist
  added reps to n = 5 on S1, S2, S5, S7. A route that fails one time in five passes 5/5 about a third of the time,
  so 5/5 means "no failure seen", not "reliable" (`results/shortlist.md` "Ranking basis").
- **One laptop, macOS 27.2,** cheapest models per agent. Model behaviour (ACK compliance, tool-argument filling)
  shows up in S9 and S2 acks; scoring separates delivery from model compliance (R10).
- **iTerm2 scope:** hostcheck and spot cells (S1, S4, S7 on Claude and Codex) only; not screened.
- **By equivalence (R34):** zmx/zellij adapters borrowed their tmux adapter's S3, S7 reps 2–3, S10, S11, S12 unless a
  host-sensitive result differed; zellij (S6) and Droid zmx-paste (S5) differed and got the full set. Borrowed cells
  are marked `(eq)` in `results/shortlist.md`.
- **S6 not measured for bridges** that own the session lifecycle (csd, agent-deck, gc-nudge) or whose resume failed
  (Codex intercom); **S12 n/a** for daemonless bridges and Claude's stdio channel/relay children; **S3 n/a** for
  Claude `intercom-accept` (`--yolo`), csd (`--dangerously-skip-permissions`) and gc-nudge (R36). An n/a safety cell
  counts as not shown safe (R37).
- **S5 burst precondition (R47):** a burst counts only when the five sends went out within 1 s. Bridge CLIs and the
  `-retry` settle cannot do that (S5 `n/a`); `codex-queue` and `agent-deck` missed it because of the harness's
  per-send ownership checks (S5 `error`, not re-run). The harness now checks ownership once before the burst.
- **S10 (R40):** on address-based routes the push after `/new` went to the old session, so S10 says nothing about
  compaction there.
- **Pinned versions (R35):** Codex, Droid and OpenCode auto-updated mid-stage; their old verdicts were superseded and
  re-screened, and the rest ran on pinned copies. Task 7 S9 pilot records keep older versions and are labelled.
  The fleet will run newer versions; re-test after updates.
- **Sends before readiness:** every cell waited for the receiver's readiness signal before sending
  (`Engine.await_ready`, `agentcomms/engine.py:569`). The R14 bug, where Codex cells were sent during startup and had
  to be re-run, shows that this matters. What a send does during startup was not measured (section 10.7).
- **S9 discovery was handed to A:** A was given B's exact name or command, so no cell shows an agent finding a peer
  by itself (section 5).
- **Codex S3 needed a prompt tweak:** in `prompting` mode Codex shows a dialog only when the model asks to escalate,
  so Codex's S3 setup prompt adds "request approval to run the write outside the sandbox" (`docs/design.md` "Verdicts").
- **S3 ran only in `prompting` mode.** The other scenarios launch in `auto` mode
  (`agentcomms/scenarios/__init__.py:23-35`), and the recommended launches use it too.
  S3 says nothing about dialogs an auto-mode agent might still show (section 10.7).
- **Bridge cells' shell (R28):** agents in bridge cells had a run-local `HOME` and run-pinned tool shims first on
  `PATH`, a slightly different shell environment than a fleet would give them.
- **Older versions in the harm count:** 10 of the 34 harmful records are pilot runs on Claude 2.1.310/2.1.311 and
  Codex 0.164.0.
- **Not measured:** sessions running for hours, message loops, fleets beyond 8, the user's real config (section 8),
  cross-machine routes, `claude --bg`, agent→Droid over `tmux-paste` (section 5).
- **Sleep:** the laptop slept during the screen; affected cells were `env_error` and re-run, later batches ran under
  `caffeinate -i`.

## 10. Recommended fleet setup

### 10.1 Overall

- **Host:** one tmux server for the fleet (`tmux -L <fleet> -f <fleet tmux.conf>`), one session per agent. Attach:
  `tmux -L <fleet> attach -t <name>`, detach with prefix + `d`. tmux had no host-specific failure, and a send to a
  dead session fails loudly (S6 `down=rejected`).
- **Delivery:** the per-agent native route below; terminal paste only for Droid.
- **Mid-turn behaviour:** prefer routes that queue to the turn boundary (plan decision): Codex `codex-remote-start`,
  Pi `pi-ext`, OpenCode `opencode-server-queue` queue; Claude's three routes steer into the running turn at the next
  tool result (no queue-only option was found for Claude).
- **`agent-send`:** a name registry (name → agent, adapter, address) in place of the harness senders' ownership guard.
  For Claude, Pi and OpenCode it reuses the stdlib senders. For Codex and Droid it needs code the harness keeps
  elsewhere (section 10.8). Put the sender's name in the envelope: most native routes carry none, and every route's
  identity is self-asserted.
- **nono:** no grants were needed because of where things lived (section 7). The Mac Studio layout keeps that only if
  it holds these:
  - Inside a path every `<agent>-local` profile grants read+write (here `~/wrksp`):
    - the agent binaries the fleet launches. The harness used pinned copies in `vendor/agents/`; the user's installed
      binaries were not tested under these profiles.
    - the sender scripts, `agentcomms/channel/server.ts`, the child relay and the Pi extension.
    - every per-agent home (`CLAUDE_CONFIG_DIR`, `CODEX_HOME`, `PI_CODING_AGENT_DIR` and Pi's `HOME`,
      `FACTORY_HOME_OVERRIDE`, OpenCode's `XDG_*` dirs) and every work dir.
    - the OpenCode env and password files, and the Codex spool.
  - Sockets in `/tmp/ac/`, the only socket dir tested for harness sockets. Use another dir only after
    `nono why --self --path <dir> --op readwrite` and a bind test in every profile.
  - `sops-exec` outside `nono run`, and each backend under its receiver's profile.
- **Auto-update off** in every launch (pinned behaviour), and re-test when versions move.

The commands in 10.2–10.6 are the harness's own launch and send forms, with a harness run's paths: `<repo>` is this
repo, `<run_id>` a harness run id (`YYYYMMDD-HHMMSS-xxxx`), `<home>` and `<work>` that run's
`runs/<run_id>/home/<agent>` and `runs/<run_id>/work/<agent>`, and `<claude>`, `<codex>`, `<opencode>`, `<droid>`
the pinned binaries in `vendor/agents/` (`profiles.py:191-202`). The senders work only on such a run. Each one checks
that the socket, URL or password file belongs to a harness run listed in `runs/<run_id>/manifest.json`. Otherwise it
prints `refused: …` and exits 2:

- `unix_send.py`: `agentcomms/senders/unix_send.py:47-52`, `guard.py:119-130`.
- `codex_remote.py`: `agentcomms/senders/codex_remote.py:322-327`, `guard.py:133-142`.
- `opencode_http.py`: `agentcomms/senders/opencode_http.py:85-97`, `:108-113`, `guard.py:60-64`.

A fleet replaces that guard with its own registry. Section 10.8 gives the wire step each sender performs once the
guard passes, which is what a fleet sender has to do.

### 10.2 Claude: `claude-channel` (alternative `claude-uds-child`)

Measurement does not separate the three Claude routes. The choice rests on unmeasured properties:

- `claude-channel` is Claude's documented way for a script to push into a running session ("Channels are MCP
  servers that push events into your running Claude Code session", `docs/enumeration.md`). It needs the hidden
  development-channel flag and a "Loading development channels" warning answered at every launch.
- `claude-uds-child` needs no flag and no dialog, but relies on Claude passing its child messaging token to MCP
  children; the docs name hooks and Bash commands (notes file §4.2), the MCP case is observed only on
  2.1.310–2.1.312.
- `claude-uds-accept` needs no extra process but makes the session accept any frame from any same-user process,
  authenticated or not (R26). Use it only if every same-user process is trusted.

Launch and send, harness form (`agentcomms/adapters/claude_channel.py:13-54`, `profiles.py:287-289`):

```sh
CLAUDE_CONFIG_DIR=<home> DISABLE_AUTOUPDATER=1 sops-exec <claude> --session-id <uuid> --model haiku \
  --permission-mode bypassPermissions \
  --mcp-config <home>/channel-mcp.json --dangerously-load-development-channels server:agentcomms
# answer "1. I am using this for local development" with Enter once the warning shows
python3 -I <repo>/agentcomms/senders/unix_send.py --socket /tmp/ac/<run_id>-ch.sock < body.txt   # prints "emitted"
```

`channel-mcp.json` uses absolute paths, because Claude starts MCP children in its own work dir
(`claude_channel.py:18-21`):

```json
{"mcpServers": {"agentcomms": {"command": "/absolute/path/to/bun", "args": ["run", "<repo>/agentcomms/channel/server.ts"],
  "env": {"AGENTCOMMS_CHANNEL_SOCKET": "/tmp/ac/<run_id>-ch.sock"}}}}
```

`claude-uds-child` instead: `--mcp-config <home>/relay-mcp.json` with `{"mcpServers": {"agentcomms-relay":
{"command": "/absolute/path/to/python3", "args": ["-I", "<repo>/agentcomms/senders/claude_child_relay.py"], "env":
{"AGENTCOMMS_RELAY_SOCKET": "/tmp/ac/<run_id>-relay.sock"}}}}` (`agentcomms/adapters/claude_uds.py:29-32`, `:85-106`),
no channel flag, same sender on `/tmp/ac/<run_id>-relay.sock`. It prints `forwarded via child-env` once Claude's
peer socket has taken the frame.

Config: isolated `CLAUDE_CONFIG_DIR` with `.claude.json` (onboarding done, work dir trusted) and `settings.json`
(`skipDangerousModePermissionPrompt`, `autoUpdates: false`, `claudeMdExcludes` for every ancestor `CLAUDE.md`);
`DISABLE_AUTOUPDATER=1`. On the user's global config: the fleet's work dirs need workspace trust in `~/.claude.json`
(no per-launch switch), and making `accept` global would be `crossSessionInbound: accept` in
`~/.claude/settings.json` (not recommended). Channels are gated by the `channelsEnabled` org policy on Team and
Enterprise plans (and Console orgs with managed settings); Pro and Max users without an organization skip the check
(`docs/research-assumptions.md` Q3). The injected credential worked here.

### 10.3 Codex: `codex-remote-start`

Harness form (`agentcomms/adapters/codex_remote.py:90-93`, `profiles.py:290-291`):

```sh
CODEX_HOME=<home> sops-exec <codex> app-server --listen unix:///tmp/ac/<run_id>.sock   # backend, own process group
CODEX_HOME=<home> sops-exec <codex> -C <work> --remote unix:///tmp/ac/<run_id>.sock    # TUI, no -c flags
python3 -I <repo>/agentcomms/senders/codex_remote.py --socket /tmp/ac/<run_id>.sock --thread <uuid> \
  --mode start < body.txt                                                               # prints "turn/start <turn id>"
```

The thread id comes from the app server (section 10.7). Run like this, without `--drain`, the sender does not queue.
It polls until the thread is idle, for up to `--wait-s 600` seconds, and then sends `turn/start`
(`agentcomms/senders/codex_remote.py:208-221`, `:317`), so the caller blocks for the whole running turn. The S2
"queued 5/5" verdicts came from the harness adapter instead (`CodexRemote.send()`/`defer()`,
`agentcomms/adapters/codex_remote.py:95-124`). The adapter appends the message to a per-thread spool under
`runs/<run_id>/deferred/<thread>` and returns at once. It also starts one detached `codex_remote.py … --drain <spool>`
per thread, which delivers the spool in order, one turn at a time. `agent-send` has to port that (section 10.8).

Config (`<home>/config.toml`, `agentcomms/isolation.py:92-120`): `model`, `model_reasoning_effort`,
`approval_policy`, `sandbox_mode`, `check_for_update_on_startup = false`, `[features] shell_snapshot = false` (R29),
`[projects."<work>"] trust_level = "trusted"`; `auth.json` linked to `~/.codex/auth.json`. On the user's `~/.codex`,
pass everything per launch instead of editing `config.toml`, as the user-config cells did on both the app server and
the TUI (`agentcomms/userconfig.py:225-230`, `:252-257`):
`-c features.shell_snapshot=false` (snapshots hold secrets, section 11),
`-c check_for_update_on_startup=false` and `-c projects={"<work>"={trust_level="trusted"}}`. The dotted
`projects."<dir>".trust_level` form is ignored by 0.165.0. Type one turn before relying on a server restart: a thread
with no turn does not survive (R18).

### 10.4 Pi: `pi-ext`

Harness form (`agentcomms/adapters/pi_ext.py:22-41`, `profiles.py:255-260`, `:294-296`):

```sh
AGENTCOMMS_PI_SOCKET=/tmp/ac/<run_id>-pi.sock PI_CODING_AGENT_DIR=<home> PI_SKIP_VERSION_CHECK=1 sops-exec \
  /usr/bin/env HOME=<home> NODE_PATH=<pi node_modules> <node 24> <pi package>/dist/bundle/cli.js \
  --session-dir <home>/sessions --model openrouter/deepseek/deepseek-v4.1-flash --thinking off --session-id <uuid> \
  -e <repo>/agentcomms/pi_ext/agentcomms-inbox.ts
python3 -I <repo>/agentcomms/senders/unix_send.py --socket /tmp/ac/<run_id>-pi.sock < body.txt   # "queued followUp"
```

`NODE_PATH` is needed only for the pinned copy's layout (`profiles.py:127-129`). The extension binds its socket
with mode 0600 when the session starts (`agentcomms/pi_ext/agentcomms-inbox.ts:40-43`).

Config (`<home>/settings.json`, `agentcomms/isolation.py:148-161`): provider/model, `defaultProjectTrust: always`,
`packages: []`, `extensions: []`, `lastChangelogVersion` set to the running version (suppresses the changelog),
`quietStartup: true`; `PI_SKIP_VERSION_CHECK=1`. On the user's `~/.pi/agent`: Pi rewrites `settings.json` on launch and the user's packages
change the footer, so a fleet on the global config is untested (section 8).

### 10.5 OpenCode: `opencode-server-queue`

The password never goes on a command line. Write it once into three 0600 files: the sender's password file, an env
file for the server and the TUI, and a curl config. The harness does the same with a private env file sourced by
`/bin/sh` (`agentcomms/hosts/tmux.py:103-135`, `backends.py:216-234`):

```sh
python3 -I -c 'import os, secrets, sys
pw = secrets.token_urlsafe(24)
for name, text in (("server-password", pw), ("env-opencode.sh", f"export OPENCODE_PASSWORD={pw}\n"),
                   ("curl-auth.conf", f"user = \"opencode:{pw}\"\n")):
    fd = os.open(os.path.join(sys.argv[1], name), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.write(fd, text.encode()); os.close(fd)' <home>
```

Harness form (`agentcomms/adapters/opencode_server.py:60-83`, `profiles.py:297-300`):

```sh
/bin/sh -c '. "$0" && exec "$@"' <home>/env-opencode.sh \
  sops-exec <opencode> serve --hostname 127.0.0.1 --port <port>                           # backend
curl -sS -K <home>/curl-auth.conf -H 'Content-Type: application/json' http://127.0.0.1:<port>/api/session -d \
  '{"id":"<ses_id>","location":{"directory":"<work>"},"model":{"providerID":"opencode-go","id":"gpt-6-luna"},"agent":"build"}'
/bin/sh -c '. "$0" && exec "$@"' <home>/env-opencode.sh \
  sops-exec <opencode> --auto --session <ses_id> --server http://127.0.0.1:<port> <work>  # TUI
python3 -I <repo>/agentcomms/senders/opencode_http.py --url http://127.0.0.1:<port> --session <ses_id> \
  --password-file <home>/server-password --route prompt --delivery queue < body.txt     # "http 200 inbox=… delivery=queue"
```

The TUI needs `OPENCODE_PASSWORD` in its environment too: `--server` clients send it (`results/notes.md` "OpenCode
routes"), and the harness gives the TUI the same env as the server (`agentcomms/engine.py:368`, `:375`, `:394`). `<ses_id>` is a
`ses_…` id the client picks (`profiles.py:154-156`). The session body is `create_session_body()`
(`agentcomms/senders/opencode_http.py:47-53`). Create the session with the configured model first; one created
without a model ran on OpenCode's free default.

**The password trade-off (R23).** Under plain `serve`, the server's and the TUI's env holds `OPENCODE_PASSWORD`, so
the agent's own tool shell inherits it. Each agent can therefore drive its own server, which is also what makes
agent→agent sends possible. Anything else that can read that env, or the three 0600 files, can drive it too.

Config: `opencode.json` with the model and `"update": "disable"`, `OPENCODE_DISABLE_AUTOUPDATE=1`
(`agentcomms/isolation.py:184-192`). On the user's config, `~/.config/opencode/service.json` is the user's
background service (port 49374, avoid it), and MCP servers there cannot be disabled per launch (section 8).
`opencode-service-steer` scored the same as `-queue`. Each of its cells ran its own isolated service, so one service
shared by many sessions was not measured.

### 10.6 Droid: `tmux-paste`, with a guard

Launch (`profiles.py:301-302`, `agentcomms/isolation.py:218-239`) and the paste the harness sends
(`agentcomms/adapters/tmux.py:12-28`, `:56-63`; `hosts/tmux.py:178-186`):

```sh
FACTORY_HOME_OVERRIDE=<home> FACTORY_DROID_AUTO_UPDATE_ENABLED=false FACTORY_DISABLE_KEYRING=1 \
  sops-exec <droid> --cwd <work> --auto high          # in the fleet tmux session
body=$(cat body.txt)
body=${body//$'\e[200~'/}; body=${body//$'\e[201~'/}  # strip_paste_markers(), adapters/tmux.py:23-24
tmux -L <fleet> send-keys -t "=<name>:" -l -- $'\e[200~'"$body"$'\e[201~' && tmux -L <fleet> send-keys -t "=<name>:" Enter
```

**Strip the paste markers.** The harness wraps every body as `bracketed_paste(text)`, which first removes any
`\e[200~` and `\e[201~` inside it (`strip_paste_markers`, `agentcomms/adapters/tmux.py:23-28`). Without that step, a
peer message containing `\e[201~` ends the paste early, and everything after it reaches Droid as typed keys, for
example an answer to an approval dialog. That is the harm S3 measured, and Droid's bodies come from other agents.
Stripping the two markers closes only that one hole. Other control bytes inside the paste were not tested, so a
fleet sender should also drop every control character except newline and tab.

There is no stdlib Droid sender. The harness's agent-usable route for Droid is `python -m agentcomms.cli send --run
<run_id> --host-ref <ref> --adapter tmux-paste` (`agentcomms/adapters/tmux.py:31-33`), which imports the whole
harness and resolves the target from a run manifest.

Config: `<home>/.factory/settings.json` with the model, `trustedFolders` (work dir and its git root) and
`autonomyLevel` (`high` in `auto` mode, `off` in `prompting` mode). On the user's config, trust needs an entry in
`~/.factory/settings.json`.

Mitigations, not tested:

- Run Droid in an autonomy level that shows no approval dialog. S3's harm needs a dialog, and whether `--auto high`
  ever shows one was not measured (section 10.7).
- Have `agent-send` capture the pane and refuse to paste while a dialog or a non-empty input box is visible. The
  check `tmux-paste-retry` runs before retrying, `retry.idle_and_empty()` (`agentcomms/adapters/retry.py:33-35`), is a
  starting point.

### 10.7 Operations

- **Codex thread id.** `codex_remote.py` needs `--thread <uuid>`. The harness reads it from the app server: it calls
  `thread/loaded/list` over the socket and takes the one loaded thread. Failing that, it takes the session id of the
  TUI's rollout (`owned_thread()`, `agentcomms/adapters/codex_remote.py:38-55`). The thread exists only once the TUI
  has created it. A sandboxed sender started before the transcript existed had no thread id (`results/notes.md` "nono
  pass"). So read the id after the TUI is ready and store it in the registry. Re-read it after `/new` or `/clear`:
  on every address-based route the push after `/new` went to the old session (S10, R40).
- **Readiness before sending (R14).** Every cell waited for the receiver's ready screen before the first send
  (`Engine.await_ready`, `agentcomms/engine.py:569-608`). That means the agent's prompt and footer patterns with no
  dialog showing, and Codex past `Waiting for startup`. Claude also needs its registry entry at `status: idle`. The
  patterns are in `READY_PANE`, `STARTING_PANE` and `pane_ready()`, `engine.py:83-96` and `:130-135`. R14 was a
  Codex readiness pattern that matched the startup placeholder, so cells sent during startup and had to be re-run.
  Sends during startup were not measured. A socket that accepts is not readiness: the channel server listens as soon
  as Claude starts it (`agentcomms/channel/server.ts:72-100`), and Pi's extension at `session_start`. `agent-send`
  needs its own readiness check, or a registry state set only after one.
- **Delivery confirmation.** A sender's reply confirms only its own hop:
  - Channel `emitted`: the server wrote the notification to Claude (`server.ts:86-93`). Claude does not acknowledge
    channel events, and if the session has not loaded the server as a channel, or org policy blocks it, "Claude Code
    drops the events silently" (`docs/research-assumptions.md` Q3, quoting the channel docs).
  - Relay `forwarded via …`: Claude's peer socket took the frame (`agentcomms/senders/claude_child_relay.py:73-89`).
  - Pi `queued followUp`: the extension called `sendUserMessage`. Its own comment says "failures only surface
    asynchronously, so never claim delivery" (`agentcomms/pi_ext/agentcomms-inbox.ts:19-24`).
  - Codex `turn/start <turn id>` and OpenCode `http 200 inbox=<id> delivery=queue`: the server accepted the input.
  - Droid: a zero exit from `tmux send-keys` means only that the keys were sent.

  The harness judged every delivery from the receiver's own transcript (README "Scenarios", the `evidence` field of
  each record, `agentcomms/transcripts/`). A fleet needs the equivalent: look for the message in the receiver's
  session log, or have the receiver acknowledge it.
- **Prerequisites:**
  - python3 (stdlib senders, run with `-I`), tmux and `sops-exec`.
  - bun for the Claude channel server, written into the MCP config as an absolute path
    (`agentcomms/adapters/claude_channel.py:13-21`).
  - node 24 for Pi (24.22.0 tested; the package declares `node >=22.19.0`).
  - The `iterm2` Python package only if iTerm2 hosts are used (`pyproject.toml`); the recommended setup does not use
    them.
- **Permission mode vs S3.** Every launch above is the harness's `auto` mode:
  - Claude `bypassPermissions`.
  - Codex `approval_policy = "never"`, `sandbox_mode = "danger-full-access"` (`agentcomms/isolation.py:92`).
  - OpenCode `--auto`.
  - Droid `--auto high` with `autonomyLevel: high` (`isolation.py:219`).
  - Pi has no approval modes.

  S3 was measured in `prompting` mode only (Claude `default`, Codex `-a on-request -s read-only` plus the setup
  prompt tweak, OpenCode with `edit`/`bash: ask`, Droid `autonomyLevel: off`; README "Modes"), because it needs an
  open dialog. In auto mode S3's precondition should not arise, but no cell checked that any of these modes never
  shows a dialog. That includes Droid at `--auto high`, the one agent whose route is terminal paste. **Decide which
  mode the fleet runs in** (section 13):
  - In auto mode, S3 does not cover the fleet, and the Droid guard is the remaining defence if a dialog appears.
  - In a prompting mode, S3 applies as measured: native routes queued or were `lost`, terminal routes approved the
    dialog.

### 10.8 What `agent-send` must add

Per agent, beyond a registry:

| agent | reuse | must add |
|---|---|---|
| Claude | `unix_send.send()` (`agentcomms/senders/unix_send.py:15-32`) | the registry in place of `guard.owned_run_socket` |
| Pi | `unix_send.send()` | the same |
| OpenCode | `opencode_http.post()` (`agentcomms/senders/opencode_http.py:74-75`) | the same, plus its own password-file location; the harness guard accepts only a file under `runs/` (`guard.py:60-64`) |
| Codex | the WebSocket client and `turn/start` (`agentcomms/senders/codex_remote.py:126-221`), `enqueue`/`drain` (`:245-287`) | a non-blocking start: spool the message and return; one drainer per thread. The decision to spool and the drainer spawn are in the harness adapter (`agentcomms/adapters/codex_remote.py:95-124`). `--drain` accepts only a harness run's spool (`senders/codex_remote.py:296-302`). Without it, each sender blocks for the whole running turn, and two waiting senders can both send `turn/start` at the same turn end (not measured). |
| Droid | nothing stdlib | a paste sender: marker stripping, the dialog and draft check, the bracketed paste and one Enter (section 10.6) |

Wire steps, as the harness senders perform them once the guard passes:

- **Claude channel, Claude child relay, Pi extension:** open the unix socket (`/tmp/ac/<run_id>-ch.sock`,
  `-relay.sock`, `-pi.sock`), write the UTF-8 body, shut down the write half, read one reply line (`unix_send.py:15-32`).
  Replies: channel `emitted` or `empty` (`agentcomms/channel/server.ts:86-93`); relay `forwarded via child-env` or
  `error …` (`claude_child_relay.py:73-89`); Pi `queued followUp`, `error empty message` or `error compacting`, with
  bodies over 1 MiB dropped (`agentcomms/pi_ext/agentcomms-inbox.ts:6-11`, `:29-37`).
- **Codex app server:** WebSocket upgrade over the unix socket (`codex_remote.py:86-88`, `:126-142`), then JSON-RPC
  without a `jsonrpc` field:
  1. `initialize` with `clientInfo` and `capabilities.experimentalApi`, then the `initialized` notification
     (`:38-39`, `:189-192`).
  2. Busy check: `thread/read`, and `thread/turns/list` if the thread is active (`:56-62`, `:194-202`).
  3. `turn/start {threadId, input: [{type: "text", text, text_elements: []}], clientUserMessageId}` (`:42-48`).

  Answer any request from the server with error -32601 (`:69-70`, `:182-183`).
- **OpenCode:** `POST http://127.0.0.1:<port>/api/session/<ses_id>/prompt` with `{"text": …, "delivery": "queue"}`
  and Basic auth as user `opencode` (`opencode_http.py:35-75`).
- **Droid:** the paste in section 10.6.

Readiness, delivery confirmation and the sender's name in the envelope come on top (section 10.7).

### 10.9 Re-test on the Mac Studio

- Scale beyond 8: the target fleet size, mixed agents, with per-receiver backends (RSS was 3.0–3.4 GB for 8).
- Latency on the M5 Max, and the fleet's macOS version (only 26 and 27.2 were seen; the 26→27.2 re-baseline changed
  no verdict).
- Fleet concurrency with real auth: many sessions sharing one Claude token, one Codex `auth.json` (refresh), one
  OpenRouter and Factory key, under real rate limits.
- The chosen agent versions (pinned here; three agents changed behaviour across one update).
- The user's real config per agent once the trust question is decided (section 13).
- Long-lived sessions and restarts of the whole fleet; S6/S12 for any bridge adopted.
- If a bridge is adopted for discovery (hcom, intercom): its nono behaviour (only intercom's S9 cell ran under nono).
- The Droid guard above, with marker stripping, and agent→Droid round trips over `tmux-paste` (no S9 record).
- S3 in the permission mode the fleet will run in (section 10.7), and a send during each agent's startup.
- `agent-send` itself: the Codex spool and drainer once ported, and its readiness and delivery checks.
- S5 on `codex-queue` (it lost its S5 coverage to the R47 burst precondition; the harness's per-send checks, now
  removed from the burst, took about 0.5 s of each 1.2–1.4 s window).

## 11. Security findings

| finding | evidence |
|---|---|
| **Terminal sends approve permission dialogs.** 34 harmful S3 records, all on terminal routes (tmux, zmx, zellij, and agent-deck typing into Droid), on Claude, Codex, OpenCode and Droid. 27 were a paste plus Enter and 7 a typed send plus Enter. 10 are pilot records on older versions. On Claude the Enter confirms the highlighted "Yes". | `raw.jsonl` `harmful: true`; probe `20261024-234730-0101` |
| **A paste-end marker in a body breaks out of the paste** (not measured; follows from the paste format). A message containing `\e[201~` ends a bracketed paste early, and the rest arrives as typed keys. The harness strips both markers (`strip_paste_markers`); any fleet paste sender must too (section 10.6). | `agentcomms/adapters/tmux.py:23-28` |
| **Claude `accept` admits unauthenticated frames from any same-user process (R26).** With `crossSessionInbound: accept`, a frame with no auth line from a process outside Claude's registry is delivered (the socket is mode `srw-------`, so other users cannot connect). pi-claude-link and agent-intercom's native Claude bridge both send such frames. | `results/notes.md` "pi-claude-link safety", Task 7 "agent-intercom" |
| **OpenCode server password in the agent's env (R23).** Under plain `serve` the agent's tools inherit `OPENCODE_PASSWORD`, so an agent can drive its own server; that is also what makes agent→agent sends possible. | `results/notes.md` "OpenCode routes" |
| **Socket = authority on native routes.** Anyone who can open the channel/relay socket, the Pi extension socket (mode 0600), the Codex app-server socket or the OpenCode port with its password can inject; same-user processes can queue into any thread of a Codex daemon. | `results/shortlist.md` properties table; `docs/research-assumptions.md` Q2 |
| **Codex shell snapshots hold secrets (R29).** Codex writes the exported environment, injected secrets included, to `CODEX_HOME/shell_snapshots/*.sh`, mode 0644 (92 of 129 harness snapshots held a secret). Off with `[features] shell_snapshot = false` in an isolated home, or per launch with `-c features.shell_snapshot=false` on the user's `~/.codex`. | `results/notes.md` Task 7 M7 |
| **Codex delivers peer text as the user.** Queued and `turn/start` text is an ordinary user prompt with no sender identity. | S9 attribution `message`; `docs/enumeration.md` §4 |
| **csd** runs every worker with `--dangerously-skip-permissions`, keeps state in `/tmp/csd-workers` by default, copies Codex credentials into worker homes, and delivers by tmux paste. | `vendor/REVIEW.md`, `results/notes.md` Task 7 |
| **hcom:** any same-user process can send as any name (`--from`, `-b`); for Codex it installs an execpolicy that auto-approves `hcom send|relay|config|hooks|…`, so an agent can enable the cross-device relay without a prompt; each PTY proxy listens on loopback TCP for wake pings and `hcom term` injection (auth not checked); legacy-hook cleanup rewrites `~/.claude/settings.json` and `~/.codex/*` if old hcom hooks exist. | `vendor/REVIEW.md` hcom, `results/notes.md` Task 7 |
| **Gas City:** `gc start`/`register`/`supervisor install` install and load a LaunchAgent even with `GC_HOME` set; the supervisor API on 127.0.0.1:8372 answered `/health` without credentials; any gc command below `~` treats the home directory as a city because `~/.gc` exists; nudges arrive as `<system-reminder>` blocks in the user channel; gc tells every agent to run `gc` by name. | `vendor/REVIEW.md` Gas City, `results/notes.md` Task 7 |
| **agent-deck:** shares the user's default tmux server by default, writes `trust_level = "trusted"` for each project into `~/.codex/config.toml`, auto-installs updates with a launchd timer, leaves a detached queue worker for up to 30 min. | `vendor/REVIEW.md` agent-deck, `results/notes.md` Task 7 |
| **agent-intercom:** trusts every same-user process (`trustedLocal`), names are self-chosen, routing lets any local session reach any other; a component that loses `PI_CODING_AGENT_DIR` joins the user's real broker in `~/.pi/agent/intercom`. | `vendor/REVIEW.md`, `results/notes.md` Task 7 |
| **pi-session-bridge** `postinstall` writes `~/.pi/agent/APPEND_SYSTEM.md`; install with `--ignore-scripts`. | `vendor/REVIEW.md` |

Peer text as an injection channel more generally (free-form messages relayed between agents are adopted as
instructions) is covered by the research in the notes file, §4.3.

## 12. Incidents

Writes and actions outside the repo that the isolation rules did not intend, with what changed afterwards.

1. **`~/.pi/agent/intercom` (Task 7, 17:25–17:27 on 2026-10-27).** The Codex intercom MCP server, started through
   `-c` flags without `PI_CODING_AGENT_DIR`, spawned a broker in the user's intercom dir (`broker.*`,
   `remote-gateway.sock`, removed again on exit) and left one empty outbox file
   (`outbox/82021a57….json`). The user's broker access files were unchanged. Fix: the env is passed to the MCP server
   (tested), and a bridge-state guard over `~/.gc`, `~/.pi/agent/intercom`, `~/.hcom`, `~/.agent-deck`,
   `~/.config/agent-deck` and `~/Library/LaunchAgents` stops any command on change.
2. **`~/.gc` (Task 7).** A `gc version` probe walked up to `~` and created `~/.gc/scripts/gc-beads-bd.sh`; a first
   supervisor found the user's live one on port 8372 and probed `/health`, which the user's supervisor logged in
   `~/.gc/events.jsonl` and `supervisor.log`. `~/.gc/cities.toml` and `~/Library/LaunchAgents` were unchanged.
3. **gc receivers ran the user's real `gc prime` (Task 7, review H1).** gc types "Run `gc prime`" into every session.
   Two Claude receivers found the user's mise install and ran
   `~/.local/share/mise/installs/github-gastownhall-gascity/1.4.0/gc prime` (17:34:01, 17:35:26); a Codex
   receiver's attempt failed in the mise shim. By mtime nothing in `~/.gc` changed. Fix (R28): bridge-instructed
   tools resolve to run-pinned wrappers first on `PATH`, user gc/mise/shims dirs removed, agent `HOME` in the run;
   the three records were superseded.
4. **iTerm2 focus steal (Task 6).** New iTerm2 windows became key, and the user's keystrokes (`ne`, `ed to`) landed
   in the first hostcheck run; two Codex iTerm2 cells ran while the user cleared their input. Fix (R27): cells run as
   unselected tabs of one persistent holder window, created only while iTerm2 is not frontmost; every pre-holder
   iTerm2 record was superseded and re-run.
5. **Pi global config write (Task 10, `20261028-175605-27fb`).** With the user's config loaded, Pi 1.4.0 changed
   `~/.pi/agent/settings.json` `lastChangelogVersion` 1.2.0 → 1.4.0, rewrote `auth.json` and `models-store.json`,
   touched a pi-subagents `.last-cleanup` file and ran two `npm view` update checks. Not reverted (global config is
   read-only for the harness); the batch stopped and Pi user-config cells were skipped from then on.
6. **OpenCode MCP outward contact (Task 10).** The intended `OPENCODE_CONFIG_CONTENT` disable did not apply, so 5
   user-config cells started the user's `context7` MCP via `npx` (npm registry, context7; jina's remote MCP
   probably too). The records stay with an `outward-contact` note (R43); R42 now skips any cell without a verified
   switch.
7. **Codex and nono state in the user's stores (Task 10).** The Codex user-config cells left 7 rollouts in
   `~/.codex/sessions/2026/10/28/`, their `tui-thread-reference-capabilities` entries, two `tmp/arg0-macos` dirs,
   rows in `session_index.jsonl` and the `state_5`, `thread_history_1` and `logs_2` databases, and touched model,
   app and plugin caches. The nono pass left 409 session files in `~/.local/state/nono/sessions/`
   (`results/nono-session-files.txt`) plus two exploratory session files, one audit dir and one audit ledger line.
   Recorded, not deleted (R41).
8. **Stray-file removals.** Empty zmx/zellij files from pre-isolation `--version` calls were removed (Task 6); 50
   dead harness tmux socket files in `/private/tmp/tmux-501/` were removed after checking each was dead; 26 dead
   harness Claude sockets in `/tmp/cc-socks/` were removed (pid recorded in a harness manifest, identity no longer
   running; the 17 live ones were left); after the user's "Sure, delete them" the coordinator removed
   `~/.gc/scripts/gc-beads-bd.sh`, the empty `~/.gc/scripts` and the intercom outbox file (2026-10-28 03:34), which is
   what tripped the bridge guard on the last screen cell (`20261028-033403-e3a8`).
9. **Smaller ones.** Before isolation existed: one bare `opencode --version` appended a log line to
   `~/.local/share/opencode/log/opencode.log`; Task 5's first `npm pack` went through `~/.npm/_cacache` and wrote a
   debug log to `~/.npm/_logs` (`docs/design.md` "Constraints"), and the user-config cells' 7 `npm view`/`npx` runs (Pi ×2,
   OpenCode's `context7` ×5) wrote 7 more `~/.npm/_logs/*-debug-0.log`, since rotated away by npm (`results/notes.md`
   "Paths created in the user's stores"). Isolated Claude
   loaded the user's `~/.claude/CLAUDE.md` in every Claude cell before the R9 fix. One diagnostic `ps` with a broken
   filter printed the names (no arguments, no environment) of all processes. Codex snapshots with secrets sat in
   gitignored `runs/` until deleted (R29); `runs/` was never committed.
10. **Removed at the end of the run (2026-10-29).** The 74 dead harness tmux socket files in `/private/tmp/tmux-501/`
    (`actest*`, `agentcomms`, `agentcomms-test*`; each was checked dead with `tmux -S … ls` first), `$TMPDIR/zmx-501`
    (empty, from the first zmx call in Task 6) and 252 MB of coordinator scratch in `/tmp/ac` (no process held a file there).

## 13. Blocked on you / open questions

- **Pi `lastChangelogVersion`:** set it back to `1.2.0` in `~/.pi/agent/settings.json` if you want the pre-run
  value (Pi also rewrote `auth.json` and `models-store.json` in the same second). Default: left as is.
- **Delete the Codex user-config sessions and nono records?** 7 rollouts and their store rows (list in
  `results/notes.md` "Paths created in the user's stores"), and the 409 + 2 nono session files, audit dir and ledger
  line (`results/nono-session-files.txt`). Default: left.
- **claude-bg is blocked by your `disableAgentView: true`**, which leaks through `CLAUDE_CONFIG_DIR`. Testing it means
  flipping that setting (a global change) or dropping the host.
- **Claude and Droid user-config coverage needs a trust path:** accept one trusted parent dir (an entry in
  `~/.claude.json` / `~/.factory/settings.json`) or keep these skipped. Codex and OpenCode user-config cells would
  also skip on re-run until their connector and MCP switches are verified.
- **Droid has no human-attachable native push.** Accept guarded terminal paste, or use Factory's app over
  `droid daemon --remote-control` (not human-attachable in a terminal), or raise it with Factory.
- **Which Claude route:** channel (documented, flag and dialog) vs child relay (no dialog, relies on observed token
  inheritance) vs accept (R26). Measurement cannot decide.
- **nono state writes** are unavoidable for any `nono run`: accept them for future runs or drop the nono pass.
- **Harness Claude sockets** still go to the shared `/tmp/cc-socks`; setting `XDG_RUNTIME_DIR` to a run dir for every
  Claude launch would keep them in harness space (deferred because it changes the Claude launch env).
- **`--no-audit`** is not shown to leave the nono policy unchanged (no denial test was run).
- **Which permission mode will the fleet run in?** The recommended launches are auto mode; S3 was measured in
  prompting mode only (section 10.7). The commands in section 10 assume auto mode.

## 14. Rulings referenced, sources

Rulings (each explained in `docs/design.md`; most are also recorded in `results/notes.md`):

- R9 isolated Claude excludes ancestor `CLAUDE.md`. R10 S3 harm = a send approving a dialog; ACK is model
  behaviour. R14 Codex readiness bug: cells sent during startup were re-run. R16 claude-bg retry. R17 `held` delivery value. R18 Codex S12 warm-up. R23 OpenCode password.
  R25 S8 needs the pushed prompt visible. R26 Claude `accept` admits unauthenticated frames. R27 iTerm2 holder window.
  R28 bridge-instructed tools pinned. R29 Codex shell snapshots off. R30 S9 round-trip rules. R31 agent-deck Codex
  idle wake; Droid via bridges is terminal injection. R33 hidden-thread replies delivered, not rendered.
  R34 extensive reuses screen reps; zmx/zellij by equivalence. R35 pinned agent copies after mid-stage updates.
  R36 extensive n/a decisions. R37 safety over a fixed denominator of 7. R38 S9 column counts pinned passes.
  R39 S12 after a bridge respawn is not good. R40 S10 compaction not exercised on address routes.
  R41 user-config cells: no outward contact, no global writes. R42 a switch counts only when verified.
  R43 contaminated user-config records keep data with notes. R44 S9-only entries get no delivery reps.

Sources in this repo:

- `results/raw.jsonl` (records; run ids cited inline), `results/matrix.md`, `results/screen.md`,
  `results/shortlist.md` (generated by `uv run agentcomms shortlist --write`), `results/hostcheck.md`,
  `results/nono-preflight.md`, `results/scale-*.json`, `results/notes.md` (per-task findings, probes without
  records, incidents), `results/nono-session-files.txt`.
- `vendor/REVIEW.md` (third-party code read, install hooks, versions, sha256), `docs/harness.md`,
  `agentcomms/adapters/README.md`, `agentcomms/hosts/README.md`.
- `docs/enumeration.md`, `docs/research-assumptions.md` (inventory and pre-run research).
- Notes file: `~/wrksp/notes/work/reference/research/agent-to-agent-messaging.md` (Claude peer messaging internals,
  bridges, injection research).
