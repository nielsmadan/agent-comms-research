from agentcomms.engine import REPLY_TIMEOUT_S, envelope, new_token
from agentcomms.scenarios.common import Cell, Outcome, observe

MIN_BYTES = 10 * 1024
SAMPLES = (
    "Plain prose: the quick brown fox jumps over the lazy dog, again and again.",
    "Single 'quoted' and double \"quoted\" text, plus a stray ' and \" on their own.",
    "Backticks: `inline code` and ```fenced``` markers with `nested 'quotes'`.",
    "Shell-looking text: $HOME ${PATH} $(whoami) `date` $1 $@ && || ; | > < 2>&1",
    "Tabs:\tone\ttwo\t\tthree\tend",
    "Unicode: café naïve Straße Ελληνικά 中文 日本語 한국어 עברית العربية",
    "Emoji: 🚀 👍🏽 👨‍👩‍👧 🧪 ✅ ❤️ 🇩🇪",
    "Symbols: {braces} [brackets] <angle> #hash %percent ^caret ~tilde *star user@example.com",
    "Backslashes: C:\\path\\to\\file \\n is not a newline \\t nor a tab \\\\ double",
    "",
    "    Indented line with trailing spaces   ",
)


def payload() -> str:
    lines: list[str] = []
    i = 0
    while len("\n".join(lines).encode()) < MIN_BYTES:
        sample = SAMPLES[i % len(SAMPLES)]
        lines.append(f"L{i:04d} {sample}" if sample else "")
        i += 1
    lines.append(f"L{i:04d} END OF PAYLOAD")
    return "\n".join(lines)


def message(token: str) -> str:
    return envelope(token, "Payload integrity test; the payload follows.") + "\n" + payload()


def run(cell: Cell) -> Outcome:
    token = new_token()
    text = message(token)
    receipt = cell.owned_send(cell.target, text)
    transcript, finished = cell.engine.wait_for_token(cell.target, token, REPLY_TIMEOUT_S[cell.agent])
    out = observe(cell, cell.target, token, text, receipt, transcript, finished)
    out.notes.append(f"payload_bytes={len(text.encode())}")
    return out
