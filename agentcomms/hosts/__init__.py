from pathlib import Path


def make_host(kind: str):
    if kind == "zmx":
        from agentcomms.hosts.zmx import ZmxHost
        return ZmxHost()
    if kind == "zellij":
        from agentcomms.hosts.zellij import ZellijHost
        return ZellijHost()
    if kind == "iterm2":
        from agentcomms.hosts.iterm2 import ItermHost
        return ItermHost()
    raise KeyError(f"no host implementation for {kind!r}")


def state_dir_for(kind: str, run_id: str, root: Path) -> Path | None:
    if kind == "zmx":
        from agentcomms.hosts.zmx import state_dir_for as zmx_dir
        return zmx_dir(run_id, root)
    if kind == "zellij":
        from agentcomms.hosts.zellij import state_dir_for as zj_dir
        return zj_dir(run_id, root)
    return None
