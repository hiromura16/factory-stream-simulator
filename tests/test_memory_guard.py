"""Check the host memory guard without relying on the test host's free RAM."""

import shutil
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from factorylib import JobContext


@pytest.mark.parametrize(
    "minimum,available_kib,blocked",
    [
        (None, 1024**2, False),
        (None, 1024**2 - 1, True),
        ("2", 1536 * 1024, True),
        ("0", 0, False),
    ],
)
def test_host_memory_headroom(monkeypatch, tmp_path, minimum, available_kib, blocked):
    if minimum is None:
        monkeypatch.delenv("MIN_AVAILABLE_GIB", raising=False)
    else:
        monkeypatch.setenv("MIN_AVAILABLE_GIB", minimum)
    read_text = Path.read_text

    def meminfo(path, *args, **kwargs):
        if path == Path("/proc/meminfo"):
            return f"MemTotal: 4194304 kB\nMemAvailable: {available_kib} kB\n"
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", meminfo)
    monkeypatch.setattr(
        shutil, "disk_usage", lambda _: SimpleNamespace(free=3 * 1024**3)
    )
    instance = JobContext(
        SimpleNamespace(data_dir=tmp_path), "memory-guard-test", Event()
    )
    instance.last_guard_check = float("-inf")
    check = instance.check
    if blocked:
        with pytest.raises(RuntimeError, match="^host_memory_headroom_low$"):
            check()
    else:
        check()
