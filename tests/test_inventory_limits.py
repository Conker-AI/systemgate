from __future__ import annotations

from types import SimpleNamespace
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


@pytest.mark.parametrize(
    "ip,expected_scope",
    [
        ("127.0.0.1", "loopback"),
        ("127.9.9.9", "loopback"),
        ("::1", "loopback"),
        ("100.64.0.5", "tailscale"),
        ("100.127.255.254", "tailscale"),
        ("100.1.2.3", "public-or-host"),
        ("100.128.0.1", "public-or-host"),
        ("10.1.2.3", "private-lan"),
        ("192.168.1.9", "private-lan"),
        ("172.16.0.1", "private-lan"),
        ("172.31.255.1", "private-lan"),
        ("172.15.0.1", "public-or-host"),
        ("172.32.0.1", "public-or-host"),
        ("8.8.8.8", "public-or-host"),
        ("fe80::1", "public-or-host"),
    ],
)
def test_address_scopes(ip, expected_scope):
    import systemgate.main as main

    addr = SimpleNamespace(ip=ip, port=8080)
    result = main._safe_addr(addr)
    assert result == f"{expected_scope}:8080"


@pytest.mark.parametrize(
    "ip,docker,expected",
    [
        ("0.0.0.0", True, "container-internal:53"),
        ("0.0.0.0", False, "all-interfaces:53"),
        ("::", True, "container-internal:53"),
        ("::", False, "all-interfaces:53"),
    ],
)
def test_wildcard_scope_depends_on_a_container(ip, docker, expected, monkeypatch):
    import systemgate.main as main

    monkeypatch.setattr(main, "Path", lambda _p: SimpleNamespace(exists=lambda: docker))
    addr = SimpleNamespace(ip=ip, port=53)
    result = main._safe_addr(addr)
    assert result == expected


def test_an_address_without_ip_or_port_is_empty():
    import systemgate.main as main

    # Test None address
    assert main._safe_addr(None) == ""

    # Test empty IP
    addr1 = SimpleNamespace(ip="", port=8080)
    assert main._safe_addr(addr1) == ""

    # Test port 0
    addr2 = SimpleNamespace(ip="127.0.0.1", port=0)
    assert main._safe_addr(addr2) == ""

    # Test None port
    addr3 = SimpleNamespace(ip="127.0.0.1", port=None)
    assert main._safe_addr(addr3) == ""


def test_services_group_dedupe_and_sort(tmp_path, monkeypatch):
    import systemgate.main as main

    # Mock net_connections
    connections = [
        Mock(status="LISTEN", laddr=SimpleNamespace(ip="127.0.0.1", port=9000), pid=1),
        Mock(status="LISTEN", laddr=SimpleNamespace(ip="127.0.0.1", port=81), pid=2),
        Mock(status="LISTEN", laddr=SimpleNamespace(ip="127.0.0.1", port=81), pid=3),
        Mock(status="LISTEN", laddr=SimpleNamespace(ip="10.0.0.2", port=82), pid=3),
        Mock(status="ESTABLISHED", laddr=SimpleNamespace(ip="127.0.0.1", port=7), pid=2),
        Mock(status="LISTEN", laddr=None, pid=2),
        Mock(status="LISTEN", laddr=SimpleNamespace(ip="127.0.0.1", port=0), pid=2),
        Mock(status="LISTEN", laddr=SimpleNamespace(ip="127.0.0.1", port=90), pid=5),
        Mock(status="LISTEN", laddr=SimpleNamespace(ip="127.0.0.1", port=91), pid=None),
        Mock(status="LISTEN", laddr=SimpleNamespace(ip="127.0.0.1", port=92), pid=4),
    ]
    monkeypatch.setattr(main.psutil, "net_connections", lambda kind: connections)

    # Mock Process
    def mock_process(pid):
        proc = Mock()
        if pid == 5:
            raise main.psutil.NoSuchProcess(5)
        name_map = {1: "zeta", 2: "alpha", 3: "alpha", 4: None}
        proc.name.return_value = name_map.get(pid, "unknown")
        return proc

    monkeypatch.setattr(main.psutil, "Process", mock_process)

    with make_client(tmp_path, monkeypatch) as client:
        response = client.get("/services", headers=headers())
        data = response.json()

    assert data["metadata_only"] is True
    results = data["results"]
    assert len(results) == 3

    # Check first service (alpha)
    alpha = results[0]
    assert alpha["id"] == "service-001"
    assert alpha["name"] == "alpha"
    assert alpha["status"] == "listening"
    assert alpha["kind"] == "process-listener"
    assert alpha["listeners"] == ["loopback:81", "private-lan:82"]

    # Check second service (unknown)
    unknown = results[1]
    assert unknown["id"] == "service-002"
    assert unknown["name"] == "unknown"
    assert unknown["status"] == "listening"
    assert unknown["kind"] == "process-listener"
    assert unknown["listeners"] == ["loopback:90", "loopback:91", "loopback:92"]

    # Check third service (zeta)
    zeta = results[2]
    assert zeta["id"] == "service-003"
    assert zeta["name"] == "zeta"
    assert zeta["status"] == "listening"
    assert zeta["kind"] == "process-listener"
    assert zeta["listeners"] == ["loopback:9000"]


def test_services_limit_is_clamped(tmp_path, monkeypatch):
    import systemgate.main as main

    # Create 250 connections
    connections = []
    for i in range(1, 251):
        connections.append(
            Mock(status="LISTEN", laddr=SimpleNamespace(ip="127.0.0.1", port=8000 + i), pid=i)
        )

    monkeypatch.setattr(main.psutil, "net_connections", lambda kind: connections)

    def mock_process(pid):
        proc = Mock()
        proc.name.return_value = f"p{pid:03d}"
        return proc

    monkeypatch.setattr(main.psutil, "Process", mock_process)

    with make_client(tmp_path, monkeypatch) as client:
        # Test limit values
        test_cases = [
            (0, 1),
            (-5, 1),
            (1, 1),
            (5, 5),
            (200, 200),
            (1000, 200),
            (None, 80),  # default
        ]

        for limit_param, expected_count in test_cases:
            if limit_param is None:
                response = client.get("/services", headers=headers())
            else:
                response = client.get(f"/services?limit={limit_param}", headers=headers())

            data = response.json()
            assert len(data["results"]) == expected_count

        # Test specific limit=3 case
        response = client.get("/services?limit=3", headers=headers())
        data = response.json()
        assert len(data["results"]) == 3
        assert data["results"][0]["name"] == "p001"
        assert data["results"][1]["name"] == "p002"
        assert data["results"][2]["name"] == "p003"
        assert data["results"][0]["id"] == "service-001"
        assert data["results"][1]["id"] == "service-002"
        assert data["results"][2]["id"] == "service-003"


def test_services_survive_a_denied_connection_listing(tmp_path, monkeypatch):
    import systemgate.main as main

    monkeypatch.setattr(
        main.psutil,
        "net_connections",
        lambda kind: (_ for _ in ()).throw(main.psutil.AccessDenied()),
    )

    with make_client(tmp_path, monkeypatch) as client:
        response = client.get("/services", headers=headers())
        data = response.json()

    assert response.status_code == 200
    assert data["results"] == []
    assert data["metadata_only"] is True
    assert data["status"] == "unavailable"
    assert data["errors"] == ["service_enumeration_unavailable"]


def test_processes_sort_skip_and_clamp(tmp_path, monkeypatch):
    import systemgate.main as main

    class Denied:
        @property
        def info(self):
            raise main.psutil.AccessDenied()

    processes = [
        Mock(
            info={
                "pid": 1,
                "name": "proc1",
                "username": "user",
                "cpu_percent": 1.0,
                "memory_percent": 5.0,
            }
        ),
        Mock(
            info={
                "pid": 2,
                "name": "proc2",
                "username": "user",
                "cpu_percent": 9.0,
                "memory_percent": 1.0,
            }
        ),
        Denied(),
        Mock(
            info={
                "pid": 3,
                "name": "proc3",
                "username": "user",
                "cpu_percent": 1.0,
                "memory_percent": 7.0,
            }
        ),
        Mock(
            info={
                "pid": 4,
                "name": "proc4",
                "username": "user",
                "cpu_percent": None,
                "memory_percent": None,
            }
        ),
    ]

    def mock_process_iter(fields):
        return processes

    monkeypatch.setattr(main.psutil, "process_iter", mock_process_iter)

    with make_client(tmp_path, monkeypatch) as client:
        # Test default ordering and limits
        response = client.get("/processes", headers=headers())
        data = response.json()
        results = data["results"]

        # Check ordering: should be by CPU then memory, descending
        assert results[0]["pid"] == 2  # CPU 9.0, mem 1.0
        assert results[1]["pid"] == 3  # CPU 1.0, mem 7.0
        assert results[2]["pid"] == 1  # CPU 1.0, mem 5.0
        assert results[3]["pid"] == 4  # CPU None, mem None

        # Test limit clamping
        for limit_param, expected_pids in [(0, [2]), (2, [2, 3]), (1000, [2, 3, 1, 4])]:
            response = client.get(f"/processes?limit={limit_param}", headers=headers())
            assert [row["pid"] for row in response.json()["results"]] == expected_pids


def test_processes_limit_is_capped_at_100(tmp_path, monkeypatch):
    import systemgate.main as main

    # Create 150 processes with varying CPU/memory
    processes = []
    for i in range(150):
        processes.append(
            Mock(
                info={
                    "pid": i + 1,
                    "name": f"proc{i + 1}",
                    "username": "user",
                    "cpu_percent": float(i % 10),  # CPU 0-9
                    "memory_percent": float(i % 5),  # Memory 0-4
                }
            )
        )

    monkeypatch.setattr(main.psutil, "process_iter", lambda fields: processes)

    with make_client(tmp_path, monkeypatch) as client:
        response = client.get("/processes?limit=1000", headers=headers())
        data = response.json()

        # Should be clamped to 100
        assert len(data["results"]) == 100


def test_packages_are_cached_for_an_hour(tmp_path, monkeypatch):
    import systemgate.main as main

    # Track command calls
    commands_run = []

    def mock_run_summary(command):
        commands_run.append(command[0])  # Track first element of command
        return {"ok": True, "output": "[]"}

    monkeypatch.setattr(main, "_run_summary", mock_run_summary)

    # Mock time
    clock = [1000.0]

    def mock_time():
        return clock[0]

    monkeypatch.setattr(main.time, "time", mock_time)

    with make_client(tmp_path, monkeypatch) as client:
        # First call - should run commands
        response = client.get("/packages", headers=headers())
        data = response.json()

        assert len(commands_run) == 3
        assert commands_run == ["python", "npm", "sh"]
        assert data["generated_at"] == 1000.0

        # Second call at 3599 seconds - should use cache
        clock[0] = 1000.0 + 3599
        response = client.get("/packages", headers=headers())
        data = response.json()

        assert len(commands_run) == 3  # No new commands
        assert data["generated_at"] == 1000.0  # Same timestamp

        # Third call at 3600 seconds - should recompute
        clock[0] = 1000.0 + 3600
        response = client.get("/packages", headers=headers())
        data = response.json()

        assert len(commands_run) == 6  # 3 new commands
        assert commands_run == ["python", "npm", "sh", "python", "npm", "sh"]
        assert data["generated_at"] == 4600.0
