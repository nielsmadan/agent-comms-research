import subprocess

from agentcomms import gate
from agentcomms.procs import ProcRow


def test_gate_releases_a_blocked_reader(tmp_path):
    path = gate.create(tmp_path / "g.fifo")
    reader = subprocess.Popen(gate.gate_command(path).split(), stdout=subprocess.PIPE, text=True)
    try:
        released = False
        for _ in range(50):
            released = gate.release(path, gate.open_marker("r1"))
            if released:
                break
            subprocess.run(["sleep", "0.05"])
        out, _ = reader.communicate(timeout=5)
    finally:
        reader.kill()
        gate.remove(path)
    assert released
    assert out == "GATE-OPEN-r1\n"


def test_release_without_reader_reports_false(tmp_path):
    path = gate.create(tmp_path / "g.fifo")
    assert gate.release(path, "m") is False
    gate.remove(path)
    assert gate.release(path, "m") is False


def test_reader_is_found_in_the_process_table():
    path = gate.gate_path("20261024-000000-abcd")
    rows = [ProcRow(10, 1, 10, "/bin/zsh -c cat /tmp/ac/20261024-000000-abcd.fifo"),
            ProcRow(11, 10, 10, "cat /tmp/ac/20261024-000000-abcd.fifo")]
    assert str(path) == "/tmp/ac/20261024-000000-abcd.fifo"
    assert gate.reader_running(rows, path)
    assert gate.reader_running(rows[:0], path) is False
