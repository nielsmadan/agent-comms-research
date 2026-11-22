from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures() -> Path:
    return FIXTURES


@pytest.fixture(autouse=True)
def unsandboxed_coordinator(monkeypatch):
    from agentcomms import cli

    monkeypatch.setattr(cli, "coordinator_sandbox", lambda: None)


@pytest.fixture
def fake_pinned(monkeypatch):
    from agentcomms import profiles

    monkeypatch.setattr(profiles, "pinned_path", lambda agent, root=None: Path(f"/pinned/{agent}-0/{agent}"))


@pytest.fixture
def fake_vendored(monkeypatch):
    from agentcomms.adapters import hcom, intercom

    for module in (hcom, intercom):
        monkeypatch.setattr(module, "vendored", lambda p: p)
    monkeypatch.setattr(intercom, "node", lambda: "/bin/node")
