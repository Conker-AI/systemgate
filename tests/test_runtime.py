import socket
from types import SimpleNamespace as NS
from unittest.mock import Mock

from fastapi.testclient import TestClient

from systemgate.runtime import collect


def sources():
    info = {
        "pid": 42,
        "create_time": 123.5,
        "name": "worker",
        "status": "sleeping",
        "memory_info": NS(rss=4096),
    }
    ps = Mock()
    ps.process_iter.return_value = [NS(info=info)]
    ps.Process.return_value.create_time.return_value = 123.5
    ps.net_connections.return_value = [
        NS(
            type=socket.SOCK_STREAM,
            status="LISTEN",
            laddr=NS(ip="127.0.0.1", port=8000),
            pid=42,
        ),
        NS(
            type=socket.SOCK_DGRAM,
            status="NONE",
            laddr=NS(ip="::", port=5353),
            pid=None,
        ),
    ]
    client = Mock()
    client.containers.list.return_value = [
        NS(
            attrs={
                "Id": "a" * 64,
                "Names": ["/worker"],
                "Image": "worker:1",
                "State": "running",
                "Ports": [
                    {
                        "IP": "0.0.0.0",
                        "PublicPort": 8888,
                        "PrivatePort": 8000,
                        "Type": "tcp",
                    }
                ],
            }
        )
    ]
    return ps, client


def test_observed_identity_bindings_truthful_unknown_fields():
    ps, client = sources()
    times = iter([1000, 1002])
    value = collect(ps, lambda: client, procfs="/host/proc", clock=lambda: next(times))
    assert value["status"] == "ok" and value["ageSeconds"] == 2
    assert value["sampledAt"].endswith("+00:00")
    process = value["processes"]["results"][0]
    assert process["id"] == "process:42:0x1.ee00000000000p+6"
    assert process["memoryBytes"] == 4096 and process["cpuPercent"] is None
    assert value["ports"]["results"][0]["processId"] == process["id"]
    assert value["ports"]["results"][1]["listening"] is None
    binding = value["ports"]["results"][2]
    assert binding["containerId"] == "a" * 64 and binding["targetPort"] == 8000
    assert binding["listening"] is None and binding["bound"] is None
    assert value["capabilities"]["processActions"] is False
    client.containers.list.assert_called_once_with(all=True, limit=101, sparse=True)
    client.close.assert_called_once()
    again = collect(ps, lambda: client, procfs="/host/proc")
    assert again["processes"]["results"][0]["id"] == process["id"]
    ps.process_iter.return_value[0].info["create_time"] = 124.5
    ps.Process.return_value.create_time.return_value = 124.5
    assert (
        collect(ps, lambda: client, procfs="/proc")["processes"]["results"][0]["id"]
        != process["id"]
    )


def test_partial_errors_never_echo_exception_and_keep_other_sections():
    ps, client = sources()
    client.containers.list.side_effect = RuntimeError("/private/secret socket token")
    value = collect(ps, lambda: client, procfs="/proc")
    assert value["status"] == "partial"
    assert value["containers"]["status"] == "unavailable"
    assert value["ports"]["status"] == "partial" and len(value["ports"]["results"]) == 2
    assert value["processes"]["status"] == "ok"
    assert "secret" not in str(value)
    client.close.assert_called_once()


def test_bounds_and_pid_reuse():
    ps, client = sources()
    original = ps.process_iter.return_value[0].info
    ps.process_iter.return_value = [NS(info={**original, "pid": pid}) for pid in range(42, 47)]
    value = collect(ps, lambda: client, procfs="/proc", limit=1)
    assert value["processes"]["truncated"] and value["ports"]["truncated"]
    assert all(
        len(value[s]["results"]) <= 1 for s in ("processes", "ports", "containers")
    )
    ps.Process.return_value.create_time.return_value = 999
    value = collect(ps, lambda: client, procfs="/proc")
    assert value["processes"]["results"] == []
    assert "process_changed_during_collection" in value["processes"]["errors"]
    assert value["ports"]["results"][0]["processId"] is None


def test_total_failure_is_not_empty_success():
    ps, client = sources()
    ps.process_iter.side_effect = PermissionError("private")
    ps.net_connections.side_effect = PermissionError("private")
    client.containers.list.side_effect = PermissionError("private")
    value = collect(ps, lambda: client, procfs="/proc")
    assert all(
        value[s]["status"] == "unavailable"
        for s in ("processes", "containers", "ports")
    )
    assert value["status"] == "partial" and "private" not in str(value)


def test_route_owner_auth_and_no_mutations(tmp_path, monkeypatch):
    monkeypatch.setenv("SYSTEMGATE_ADMIN_KEY", "test-runtime-key")
    monkeypatch.setenv("SYSTEMGATE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SYSTEMGATE_BACKUP_ROOT", str(tmp_path / "backups"))
    import dotenv

    monkeypatch.setattr(dotenv, "load_dotenv", lambda: None)
    from systemgate import main

    ps, client = sources()
    monkeypatch.setattr(main, "psutil", ps)
    monkeypatch.setattr(main, "procfs_path", lambda: "/proc")
    monkeypatch.setattr(main.docker, "from_env", lambda **kwargs: client)
    with TestClient(main.app) as api:
        assert api.get("/runtime").status_code == 401
        ps.process_iter.assert_not_called()
        response = api.get("/runtime", headers={"X-SystemGate-Key": "test-runtime-key"})
        assert response.status_code == 200 and response.json()["mode"] == "observed"
        assert (
            api.post(
                "/runtime", headers={"X-SystemGate-Key": "test-runtime-key"}
            ).status_code
            == 405
        )


def test_scan_bounds_and_malformed_container():
    ps, client = sources()
    consumed = []

    def processes(fields):
        for index in range(3000):
            consumed.append(index)
            yield NS(info={"pid": index + 1, "create_time": None})

    ps.process_iter.side_effect = processes
    client.containers.list.return_value = [
        NS(attrs={"Id": None}),
        NS(
            attrs={
                "Id": "real",
                "Names": ["x"],
                "Ports": [{"PublicPort": False, "PrivatePort": 80, "Type": "tcp"}],
            }
        ),
    ]
    value = collect(ps, lambda: client, procfs="/proc")
    assert len(consumed) == 2001 and value["processes"]["truncated"]
    assert value["containers"]["status"] == "partial"
    assert "invalid_container_binding" in value["ports"]["errors"]
    assert value["containers"]["results"][0]["id"] == "real"
