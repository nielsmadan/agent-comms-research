# agent-comms-research

How do you push a message into a coding agent that is already running in a terminal, and wake it up, without breaking whatever it or its human is doing?

This repo is the record of one attempt to answer that by measurement. Between 2026-10-24 and 2026-10-28 an agent built a test harness, tried every delivery method it could find against five coding agents (Claude Code, Codex, Pi, OpenCode and Droid), and wrote up what happened. It produced 1,596 scored records.

I ran it to decide how the agents in my own setup should talk to each other. I am publishing it in case it saves someone else the time and the tokens. It is a snapshot, not a maintained project.

## What it found

The full write-up is [REPORT.md](REPORT.md). The short version:

- **Use each agent's own way in, not the terminal.** Claude Code, Codex, Pi and OpenCode each have a native route for receiving a message (a socket, an app server, an extension, a server API). Those were safe in every test.
- **Typing into the terminal is the risky option.** Sending keystrokes or a paste plus Enter through tmux, zmx, zellij or iTerm2 works with every agent, but the sender cannot see what is on screen. All 34 harmful results in the data were a terminal send approving a permission dialog nobody approved.
- **Agent to agent works.** On native routes, 35 of 35 round trips between two agents completed.
- **Droid is the exception.** It had no native route a human-attached session could use, so the terminal was the only way in.

The report also covers what happens when a message arrives mid-turn, while a human has a half-typed draft, in a burst, under a sandbox, and with eight receivers at once.

## What is in here

| Path | What it is |
|---|---|
| [REPORT.md](REPORT.md) | The findings, per agent and per method, with the recommended setup |
| [results/](results/) | The data behind the report. [raw.jsonl](results/raw.jsonl) holds every record; [matrix.md](results/matrix.md) and [shortlist.md](results/shortlist.md) are generated from it; [notes.md](results/notes.md) and [progress.md](results/progress.md) are the agent's working notes |
| [results/screen.md](results/screen.md) | The first screening pass over every candidate method |
| [results/hostcheck.md](results/hostcheck.md), [results/nono-preflight.md](results/nono-preflight.md) | Checks of the terminal hosts and of the sandbox before testing, with their raw output in `hostcheck.json` and `nono-session-files.txt` |
| `results/scale-*.json` | The two runs with eight receivers at once |
| [docs/harness.md](docs/harness.md) | How the test harness works and how to run it |
| [docs/design.md](docs/design.md) | Design decisions and the numbered rulings (R9 to R51) that the report cites |
| [docs/enumeration.md](docs/enumeration.md), [docs/research-assumptions.md](docs/research-assumptions.md) | The survey of tools and the background research done before testing |
| [docs/studio-retest.md](docs/studio-retest.md) | A plan for repeating the key tests on a second machine. Not run yet |
| `agentcomms/` | The harness. Each delivery method is an adapter in `agentcomms/adapters/` ([terminal adapter notes](agentcomms/adapters/README.md)); terminal hosts are in `agentcomms/hosts/` ([notes](agentcomms/hosts/README.md)) |
| `tests/` | The harness's own test suite |
| `vendor/` | Version pins and [a review log](vendor/REVIEW.md) for the third-party bridges that were tested. The bridges themselves are not included |

## Read this before relying on it

- **It is dated.** The versions tested are listed at the top of the report (Claude Code 2.1.312, Codex 0.165.0, Pi 1.4.0, OpenCode 2.2.0, Droid 0.251.0). These tools change weekly, and several of the routes used are undocumented or marked as development features.
- **The samples are small.** Most cells have one to five runs, so only failures that happen often would show up. Section 9 of the report lists the measurement limits.
- **One machine, one setup.** Everything ran on a single MacBook on macOS. Nothing was measured across machines or at more than eight agents.
- **An agent wrote almost all of it.** The harness, the report and the notes were written by a coding agent working mostly unattended, with my rulings where it asked. I have not checked every number against the raw data.
- **The paths are mine.** The docs mention local paths such as `~/wrksp` and a secrets wrapper called `sops-exec`.

## What is not in here

Each test run kept its own isolated home directory, a terminal capture and a backend log, about 500 MB of logs in total once the copied agent installs are left out. They are not in the repo. If you want them, open an issue.

## Running it yourself

See [docs/harness.md](docs/harness.md). You need `uv`, tmux and your own copies of the agent binaries, and the setup section assumes my credential wrapper, so expect to adapt it.

## What came out of it

Two tools that use the recommended routes:

- [bellhop](https://github.com/nielsmadan/bellhop): deliver a message into a running Claude Code, Codex or Pi session.
- [callboard](https://github.com/nielsmadan/callboard): chat and mail between agents, built on bellhop.

## License

[MIT](LICENSE), for the code, the report and the data.
