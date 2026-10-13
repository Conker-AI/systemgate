from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("SYSTEMGATE_ADMIN_KEY", "system-test-key-1234")
    monkeypatch.setenv("SYSTEMGATE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SYSTEMGATE_BACKUP_ROOT", str(tmp_path / "backups"))
    from systemgate.main import app
    return TestClient(app)


def headers():
    return {"X-SystemGate-Key": "system-test-key-1234"}


def test_health_and_auth(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/vitals").status_code == 401


def test_health_reports_container_telemetry_as_intentionally_unconfigured(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        body = client.get("/health").json()

    assert body["status"] == "ok"
    assert body["degraded"] == []
    assert body["checks"]["docker"]["status"] == "not_configured"
    assert body["checks"]["procfs"]["status"] == "ok"


def test_health_leaks_nothing_to_an_unauthenticated_caller(tmp_path, monkeypatch):
    """/health takes no key, so its detail must never carry host specifics."""
    with make_client(tmp_path, monkeypatch) as client:
        raw = client.get("/health").text

    assert "docker.sock" not in raw
    assert "/srv/secret" not in raw
    assert "Traceback" not in raw


def test_vitals_declares_which_machine_it_measured(tmp_path, monkeypatch):
    """Host or container is a deployment detail; the caller must not guess."""
    import systemgate.main as main
    monkeypatch.setattr(main.psutil, "cpu_percent", lambda interval=0: 1.0)
    monkeypatch.setattr(main.psutil, "cpu_count", lambda: 1)
    monkeypatch.setattr(main.psutil, "virtual_memory", lambda: Mock(_asdict=lambda: {}))
    monkeypatch.setattr(main.psutil, "disk_usage", lambda path: Mock(_asdict=lambda: {}))
    monkeypatch.setattr(main.psutil, "sensors_temperatures", lambda fahrenheit=False: {}, raising=False)

    monkeypatch.setattr(main.psutil, "PROCFS_PATH", "/proc", raising=False)
    with make_client(tmp_path, monkeypatch) as client:
        assert client.get("/vitals", headers=headers()).json()["source"]["scope"] == "container"

    monkeypatch.setattr(main.psutil, "PROCFS_PATH", "/host/proc", raising=False)
    with make_client(tmp_path, monkeypatch) as client:
        source = client.get("/vitals", headers=headers()).json()["source"]
    assert source["scope"] == "host"
    assert source["procfs"] == "/host/proc"


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="procfs is Linux-only")
def test_redirecting_procfs_actually_changes_what_is_read(tmp_path):
    """The redirection must work, not merely be configured.

    An earlier fix set PROCFS_PATH in the environment and mounted the host's
    /proc, which looks correct and does nothing: psutil honours no environment
    variable for this, so every figure still came from the container while the
    service reported scope "host". Only assigning psutil.PROCFS_PATH works.

    This asserts the reading itself moves, which is the thing the previous test
    could not see - it checked that the variable was set, not that psutil obeyed.
    """
    import psutil

    fake_proc = tmp_path / "proc"
    fake_proc.mkdir()
    (fake_proc / "meminfo").write_text(
        "MemTotal:       12345678 kB\n"
        "MemFree:         1111111 kB\n"
        "MemAvailable:    2222222 kB\n"
        "Buffers:             100 kB\n"
        "Cached:              200 kB\n"
        "SwapCached:            0 kB\n"
        "Active:                0 kB\n"
        "Inactive:              0 kB\n"
        "SwapTotal:             0 kB\n"
        "SwapFree:              0 kB\n"
        "Dirty:                 0 kB\n"
        "Writeback:             0 kB\n"
        "Shmem:                 0 kB\n"
        "Slab:                  0 kB\n"
        "SReclaimable:          0 kB\n",
        encoding="utf-8",
    )

    original = psutil.PROCFS_PATH
    try:
        psutil.PROCFS_PATH = str(fake_proc)
        assert psutil.virtual_memory().total // 1024 == 12345678
    finally:
        psutil.PROCFS_PATH = original


def test_vitals_with_mocked_psutil(tmp_path, monkeypatch):
    import systemgate.main as main
    monkeypatch.setattr(main.psutil, "cpu_percent", lambda interval=0: 12.5)
    monkeypatch.setattr(main.psutil, "cpu_count", lambda: 8)
    monkeypatch.setattr(main.psutil, "virtual_memory", lambda: Mock(_asdict=lambda: {"total": 100, "available": 50}))
    monkeypatch.setattr(main.psutil, "disk_usage", lambda path: Mock(_asdict=lambda: {"total": 200, "free": 100}))
    monkeypatch.setattr(main.psutil, "sensors_temperatures", lambda fahrenheit=False: {}, raising=False)

    with make_client(tmp_path, monkeypatch) as client:
        data = client.get("/vitals", headers=headers()).json()
        assert data["cpu_percent"] == 12.5
        assert data["memory"]["total"] == 100


def test_containers_truthfully_reports_unavailable(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        data = client.get("/containers", headers=headers()).json()
    assert data == {
        "status": "unavailable",
        "results": [],
        "errors": ["container_telemetry_not_configured"],
    }


def test_shipped_compose_has_no_docker_socket_or_host_root_mount():
    compose = (Path(__file__).parents[1] / "docker-compose.yml").read_text(encoding="utf-8")
    assert "docker.sock" not in compose
    assert "/host/root" not in compose
    assert not any(line.strip().startswith("- /:/") for line in compose.splitlines())


def test_services_inventory_is_metadata_only(tmp_path, monkeypatch):
    import systemgate.main as main

    class Addr:
        ip = "127.0.0.1"
        port = 8644

    conn = Mock(status="LISTEN", laddr=Addr(), pid=123)
    proc = Mock()
    proc.name.return_value = "pi-adapter"
    monkeypatch.setattr(main.psutil, "net_connections", lambda kind: [conn])
    monkeypatch.setattr(main.psutil, "Process", lambda pid: proc)

    with make_client(tmp_path, monkeypatch) as client:
        data = client.get("/services", headers=headers()).json()

    assert data["metadata_only"] is True
    assert data["results"][0]["id"] == "service-001"
    assert data["results"][0]["name"] == "pi-adapter"
    assert data["results"][0]["listeners"] == ["loopback:8644"]
    assert "pid" not in data["results"][0]
    assert "cmdline" not in data["results"][0]
    assert "env" not in data["results"][0]
    assert "username" not in data["results"][0]


def test_processes_logs_packages_and_backups_are_bounded(tmp_path, monkeypatch):
    backup_root = tmp_path / "backups"
    backup_root.mkdir()
    (backup_root / "20260101T000000Z").mkdir()
    import systemgate.main as main
    proc = Mock(info={"pid": 1, "name": "python", "username": "me", "cpu_percent": 1.0, "memory_percent": 2.0, "cmdline": ["python", "app.py"]})
    monkeypatch.setattr(main.psutil, "process_iter", lambda fields: [proc])
    monkeypatch.setattr(main, "_journal_errors", lambda: "bounded errors")
    monkeypatch.setattr(main, "_run_summary", lambda command: {"ok": True, "output": "[]"})

    with make_client(tmp_path, monkeypatch) as client:
        assert client.get("/processes", headers=headers()).json()["results"][0]["name"] == "python"
        assert client.get("/logs/errors", headers=headers()).json()["text"] == "bounded errors"
        assert client.get("/packages", headers=headers()).json()["pip"]["ok"] is True
        backup_state = client.get("/backups", headers=headers()).json()
        assert backup_state["latest"] is None
        assert backup_state["rejected"][0]["name"] == "20260101T000000Z"
        assert backup_state["rejected"][0]["status"] == "incomplete"
