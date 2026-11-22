# Injection into live interactive coding-agent sessions: additions (2026-10-21)

Pre-run inventory. What was tested and what each option measured is in `REPORT.md` (inventory and matrix). The
OpenCode `/tui/*` and `prompt_async` routes listed below do not exist in the 2.0.32 or 2.1.4 source (`results/notes.md`
"OpenCode routes (from source)").

Legend: stars/last push from `gh repo view` today unless noted. "unverified" = not confirmed from a primary source this session (README/docs/source/issue read). Agents: CC=Claude Code, CX=Codex, PI=Pi, OC=OpenCode, DR=Droid.

## 1. Terminal / PTY drivers

| name | URL | mechanism | agents | human attach? | maintenance | notes |
|---|---|---|---|---|---|---|
| microsoft/tui-test | https://github.com/microsoft/tui-test | Test harness: spawns program in its own PTY; CLI `tui-test run PROGRAM` plus Python/JS/Rust/Go in-process APIs with type/send/assert actions (README) | any TUI (agent-agnostic) | No documented attach. It is a test runner that owns the PTY, not a session host. Human attach: unverified/likely no | 293 stars, push 2026-10-21 | Good for driving, poor for hosting a human-visible long-lived session |
| remorses/tuistory | https://github.com/remorses/tuistory | Named background PTY sessions; agent commands read/snapshot/wait/type; `tuistory attach` for humans (README: "tmux for agents") | any TUI | Yes, `tuistory attach` (humans only) | 367 stars, push 2026-10-13 | Closest tui-test alternative that IS attachable. Not tested against the 5 agents |
| neurosnap/zmx | https://github.com/neurosnap/zmx | Session attach/detach daemon. `zmx run <name> [-d] <cmd>` "send command without attaching"; `zmx attach`; plain-text scrollback print (README) | any TUI | Yes (`zmx attach`, ctrl+\ detach) | 2,223 stars, push 2026-10-21 | Minimal, active, scriptable send. Fits "host agent, inject, human attaches". `run` semantic is command-oriented; behaviour inside a TUI composer unverified |
| shell-pool/shpool | https://github.com/shell-pool/shpool | Persistent named sessions via daemon; `shpool attach/detach` | any | Yes | 2,019 stars, push 2026-10-19 | README shows no send-text API (only attach). Injection would need writing to the PTY some other way. Weak for injection |
| tmux (send-keys, paste-buffer, load-buffer, pipe-pane -I) | https://github.com/tmux/tmux | CLI/ctl socket | all 5 | Yes | 49,969 stars, push 2026-10-21 | Baseline (already known). Codex issue #15355 documents its failure modes (races with typing, draft vs submit) |
| tmux control mode `-CC` | https://github.com/tmux/tmux/wiki/Control-Mode | Line protocol over stdin/stdout; `send-keys` commands plus `%output` notifications | all 5 | Yes (other clients attach in parallel) | active | Used by Open330/amux to project panes into Ghostty. Better event stream than polling capture-pane |
| libtmux | https://libtmux.git-pull.com/quickstart | Python wrapper, `Pane.send_keys()` | all 5 | Yes | docs v0.62.0 (current) | Library form of tmux send-keys |
| GNU screen `-X stuff` | https://www.gnu.org/software/screen/ | `screen -S s -X stuff "text\r"` | all 5 | Yes | stable, slow-moving | unverified for current agents; same race issues as tmux |
| Zellij | https://github.com/zellij-org/zellij | `zellij action write-chars`, `write`, `zellij pipe` (plugin messaging) | all 5 | Yes (`zellij attach`) | 35,801 stars, push 2026-10-21 | write-chars/pipe from my knowledge, not re-read this session (unverified in docs). rz-cli builds agent messaging on it |
| rz-cli | https://lib.rs/crates/rz-cli | Agent-to-agent messaging over Zellij panes; hub mode via `rz-hub` WASM plugin and `zellij pipe`; `rz spawn --name X -p prompt claude` | CC confirmed in example; others unverified | Yes (it is Zellij panes) | crates.io 1.0.1, 2 versions. "experimental" per its page | Needs Zellij 0.42+ |
| stanislc/zellij-claude-teams | https://github.com/stanislc/zellij-claude-teams | tmux shim translating tmux commands to zellij actions (writes to FIFO) so Claude Code Agent Teams run in Zellij | CC | Yes | 42 stars, push 2026-09-15 | Shows CC teammate spawning relies on tmux CLI semantics |
| WezTerm `wezterm cli send-text` | https://wezterm.org/cli/cli/send-text.html | "Send text to a pane as though it were pasted" (docs); `--pane-id`, `--no-paste` | all 5 | Yes (GUI/mux) | 29,304 stars, push 2026-10-19 | Paste semantics help multiline; need a separate Enter for submit (unverified per agent) |
| kitty `kitten @ send-text` | https://sw.kovidgoyal.net/kitty/remote-control | Remote control socket; `--match` by title/cmdline/etc. (docs snippet) | all 5 | Yes | 35,385 stars, push 2026-10-22 | Requires `allow_remote_control` / `listen_on` |
| Ghostty AppleScript `input text` / `send key` | https://ghostty.org/docs/features/applescript | macOS AppleScript dictionary: paste-style `input text "..." to terminal`; `send key` (docs snippet; introduced in 1.3.0 per a third-party note, unverified) | all 5 | Yes | 62,487 stars, push 2026-10-21 | Gives non-tmux Ghostty an official injection API. Open issue #11457: AppleScript new window/tab activates Ghostty |
| iTerm2 Python API `async_send_text` | https://iterm2.com/python-api | already known | all 5 | Yes | - | - |
| cmux (manaflow-ai) socket API | https://github.com/manaflow-ai/cmux | Ghostty-based macOS terminal; "CLI and socket API to ... send keystrokes" (README) | all 5 (agent-agnostic terminal) | Yes (it is the terminal) | 28,332 stars, push 2026-10-22 | Also `cmux claude-teams`. Different from craigsc/cmux (604 stars) |
| amantus-ai/vibetunnel (`vt` / `vibetunnel fwd`) | https://github.com/amantus-ai/vibetunnel | Forwards a terminal session to a browser over WebSocket | all 5 | Yes (browser + local) | 4,695 stars, push 2026-08-05 | Browser input goes into the PTY; programmatic inject API: unverified |
| microsoft/node-pty | https://github.com/microsoft/node-pty | In-process PTY fork; you own master fd | all 5 | Only if you build your own attach layer | 2,052 stars, push 2026-10-22 | Used by ccmanager/crystal-style apps; no external attach by itself |
| pexpect | https://github.com/pexpect/pexpect | Python PTY expect | all 5 | No (own PTY) | 2,856 stars, last push 2025-04-11 | Low activity |
| dtach (crigler) | https://github.com/crigler/dtach | socket; `dtach -p` pushes stdin to a session | all 5 | Yes (`dtach -a`) | 751 stars, last push 2025-06-21 | Tiny, stable, no screen redraw state |
| abduco | https://github.com/martanne/abduco | similar to dtach | all 5 | Yes | 991 stars, last push 2023-01-18 | Effectively unmaintained |
| tmux-mcp servers | https://github.com/howardpen9/tmux-bridge-mcp (104 stars, push 2026-10-21); https://github.com/nickgnd/tmux-mcp (306, 2026-02-14) | MCP tools wrapping tmux send/read | CC, CX, Gemini, Kimi named for tmux-bridge-mcp (README) | Yes | see left | Lets one agent type into another's pane |
| Open330/amux (+ muxa) | https://github.com/Open330/amux | tmux `-L amux` server, tmux -CC into native Ghostty surfaces; "Send text to a workspace over the socket; it lands in the session's active pane, no attach, no focus steal" (README) | CC, CX, Gemini hooks named | Yes (`tmux -L amux attach`) | 1 star, push 2026-10-21 (brand new) | Concept matches the goal exactly; very young |

## 2. Fleet runners / session multiplexers

| name | URL | mechanism | agents | human attach? | maintenance | notes |
|---|---|---|---|---|---|---|
| asheshgoplani/agent-deck | https://github.com/asheshgoplani/agent-deck | tmux sessions. `agent-deck session send <proj> --message-file` ; TUI `o` composer. README: "Queueing uses native Claude/OpenCode 2 queueing where available and waits for the current turn to finish on other commands"; OC2 queueing "uses its session API ... unconfirmed delivery is reported without retrying or falling back to terminal keys" | CC, OC2 (native queue); also Codex, Pi, Gemini (fork support listed); Droid unverified | Yes (Enter attaches) | 1,138 stars, push 2026-10-21 | Best-in-class model: uses native queue APIs for CC/OC, falls back to wait-for-idle for others. Worth reading source for the CC native queue path |
| smtg-ai/claude-squad | https://github.com/smtg-ai/claude-squad | tmux per session + worktrees | CC, Codex, Gemini, OpenCode, Amp (README) | Yes | 8,642 stars, push 2026-08-20 | Prompt send mechanism (send-keys) assumed, unverified |
| kbwo/ccmanager | https://github.com/kbwo/ccmanager | Own PTY, no tmux ("completely self-contained") | CC, Gemini, Codex, Cursor, Copilot, Cline, OpenCode, Kimi (README) | Yes within its TUI only | 1,267 stars, push 2026-10-18 | No external inject API seen in README |
| raine/workmux | https://github.com/raine/workmux | git worktree + tmux windows (also zellij/kitty/etc. backends) | agent-agnostic | Yes | 2,915 stars, push 2026-10-17 | Send mechanism unverified |
| devflowinc/uzi | https://github.com/devflowinc/uzi | tmux window per agent, `uzi prompt` | claude, codex | Yes | 582 stars, last push 2025-06-04 | Stale |
| BloopAI/vibe-kanban | https://github.com/BloopAI/vibe-kanban | Spawns agents as subprocess (structured/stream, not tmux) per README claims; follow-up via its UI | CC, Codex, Gemini, Copilot, Amp, Cursor, OpenCode, Droid, CCR, Qwen | Via its web UI, not TUI | 28,425 stars, push 2026-09-19 | Droid is listed as supported. Mechanism details unverified |
| generalaction/emdash | https://github.com/generalaction/emdash | Desktop app, runs agent CLIs in worktrees | CC, Codex, OpenCode, Amp, Cursor, Devin, Qwen, Droid, Copilot (README) | Yes in-app terminal | 6,049 stars, push 2026-10-20 | Mechanism unverified |
| stravu/crystal (now Nimbalyst) | https://github.com/stravu/crystal | Electron + node-pty | CC, Codex | in-app | 3,134 stars, last push 2026-02-26 | Superseded |
| coder/xum (renamed from mux?) | https://github.com/coder/xum | desktop app, isolated parallel agents | unverified | - | 2,057 stars, push 2026-10-22 | I resolved `coder/mux` to `coder/xum`; unverified rename |
| imbue-ai/sculptor | https://github.com/imbue-ai/sculptor | containerised agents | unverified | - | 240 stars, push 2026-10-21 | unverified |
| winfunc/opcode | https://github.com/winfunc/opcode | Tauri GUI wrapping Claude Code | CC | GUI only | 22,417 stars, push 2026-09-18 | - |
| gastownhall/gastown | https://github.com/gastownhall/gastown | tmux-backed roles (Mayor, polecats); mail/nudge | CC default, Copilot, Codex, Gemini, Cursor (README) | Yes (tmux) | 18,467 stars, push 2026-10-21 | Uses tmux; Pi/OpenCode/Droid not named in README grep |
| Dicklesworthstone/ntm (Named Tmux Manager) | https://github.com/Dicklesworthstone/ntm | tmux panes + Go binary with `--robot-*` JSON, REST, SSE, WebSocket, OpenAPI (README) | CC, Codex, Antigravity, omp (Oh My Pi), Grok Build, Gemini legacy | Yes | 460 stars, push 2026-10-21 | Has a local REST/WS API to send prompts into panes |
| awslabs/cli-agent-orchestrator | https://github.com/awslabs/cli-agent-orchestrator | tmux terminals; HTTP API + PTY WebSocket (docs/api.md) | CC, Kiro, Codex, Antigravity, OpenCode, OMP (README) | Yes | 1,458 stars, push 2026-10-22 | AWS Labs; inbox/messaging between terminals |
| jayminwest/overstory | https://github.com/jayminwest/overstory | Worktrees + SQLite mail; `ov mail check --inject` injects mail into the agent | CC, Pi, Codex, OpenCode (README) | tmux (assumed) | 1,315 stars, last push 2026-05-28 | Mail injection happens through hook/check, not live push |
| agent-of-empires/agent-of-empires | https://github.com/agent-of-empires/agent-of-empires | tmux sessions, TUI + web dashboard (phone) | CC, OpenCode (README), others unverified | Yes | 3,373 stars, push 2026-10-22 | Web input path into tmux: unverified |
| siteboon/claudecodeui (CloudCLI) | https://github.com/siteboon/claudecodeui | Web/mobile UI driving CLIs | CC, OpenCode, Cursor, Codex | UI only | 14,225 stars, push 2026-10-21 | - |
| omnara-ai/omnara | https://github.com/omnara-ai/omnara | Now a managed-agent platform (MCP server, API to send messages) | CC, Codex, OpenCode, Pi as harnesses (README) | no | 2,993 stars, push 2026-10-22 | Pivoted away from "attach to local terminal" |
| alexei-led/ccgram | https://github.com/alexei-led/ccgram | Telegram to tmux window (or Herdr session) bridge | CC, Codex, Gemini, Pi, shell | Yes (tmux) | 279 stars, push 2026-10-21 | Same tmux-send approach. six-ddc/ccbot (277) is CC-only |
| ebibibi/ebi-agent-chat-relay | https://github.com/ebibibi/ebi-agent-chat-relay | Web/Discord/Teams console running CLIs as backends | CC, Codex, local, pi, AG-UI | web | 64 stars, push 2026-10-22 | Backend model, no TUI attach |
| nyanko3141592/tmuxcc, hallucinogen/agent-viewer, samleeney/tmux-agent-status | github | tmux dashboards (status, approve keys) | CC, OC, Codex, Gemini | Yes | 67 / 402 / 289 stars | Mostly observability, can send approve keys |
| buildoak/agent-mux | https://github.com/buildoak/agent-mux | dispatch layer / one JSON contract | Codex, CC, Gemini | no | 35 stars | Not live-session injection |
| openclaw/acpx | https://github.com/openclaw/acpx | See category 6 | - | - | - | - |

## 3. Droid

Primary sources: docs.factory.com (Remote Control, Droid Exec overview, CLI reference, changelog) read this session. Local `droid` could not be run (shell wrapper `_agent_sandboxed` not defined in this tool shell), so `droid --help` is not checked.

| name | URL | mechanism | human attach? | notes |
|---|---|---|---|---|
| `droid exec --input-format stream-jsonrpc --output-format stream-jsonrpc` | https://docs.factory.com/droid-exec/overview | Long-lived subprocess, newline-delimited JSON-RPC on stdin/stdout. Methods: `droid.initialize_session`, `droid.load_session` (resume), `droid.add_user_message` ("Send a turn to the session"), `droid.session_notification`, `droid.request_permission`, `droid.ask_user`; "further session methods interrupt work, update settings, ... fork sessions, or compact history" | No. It is a headless child owned by the caller; the interactive TUI is a different process. Resuming the same session id elsewhere (`droid exec -s <id>`, `droid --resume`) is sequential, not shared | Gives deterministic turns but not into a live TUI. TypeScript SDK `@factory/droid-sdk` (createSession/resumeSession) wraps it |
| `droid exec --output-format acp` / `acp-daemon` | https://github.com/agentclientprotocol/registry (factory-droid/agent.json: `npx droid@0.245.1 exec --output-format acp-daemon`) | ACP agent over stdio | Only via an ACP client UI | Registry entry confirms. Open issues #47, #60, #1228 in factory-ai/factory about ACP behaviour |
| `droid daemon --remote-control` (alias `--remote-access`) | https://docs.factory.com/remote-control | Daemon connects outbound to Factory relay (`relay.factory.ai`, EU `relay.eu.factory.ai`); computer registered via `droid computer register`; "so Droid can work on it from the web or other devices"; no inbound ports | Yes: Factory App/web/mobile talk to sessions on that machine; changelog: "A queued message now stays put when another computer's connection drops" and "TUI daemon session" entries, so interactive TUI sessions are daemon-backed | This is the only native remote-push path, but it is routed via Factory cloud and requires a Factory account. No documented local socket/WebSocket API for third-party processes. Whether a third party can speak the relay protocol: unverified/undocumented |
| Changelog hints | https://docs.factory.com/changelog/release-notes | "Queue message shortcut - Queue a message with Ctrl+Enter"; "Messages typed while /compress is running are now queued"; "Edit queued messages ... or pending steering message" (app) | - | Droid has queue + steering UI semantics, only through its own UI/relay |
| Hooks | https://docs.factory.com/harness/hooks | Event-driven shell hooks | - | Hooks fire on events; no external wake documented (not read in depth: unverified) |
| Third-party | droid-mcp-controller (glama, teobucos): start/inspect/list/cancel/continue durable Droid tasks via MCP, `droid exec` based; Asylcreek/droid-tmux.nvim: sends nvim context to Droid in a tmux pane (1 star) | exec or tmux | tmux version yes | Confirms the community fallback for Droid = tmux send-keys |
| Fleet tools naming Droid | vibe-kanban, emdash, agent-deck? (unverified for agent-deck) | see category 2 | - | - |

Conclusion for Droid: no documented local push API into the interactive TUI. Options are tmux/terminal injection, `stream-jsonrpc` as a separate headless session on the same session id (not live-shared), ACP, or the Factory relay (cloud-mediated).

## 4. Codex

Sources: gh issues/PRs in openai/codex, source `codex-rs/cli/src/queue_cmd.rs` and `codex-rs/tui/src/session_queue_commands.rs`.

| item | URL | finding |
|---|---|---|
| PR #39092 "Add a command to queue messages for existing sessions" (merged 2026-08-17) | https://github.com/openai/codex/pull/39092 | `codex queue --thread <UUID or exact name> --message <text>` calls app-server `thread/queue/add`. Resolves interactive, exec and custom sessions; supports local and explicit remote app servers; text only, no images |
| Delivery semantics | issues #54991, #52705, #48928, #41060 | Items are stored (`~/.codex/queue_1.sqlite`, `queued_items`). **Idle interactive session: queue wakes it and starts a turn** (#54991, TUI 0.164.0-alpha.3: "wakes an idle session"). **Busy session: item is a follow-up that starts only after the current turn ends**, not a steer (#48928, #52705). Under an active `/goal`, the queue can lose the race against continuation turns and wait for a manual Steer (#52705, Desktop). Exec threads: items may never be delivered/lost (#41060) |
| Provenance | #54991, #45976 | Queued text appears in the TUI as an ordinary user prompt and reaches the model as role user; no sender attribution yet. Open requests for `--as developer --from` |
| No steer mode | #48928 (open), #51625 (open) | `codex queue` has no steer option. `turn/steer {threadId, input, expectedTurnId}` exists in the app-server protocol but only on the server that owns the thread |
| Shared daemon | PR #46088 (`--no-daemon`, merged 2026-09-17), #51098 | Since ~0.160 the TUI runs on a managed background app-server daemon by default. `codex queue`, `codex agents`, `--remote` require a server connection and are rejected with `--no-daemon`. This is why `codex queue` can reach a live TUI |
| Source note | queue_cmd.rs | Rejects `--no-daemon` without explicit remote: "Queuing must discover the shared server" |
| `codex --remote` + external client | #21551 (closed RFC, 2026-05), docs app-server | `codex --remote ws://…` or unix socket connects TUI to an app-server. A maintainer said then: "assumed that you'll close the thread in the TUI before interacting with it ... in the desktop app ... each client starts a new instance of the app server". The RFC asked for multi-subscriber co-presence. Whether a second client's `turn/start`/`turn/steer` is rendered live in an already-attached TUI under the current daemon design: **unverified** (no primary confirmation found). Test needed: `codex app-server --listen unix://X`, `codex --remote unix://X`, second JSON-RPC client calling `turn/steer`. The wrapper pattern is described in #51098 item 2 |
| Related | #16447 (UDS peer messaging request, Claude-compatible), #15355 (opt-in local ingress; mentions `codex send`), #9224 (Remote Control), #54252 (read reply to queue message), #54892 | `codex send` appears in a comment on #15355 as a proposal; not confirmed shipped |
| Releases | | rust-v0.164.0-alpha.10 published 2026-10-22; `codex queue` and `codex agents` ship since rust-v0.149.0 per a third-party page (unverified) |

## 5. Pi: extensions that listen on socket/HTTP/relay and inject into the live TUI

All are userland packages; Pi core has no ingress (no relevant issue found in earendil-works/pi). Repo (earendil-works/pi): 116,991 stars, push 2026-10-21. Primary check = npm registry metadata/README for the first row; others from npm descriptions only.

| name | URL | mechanism | agents | human attach? | maintenance | notes |
|---|---|---|---|---|---|---|
| @vanillagreen/pi-session-bridge (CLI `pi-bridge`) | https://github.com/vanillagreencom/kendex (pi-extensions/pi-session-bridge); npm v3.0.1 | Each Pi session opens a Unix socket + registry file; CLI finds sessions, sends prompts/corrections/follow-ups, reads history, subscribes to live events; README: "controlling visible interactive Pi sessions"; "The socket triggers real agent work in the owning Pi process" | PI | Yes, it is the normal TUI | kendex repo 85 stars, push 2026-10-22; npm modified 2026-10-03 | Closest to what you asked for in Pi. Read README verified |
| carderne/pi-nvim | https://github.com/carderne/pi-nvim | Extension opens unix socket when pi starts; external tools send JSON to inject prompts (search snippet) | PI | Yes | 98 stars, push 2026-10-12 | - |
| nicobailon/pi-intercom | https://github.com/nicobailon/pi-intercom | Local broker over IPC; 1:1 messages between pi sessions | PI | Yes | 548 stars, push 2026-10-21 | Pi-to-Pi, you can write a non-Pi client against the broker (protocol unverified) |
| pi-aimail | https://www.npmjs.com/package/pi-aimail | "inbound local HTTP receiver bridged into the active session via sendUserMessage" (npm desc) | PI | Yes | github.com/metercai/aimail 0 stars, push 2026-10-21; npm 0.1.57 | A local HTTP endpoint you could POST to; designed for mail |
| @geohar/un-bien / remote-pi | https://github.com/georgeharker/un-bien | Phone relay + local Unix Domain Socket broker for multi-Pi, structured requests | PI | Yes | 7 stars, push 2026-10-22 | remote-pi broker path `pi/remote/sessions/<name>/broker.sock` (search snippet) |
| @prjct.app/pi-team | https://github.com/prjct-app/pi-team | "Connect independent Pi terminals with live presence, automatic message delivery and clear submission receipts" | PI | Yes | 1 star, push 2026-10-13 | - |
| pi-claude-link | https://github.com/alonw0/pi-claude-link | Speaks Claude Code's cross-session socket protocol: pi sessions appear in CC's session list and exchange messages | PI <-> CC | Yes | 15 stars, push 2026-08-08 | Already similar to your known pi-claude-peer |
| pi-event-monitor | https://github.com/Helmi/pi-event-monitor | Background shell/file watchers wake the session that started them via custom message + trigger turn | PI | Yes | 17 stars, last push 2026-05-12 | Self-wake only |
| @amaster.ai/pi-channels | https://github.com/TGYD-helige/pi | Native messaging channels: Feishu, DingTalk, WeCom, webhooks | PI | Yes | npm modified 2026-10-20 | Webhook ingress = HTTP listener. Details unverified |
| Remote-control family: zerray/pi-remote-control (11 stars), mipsel64/pi-remote-control (4), CleverCloud/pi-remote-control (1), goofansu/pi-remote-control (8), @yunazgr/pi-companion (ygrip, Rust daemon), Pi Pulse, pi-remote (Python wrapping `pi --mode rpc`), pi-courier (Matrix over RPC) | see npm names | Relay/daemon bridges phone/browser to a live TUI session ("steering" in pi-companion) | PI | Yes except pi-remote/pi-courier (RPC mode, headless) | all small, pushed 2026-09/10 | Same idea, cloud or LAN relay; local socket not guaranteed |
| joelclaw gateway | https://joelclaw.com/adrs/adr-0038 | pi inside tmux; gateway extension injects events via `sendUserMessage()` | PI | Yes | blog ADR 2026-02 | Pattern reference |
| pi-acp (svkozak) | https://github.com/svkozak/pi-acp | ACP adapter | PI | See cat. 6 | registry v0.0.34 | - |
| pi RPC mode (`pi --mode rpc`) | already known | headless | PI | No | - | - |

## 6. ACP (Agent Client Protocol)

Registry read via gh: https://github.com/agentclientprotocol/registry (427 stars, push 2026-10-22). Protocol repo 4,478 stars.

| agent | ACP as agent? | how | notes |
|---|---|---|---|
| Claude Code | Yes, via wrapper | `@agentclientprotocol/claude-agent-acp` 0.94.0 (Anthropic/Zed/JetBrains), built on the Agent SDK | Not the interactive TUI process; a new SDK-driven session |
| Codex | Yes, via wrapper | `@agentclientprotocol/codex-acp` 2.2.2 (OpenAI/JetBrains/Zed) | Wrapper around Codex; does it share the TUI's thread via app-server: unverified |
| OpenCode | Yes, native | `opencode acp` (registry entries for 1.19.3 and opencode-v2 2.1.2) | - |
| Pi | Yes, via adapter | `pi-acp` 0.0.34 (svkozak) | Adapter, likely wraps RPC (unverified) |
| Droid | Yes, native | `droid exec --output-format acp` / `acp-daemon` (registry 0.245.1) | - |

ACP clients that can host sessions:
| name | URL | mechanism | human attach? | maintenance |
|---|---|---|---|---|
| openclaw/acpx | https://github.com/openclaw/acpx | Headless ACP CLI client with persistent named sessions, queued follow-up prompts when a turn is running ("queue ownership, reconnects" in docs); `createSharedAcpRuntime()` lets an app and CLI processes share one local session owner. Adapters named: codex, droid (acpx README via search), claude, etc. | A human using acpx can send prompts too, but there is no TUI; no attach to an existing native TUI | 3,374 stars, push 2026-10-21 |
| Zed / JetBrains / Obsidian agent-client (RAIT-09/obsidian-agent-client 2,454 stars) / ACP UI web client | various | GUI hosts of ACP agents | The GUI is the human interface | active |
| ACP RFD: Streamable HTTP & WebSocket transport | https://agentclientprotocol.com/rfds/streamable-http-websocket-transport | Proposed remote transport; QwenLM/qwen-code#4782 lists "multi-client shared session" as a goal | n/a | RFD stage |
| ACP RFD session/list | https://agentclientprotocol.com/rfds/session-list | enumerate sessions | n/a | RFD |

Takeaway: ACP gives a uniform headless way to create/resume sessions for all 5, but the ACP agent is its own process. It does not push into a separately running native TUI, and the spec has no multi-client attach (proposals only). Use it for the "orchestrator owns the session" design, with the human typing via the ACP client UI.

## Additional findings outside your categories (all verified in docs)

| item | source | notes |
|---|---|---|
| Claude Code Channels (`claude --channels plugin:telegram@claude-plugins-official`) | https://code.claude.com/docs/en/channels | "Channels are MCP servers that push events into your running Claude Code session." Research preview; sender allowlist; org policy `channelsEnabled`/`allowedChannelPlugins`; `--dangerously-load-development-channels` for custom local channels; flags hidden from `--help`. A custom channel MCP server is the sanctioned way for a script to push into a live CC TUI |
| Claude Code Remote Control | https://code.claude.com/docs/en/remote-control | Local terminal session also reachable from claude.ai/phone; cross-session messaging rides the same connection |
| Claude Code cross-session messaging | https://code.claude.com/docs/en/cross-session-messaging | Inbox socket per session (shipped 2.1.224), SendMessage / ListAgents; message labelled as from another session |
| Claude Code agent view / background sessions | https://code.claude.com/docs/en/agent-view | `claude agents`, `claude attach <id>` (per a third-party article, unverified); background sessions run under a supervisor daemon that you can attach to |
| OpenCode server `/tui/*` | https://opencode.ai/docs/server | `/tui/append-prompt`, `/tui/submit-prompt`, `/tui/execute-command`, `/tui/clear-prompt`, `/tui/show-toast`, and `/session/:id/prompt_async`; docs page may describe v1 so confirm on 2.0.32. Issue anomalyco/opencode#8564: prompt_async messages processed but not rendered in the TUI (Jan 2026, status unverified) |
| xnoto/opencode-agent-hub | https://github.com/xnoto/opencode-agent-hub | Archived 2026-08-30. Used `POST /session/{id}/prompt_async` to wake agents across TUIs |
