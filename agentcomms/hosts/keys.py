KEY_BYTES = {
    "Enter": b"\r",
    "Escape": b"\x1b",
    "Tab": b"\t",
    "Space": b" ",
    "BSpace": b"\x7f",
    "Up": b"\x1b[A",
    "Down": b"\x1b[B",
    "Right": b"\x1b[C",
    "Left": b"\x1b[D",
    "C-c": b"\x03",
    "C-u": b"\x15",
}


def key_bytes(key: str) -> bytes:
    if key in KEY_BYTES:
        return KEY_BYTES[key]
    if len(key) == 1:
        return key.encode()
    raise KeyError(f"unknown key {key!r}")
