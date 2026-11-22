import json
from dataclasses import dataclass, field

PASTE_START = b"\x1b[200~"
PASTE_END = b"\x1b[201~"
LONG_CASE = "long"


@dataclass(frozen=True)
class Read:
    t: float
    data: bytes


@dataclass(frozen=True)
class CaseResult:
    case: str
    fidelity: str
    detail: str
    markers: str
    submit: str
    sizes: tuple[int, ...]
    marker_split: bool


@dataclass(frozen=True)
class BurstResult:
    in_order: bool
    received: int
    expected: int
    paste_regions: int
    detail: str


@dataclass(frozen=True)
class Summary:
    fidelity: str
    markers: str
    chunking: str
    burst: str
    submit: str = ""
    failing: dict[str, str] = field(default_factory=dict)


def parse_log(text: str) -> tuple[dict, list[Read]]:
    meta: dict = {}
    reads: list[Read] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "hex" in row:
            reads.append(Read(row["t"], bytes.fromhex(row["hex"])))
        else:
            meta.update(row)
    return meta, reads


def case_text(n: int) -> str:
    return "".join(f"line{i:04d} the quick brown fox; " for i in range(n))


CASES: dict[str, str] = {
    "plain": "hello world",
    "multiline": "line one\nline two\n\nline four",
    "quotes": "He said \"hi\" and 'bye' `echo $HOME` $(whoami) \\n back\\slash",
    "semicolons": "a;b;;c;;;",
    "tab": "col1\tcol2",
    "unicode": "héllo ✓ 日本語 \U0001f600 \U0001f680",
    LONG_CASE: case_text(340),
}
BURST = [f"BURST-{i}-{'x' * 24}" for i in range(1, 6)]


def split_submit(data: bytes) -> tuple[bytes, bytes]:
    body = data.rstrip(b"\r\n")
    return body, data[len(body):]


def count_markers(data: bytes) -> tuple[int, int]:
    return data.count(PASTE_START), data.count(PASTE_END)


def classify_markers(body: bytes) -> str:
    starts, ends = count_markers(body)
    if starts == 0 and ends == 0:
        return "absent"
    if starts == 1 and ends == 1 and body.startswith(PASTE_START) and body.endswith(PASTE_END):
        return "wrapped"
    return f"partial({starts}/{ends})"


def strip_markers(data: bytes) -> bytes:
    return data.replace(PASTE_START, b"").replace(PASTE_END, b"")


def marker_offsets(data: bytes) -> list[int]:
    offsets = []
    for marker in (PASTE_START, PASTE_END):
        start = data.find(marker)
        while start != -1:
            offsets.append(start)
            start = data.find(marker, start + 1)
    return offsets


def marker_split(sizes: tuple[int, ...], data: bytes) -> bool:
    boundaries = []
    total = 0
    for size in sizes[:-1]:
        total += size
        boundaries.append(total)
    return any(o < b < o + len(PASTE_START) for o in marker_offsets(data) for b in boundaries)


def excerpt(data: bytes, at: int) -> str:
    return data[max(0, at - 8):at + 24].decode("utf-8", "backslashreplace").encode("unicode_escape").decode()


def first_diff(a: bytes, b: bytes) -> int:
    return next((i for i, (x, y) in enumerate(zip(a, b, strict=False)) if x != y), min(len(a), len(b)))


NEWLINE_MAPS = ((b"\r", b"\n", "LF arrives as CR"), (b"\n", b"\r", "CR arrives as LF"),
                (b"\r\n", b"\n", "LF arrives as CRLF"))


def compare_body(sent: str, received: bytes) -> tuple[str, str]:
    expected = sent.encode()
    if not received:
        return "missing", "no bytes received"
    if received == expected:
        return "exact", ""
    for src, dst, label in NEWLINE_MAPS:
        if received.replace(src, dst) == expected:
            return "newline-translated", label
    at = first_diff(received, expected)
    return "differs", f"offset {at}: sent {excerpt(expected, at)!r} got {excerpt(received, at)!r}; " \
                      f"{len(expected)} B sent, {len(received)} B received"


def analyze_case(case: str, sent: str, reads: list[Read]) -> CaseResult:
    sizes = tuple(len(r.data) for r in reads)
    data = b"".join(r.data for r in reads)
    body, submit = split_submit(data)
    fidelity, detail = compare_body(sent, strip_markers(body))
    return CaseResult(case, fidelity, detail, classify_markers(body) if body else "absent", submit.hex() or "none",
                      sizes, marker_split(sizes, data))


def split_messages(data: bytes) -> list[bytes]:
    return [piece for piece in strip_markers(data).replace(b"\r\n", b"\r").split(b"\r") if piece]


def analyze_burst(sent: list[str], reads: list[Read]) -> BurstResult:
    data = b"".join(r.data for r in reads)
    got = split_messages(data)
    expected = [s.encode() for s in sent]
    in_order = got == expected
    detail = "" if in_order else f"got {[g[:40].decode('utf-8', 'backslashreplace') for g in got]}"
    return BurstResult(in_order, len(got), len(expected), data.count(PASTE_START), detail)


def fraction(k: int, n: int) -> str:
    return f"{k}/{n}"


def summarize(cases: list[CaseResult], burst: BurstResult) -> Summary:
    exact = [c for c in cases if c.fidelity == "exact"]
    problems = {c.case: f"{c.fidelity}: {c.detail}" if c.detail else c.fidelity for c in cases
                if c.fidelity != "exact"}
    fidelity = fraction(len(exact), len(cases)) + (
        " exact; " + "; ".join(f"{k} {v}" for k, v in problems.items()) if problems else " exact")
    marker_kinds = sorted({c.markers for c in cases})
    markers = "+".join(marker_kinds) if marker_kinds else "none"
    submits = sorted({c.submit for c in cases})
    long_case = next((c for c in cases if c.case == LONG_CASE), None)
    chunking = "no data"
    if long_case:
        chunking = (f"long: {len(long_case.sizes)} reads, max {max(long_case.sizes, default=0)} B"
                    + ("; marker split across reads" if any(c.marker_split for c in cases) else ""))
    order = (f"{burst.received}/{burst.expected} " + ("in order" if burst.in_order else f"out of order or merged "
                                                                                        f"({burst.detail})")
             + (f", {burst.paste_regions} paste regions" if burst.paste_regions else ""))
    return Summary(fidelity, markers, chunking, order, "+".join(submits), problems)


def render_table(rows: list[tuple[str, str, Summary]]) -> str:
    lines = ["| host | adapter | fidelity | bracketed-paste markers | submit | chunking | burst order |",
             "|---|---|---|---|---|---|---|"]
    lines += [f"| {host} | {adapter} | {s.fidelity} | {s.markers} | {s.submit} | {s.chunking} | {s.burst} |"
              for host, adapter, s in rows]
    return "\n".join(lines) + "\n"
