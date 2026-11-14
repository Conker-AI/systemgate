"""Refusals and edge cases, driven through the HTTP API where a route reaches the code."""

from __future__ import annotations

import json
import socket
import sys
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from test_backups import save_manifest, snapshot

from systemgate import auth
from systemgate.config import ConfigError
from systemgate.runtime import MAX_SCAN, collect

KEY = "refusal-test-key-1234"


def configure(tmp_path, monkeypatch, **extra):
    monkeypatch.setenv("SYSTEMGATE_ADMIN_KEY", KEY)
    monkeypatch.setenv("SYSTEMGATE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SYSTEMGATE_BACKUP_ROOT", str(tmp_path / "backups"))
    for name, value in extra.items():
        monkeypatch.setenv(name, value)
    from systemgate.main import app

    return app


def get(client, path):
    return client.get(path, headers={"X-SystemGate-Key": KEY})


# Configuration


@pytest.mark.parametrize("value", ["not-a-number", "", "0", "65536", "-1"])
def test_an_unusable_port_stops_the_service_before_it_serves(tmp_path, monkeypatch, value):
    app = configure(tmp_path, monkeypatch, SYSTEMGATE_PORT=value)
    with pytest.raises(ConfigError, match="SYSTEMGATE_PORT") as raised, TestClient(app):
        pass
    assert KEY not in str(raised.value)


@pytest.mark.parametrize("value", ["1", "8040", "65535"])
def test_the_edges_of_the_port_range_are_accepted(tmp_path, monkeypatch, value):
    app = configure(tmp_path, monkeypatch, SYSTEMGATE_PORT=value)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200


# Keys


@pytest.mark.parametrize("encoded", ["", "no-separator", "!!!$???", "AAAA$", "$"])
def test_a_malformed_stored_hash_never_matches(encoded):
    assert auth.verify_key("any-key-1234", encoded) is False


def test_an_empty_or_missing_key_never_matches():
    encoded = auth.hash_key("right-key-1234")
    assert auth.verify_key(None, encoded) is False
    assert auth.verify_key("", encoded) is False


def test_a_corrupt_stored_hash_is_replaced_by_the_configured_key(tmp_path, monkeypatch):
    stored = tmp_path / "data" / "admin-key.pbkdf2"
    stored.parent.mkdir(parents=True)
    stored.write_text("garbage-without-a-separator", encoding="utf-8")
    app = configure(tmp_path, monkeypatch)
    with TestClient(app) as client:
        assert get(client, "/containers").status_code == 200
        assert client.get("/containers", headers={"X-SystemGate-Key": "wrong"}).status_code == 401
    assert "garbage" not in stored.read_text(encoding="utf-8")


def test_a_stored_hash_that_cannot_be_read_still_refuses_every_key(tmp_path, monkeypatch):
    app = configure(tmp_path, monkeypatch)
    with TestClient(app) as client:
        (tmp_path / "data" / "admin-key.pbkdf2").write_text("", encoding="utf-8")
        assert get(client, "/vitals").status_code == 401
        health = client.get("/health").json()
    assert health["checks"]["admin_key"]["status"] == "ok"


# Backups through GET /backups


def listing(tmp_path, monkeypatch):
    app = configure(tmp_path, monkeypatch)
    with TestClient(app) as client:
        response = get(client, "/backups")
    assert response.status_code == 200
    return response.json()


def test_a_manifest_that_is_not_an_object_is_rejected(tmp_path, monkeypatch):
    directory = snapshot(tmp_path / "backups")
    (directory / "manifest.json").write_text(json.dumps(["secret-do-not-print"]))
    body = listing(tmp_path, monkeypatch)
    assert body["latest"] is None and body["rejected_count"] == 1
    assert body["rejected"][0]["status"] == "invalid"
    assert "secret-do-not-print" not in json.dumps(body)


def test_an_oversized_manifest_is_rejected_without_being_parsed(tmp_path, monkeypatch):
    directory = snapshot(tmp_path / "backups")
    (directory / "manifest.json").write_text('{"pad": "' + "x" * (4 * 1024 * 1024) + '"}')
    body = listing(tmp_path, monkeypatch)
    assert body["latest"] is None
    assert "supported size" in body["rejected"][0]["reason"]


def test_a_manifest_time_without_a_zone_is_rejected(tmp_path, monkeypatch):
    directory = snapshot(tmp_path / "backups", created="2026-01-01T00:00:00")
    assert directory.is_dir()
    body = listing(tmp_path, monkeypatch)
    assert body["latest"] is None
    assert "creation time" in body["rejected"][0]["reason"]


def test_a_snapshot_dated_in_the_future_is_rejected(tmp_path, monkeypatch):
    snapshot(tmp_path / "backups", created="2999-01-01T00:00:00+00:00")
    body = listing(tmp_path, monkeypatch)
    assert body["latest"] is None
    assert "creation time" in body["rejected"][0]["reason"]


def test_a_manifest_missing_required_files_is_rejected(tmp_path, monkeypatch):
    directory = snapshot(tmp_path / "backups")
    manifest = json.loads((directory / "manifest.json").read_text())
    save_manifest(directory, manifest)
    manifest = json.loads((directory / "manifest.json").read_text())
    del manifest["files"]["pi.tar"]
    (directory / "manifest.json").write_text(json.dumps(manifest))
    body = listing(tmp_path, monkeypatch)
    assert body["latest"] is None
    assert "missing from the manifest" in body["rejected"][0]["reason"]


def test_a_manifest_with_files_that_is_not_a_mapping_is_rejected(tmp_path, monkeypatch):
    directory = snapshot(tmp_path / "backups")
    manifest = json.loads((directory / "manifest.json").read_text())
    manifest["files"] = ["pi.tar"]
    (directory / "manifest.json").write_text(json.dumps(manifest))
    body = listing(tmp_path, monkeypatch)
    assert body["latest"] is None and body["rejected_count"] == 1


def test_a_plain_file_in_the_backup_root_is_not_a_snapshot(tmp_path, monkeypatch):
    root = tmp_path / "backups"
    snapshot(root)
    (root / "notes.txt").write_text("not a snapshot")
    body = listing(tmp_path, monkeypatch)
    assert body["verified_count"] == 1 and body["rejected_count"] == 0
    assert [row["name"] for row in body["results"]] == ["snapshot-a"]


def test_one_bad_snapshot_does_not_hide_a_good_one(tmp_path, monkeypatch):
    root = tmp_path / "backups"
    snapshot(root, "good", "2026-01-01T00:00:00+00:00")
    bad = snapshot(root, "bad", "2026-02-01T00:00:00+00:00")
    (bad / "pi.tar").write_bytes(b"changed after the manifest was written")
    body = listing(tmp_path, monkeypatch)
    assert body["latest"]["name"] == "good"
    assert [row["name"] for row in body["rejected"]] == ["bad"]


def test_the_backup_listing_needs_the_key(tmp_path, monkeypatch):
    app = configure(tmp_path, monkeypatch)
    with TestClient(app) as client:
        assert client.get("/backups").status_code == 401
        assert client.get("/backups", headers={"X-SystemGate-Key": "wrong"}).status_code == 401


# Routes that take a limit


def test_runtime_limit_is_clamped_to_its_bounds(tmp_path, monkeypatch):
    import systemgate.runtime as runtime

    seen = []

    real = runtime.collect
    monkeypatch.setattr(
        runtime, "collect", lambda *a, **k: seen.append(k["limit"]) or real(*a, **k)
    )
    app = configure(tmp_path, monkeypatch)
    with TestClient(app) as client:
        assert get(client, "/runtime?limit=0").status_code == 200
        assert get(client, "/runtime?limit=100000").status_code == 200
        assert get(client, "/runtime?limit=abc").status_code == 422
    assert seen == [0, 100000]


@pytest.mark.parametrize("path", ["/services?limit=abc", "/processes?limit=abc"])
def test_a_non_numeric_limit_is_refused(tmp_path, monkeypatch, path):
    app = configure(tmp_path, monkeypatch)
    with TestClient(app) as client:
        assert get(client, path).status_code == 422


@pytest.mark.parametrize(
    "path", ["/vitals", "/services", "/containers", "/processes", "/logs/errors", "/packages"]
)
def test_every_inventory_route_refuses_a_wrong_key(tmp_path, monkeypatch, path):
    app = configure(tmp_path, monkeypatch)
    with TestClient(app) as client:
        assert client.get(path).status_code == 401
        assert client.get(path, headers={"X-SystemGate-Key": "wrong-key-1234"}).status_code == 401


def test_no_route_accepts_a_write(tmp_path, monkeypatch):
    app = configure(tmp_path, monkeypatch)
    with TestClient(app) as client:
        for path in ("/vitals", "/services", "/processes", "/containers", "/backups", "/packages"):
            for method in ("post", "put", "patch", "delete"):
                response = getattr(client, method)(path, headers={"X-SystemGate-Key": KEY})
                assert response.status_code == 405, (method, path)


def test_a_denied_disk_reading_is_reported_as_null(tmp_path, monkeypatch):
    from systemgate import main

    monkeypatch.setattr(main.psutil, "disk_usage", Mock(side_effect=OSError("denied")))
    app = configure(tmp_path, monkeypatch)
    with TestClient(app) as client:
        body = get(client, "/vitals").json()
    assert body["disk"] is None
    assert body["source"]["disk_path"]


@pytest.mark.skipif(sys.platform == "win32", reason="sensors are not offered on Windows")
def test_a_machine_without_sensors_reports_no_temperatures(tmp_path, monkeypatch):
    from systemgate import main

    monkeypatch.setattr(main.psutil, "sensors_temperatures", Mock(side_effect=OSError("none")))
    app = configure(tmp_path, monkeypatch)
    with TestClient(app) as client:
        assert get(client, "/vitals").json()["temps"] == {}


# The runtime collector's edges (its psutil and Docker inputs are the only fakes)


def process(pid=42, created=123.5, **extra):
    info = {
        "pid": pid,
        "create_time": created,
        "name": "worker",
        "status": "sleeping",
        "memory_info": NS(rss=4096),
        **extra,
    }
    return NS(info=info)


def listener(port=8000, pid=42, kind=socket.SOCK_STREAM, status="LISTEN", laddr=True):
    return NS(
        type=kind,
        status=status,
        laddr=NS(ip="127.0.0.1", port=port) if laddr else None,
        pid=pid,
    )


def fakes(processes=None, connections=None, containers=None):
    ps = Mock()
    ps.process_iter.return_value = [process()] if processes is None else processes
    ps.Process.return_value.create_time.return_value = 123.5
    ps.net_connections.return_value = [listener()] if connections is None else connections
    client = Mock()
    client.containers.list.return_value = [] if containers is None else containers
    return ps, client


def test_a_process_row_that_breaks_costs_only_that_row():
    ps, client = fakes(processes=[NS(info={"create_time": 1.0}), process()])
    value = collect(ps, lambda: client, procfs="/proc")
    assert value["processes"]["status"] == "partial"
    assert value["processes"]["errors"] == ["process_unavailable"]
    assert [row["pid"] for row in value["processes"]["results"]] == [42]


def test_a_repeated_process_is_listed_once():
    ps, client = fakes(processes=[process(), process()])
    value = collect(ps, lambda: client, procfs="/proc")
    assert len(value["processes"]["results"]) == 1
    assert value["processes"]["errors"] == []


def test_listeners_that_are_not_listening_or_have_no_address_are_left_out():
    connections = [
        listener(port=1, status="ESTABLISHED"),
        listener(port=2, laddr=False),
        listener(port=3, kind=socket.SOCK_RAW),
        listener(port=4),
    ]
    ps, client = fakes(connections=connections)
    value = collect(ps, lambda: client, procfs="/proc")
    assert [row["hostPort"] for row in value["ports"]["results"]] == [4]


def test_a_listener_whose_process_cannot_be_checked_keeps_no_link():
    ps, client = fakes()
    ps.Process.side_effect = [Mock(create_time=Mock(return_value=123.5)), OSError("gone")]
    value = collect(ps, lambda: client, procfs="/proc")
    assert value["ports"]["results"][0]["processId"] is None
    assert "process_link_unavailable" in value["ports"]["errors"]
    assert "gone" not in str(value)


def test_a_huge_connection_table_is_cut_at_the_scan_limit():
    connections = [listener(port=1 + index, status="ESTABLISHED") for index in range(MAX_SCAN + 5)]
    ps, client = fakes(connections=connections)
    value = collect(ps, lambda: client, procfs="/proc", limit=200)
    assert value["ports"]["truncated"] is True
    assert value["status"] == "partial"


def test_containers_beyond_the_limit_are_reported_as_truncated():
    containers = [NS(attrs={"Id": f"id{index}", "Names": [f"/c{index}"]}) for index in range(4)]
    ps, client = fakes(containers=containers)
    value = collect(ps, lambda: client, procfs="/proc", limit=2)
    assert len(value["containers"]["results"]) == 2
    assert value["containers"]["truncated"] is True
    client.containers.list.assert_called_once_with(all=True, limit=3, sparse=True)


def test_container_port_bindings_that_cannot_be_used_are_skipped():
    ports = [
        {"Type": "tcp", "PrivatePort": 80},
        {"Type": "sctp", "PublicPort": 81, "PrivatePort": 81},
        {"Type": "tcp", "PublicPort": 70000, "PrivatePort": 80},
        {"Type": "udp", "PublicPort": 53, "PrivatePort": 53, "IP": "0.0.0.0"},
    ]
    ps, client = fakes(
        connections=[], containers=[NS(attrs={"Id": "abc", "Names": [], "Ports": ports})]
    )
    value = collect(ps, lambda: client, procfs="/proc")
    assert [row["hostPort"] for row in value["ports"]["results"]] == [53]
    assert value["ports"]["errors"] == ["invalid_container_binding"]
    assert value["containers"]["results"][0]["name"] == ""


def test_a_huge_binding_list_is_cut_at_the_scan_limit():
    ports = [{"Type": "tcp", "PrivatePort": 80} for _ in range(MAX_SCAN + 3)]
    ps, client = fakes(connections=[], containers=[NS(attrs={"Id": "abc", "Ports": ports})])
    value = collect(ps, lambda: client, procfs="/proc", limit=200)
    assert value["ports"]["truncated"] is True


def test_a_container_whose_details_fail_costs_only_that_container():
    class Broken:
        @property
        def attrs(self):
            raise RuntimeError("/var/run/docker.sock refused")

    ps, client = fakes(
        connections=[], containers=[Broken(), NS(attrs={"Id": "ok", "Names": ["/a"]})]
    )
    value = collect(ps, lambda: client, procfs="/proc")
    assert value["containers"]["errors"] == ["container_unavailable"]
    assert "container_bindings_unavailable" in value["ports"]["errors"]
    assert [row["id"] for row in value["containers"]["results"]] == ["ok"]
    assert "docker.sock" not in str(value)


def test_a_container_client_that_fails_to_close_is_reported_not_raised():
    ps, client = fakes()
    client.close.side_effect = RuntimeError("socket path /run/docker.sock")
    value = collect(ps, lambda: client, procfs="/proc")
    assert "client_close_failed" in value["containers"]["errors"]
    assert value["status"] == "partial"
    assert "docker.sock" not in str(value)


def test_a_store_the_archive_cannot_open_is_never_a_recovery_point(tmp_path, monkeypatch):
    import tarfile

    snapshot(tmp_path / "backups")
    monkeypatch.setattr(tarfile.TarFile, "extractfile", lambda self, member: None)
    body = listing(tmp_path, monkeypatch)
    assert body["latest"] is None
    assert "not a file" in body["rejected"][0]["reason"]
