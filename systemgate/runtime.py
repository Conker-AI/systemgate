"""Bounded read-only runtime projection. Never infer management or socket reachability."""

import hashlib
import math
import socket
import time
from datetime import datetime, timezone

MAX_ROWS = 200
MAX_SCAN = 2000


def _text(value, limit=160):
    return str(value or "")[:limit]


def _number(value):
    return (
        value
        if type(value) in (int, float) and math.isfinite(value) and value >= 0
        else None
    )


def _identity(pid, created):
    return f"process:{pid}:{created.hex()}"


def collect(psutil, docker_factory, *, procfs, limit=100, clock=time.time):
    started = clock()
    sections = {
        key: {"status": "ok", "results": [], "truncated": False, "errors": []}
        for key in ("processes", "containers", "ports")
    }
    limit = max(1, min(limit, MAX_ROWS))

    def error(section, code, unavailable=False):
        value = sections[section]
        if code not in value["errors"]:
            value["errors"].append(code)
        value["status"] = (
            "unavailable" if unavailable and not value["results"] else "partial"
        )

    def add(section, row):
        value = sections[section]
        if len(value["results"]) >= limit:
            value["truncated"] = True
            return False
        value["results"].append(row)
        return True

    process_ids = {}
    try:
        for index, process in enumerate(
            psutil.process_iter(["pid", "create_time", "name", "status", "memory_info"])
        ):
            if index >= MAX_SCAN:
                sections["processes"]["truncated"] = True
                break
            try:
                info = process.info
                pid, created = info["pid"], _number(info.get("create_time"))
                if type(pid) is not int or pid <= 0 or created is None:
                    error("processes", "process_identity_unavailable")
                    continue
                created = float(created)
                if float(psutil.Process(pid).create_time()) != created:
                    error("processes", "process_changed_during_collection")
                    continue
                identity = _identity(pid, created)
                process_ids[pid] = (created, identity)
                if not add(
                    "processes",
                    {
                        "id": identity,
                        "pid": pid,
                        "createdAt": created,
                        "name": _text(info.get("name")),
                        "status": _text(info.get("status"), 40) or "unknown",
                        "memoryBytes": _number(
                            getattr(info.get("memory_info"), "rss", None)
                        ),
                        "cpuPercent": None,
                        "command": None,
                        "user": None,
                        "restarts": None,
                        "containerId": None,
                        "managed": False,
                    },
                ):
                    break
            except Exception:  # noqa: BLE001 - Collector failures must remain isolated and opaque.
                error("processes", "process_unavailable")
    except Exception:  # noqa: BLE001 - Collector failures must remain isolated and opaque.
        error("processes", "collection_failed", True)

    try:
        connections = psutil.net_connections(kind="inet")
        for index, conn in enumerate(connections):
            if index >= MAX_SCAN:
                sections["ports"]["truncated"] = True
                break
            protocol = {socket.SOCK_STREAM: "tcp", socket.SOCK_DGRAM: "udp"}.get(
                conn.type
            )
            if (
                not protocol
                or (protocol == "tcp" and conn.status != "LISTEN")
                or not conn.laddr
            ):
                continue
            address, port = _text(conn.laddr.ip, 64), conn.laddr.port
            process_id = None
            if conn.pid in process_ids:
                try:
                    created = float(psutil.Process(conn.pid).create_time())
                    if created == process_ids[conn.pid][0]:
                        process_id = process_ids[conn.pid][1]
                except Exception:  # noqa: BLE001 - Collector failures must remain isolated and opaque.
                    error("ports", "process_link_unavailable")
            key = f"{protocol}:{address}:{port}:{process_id or 'unknown'}"
            if not add(
                "ports",
                {
                    "id": "listener:" + hashlib.sha256(key.encode()).hexdigest(),
                    "kind": "listener",
                    "hostAddress": address,
                    "hostPort": port,
                    "protocol": protocol,
                    "processId": process_id,
                    "containerId": None,
                    "targetPort": None,
                    "listening": True if protocol == "tcp" else None,
                    "bound": True,
                },
            ):
                break
    except Exception:  # noqa: BLE001 - Collector failures must remain isolated and opaque.
        error("ports", "listener_collection_failed", True)

    client = None
    try:
        client = docker_factory()
        for index, container in enumerate(
            client.containers.list(all=True, limit=limit + 1, sparse=True)
        ):
            if index >= limit:
                sections["containers"]["truncated"] = True
                break
            try:
                attrs = container.attrs
                identity = attrs.get("Id")
                if not isinstance(identity, str) or not identity or len(identity) > 128:
                    error("containers", "container_identity_unavailable")
                    continue
                # Sparse Docker list metadata avoids per-container inspect/stats calls.
                names = attrs.get("Names") or []
                add(
                    "containers",
                    {
                        "id": identity,
                        "name": _text(names[0] if names else ""),
                        "image": _text(attrs.get("Image"), 256),
                        "status": _text(attrs.get("State"), 40) or "unknown",
                        "processId": None,
                        "restarts": None,
                        "managed": False,
                    },
                )
                for binding_index, binding in enumerate(attrs.get("Ports") or []):
                    if binding_index >= MAX_SCAN:
                        sections["ports"]["truncated"] = True
                        break
                    if "PublicPort" not in binding:
                        continue
                    protocol = binding.get("Type")
                    if protocol not in ("tcp", "udp"):
                        continue
                    address = _text(binding.get("IP"), 64)
                    public, private = (
                        binding.get("PublicPort"),
                        binding.get("PrivatePort"),
                    )
                    if any(
                        type(p) is not int or not 1 <= p <= 65535
                        for p in (public, private)
                    ):
                        error("ports", "invalid_container_binding")
                        continue
                    key = f"{identity}:{address}:{public}:{private}:{protocol}"
                    if not add(
                        "ports",
                        {
                            "id": "binding:" + hashlib.sha256(key.encode()).hexdigest(),
                            "kind": "container-binding",
                            "hostAddress": address,
                            "hostPort": public,
                            "targetPort": private,
                            "protocol": protocol,
                            "containerId": identity,
                            "processId": None,
                            "listening": None,
                            "bound": None,
                        },
                    ):
                        break
            except Exception:  # noqa: BLE001 - Collector failures must remain isolated and opaque.
                error("containers", "container_unavailable")
                error("ports", "container_bindings_unavailable")
    except Exception:  # noqa: BLE001 - Collector failures must remain isolated and opaque.
        error("containers", "collection_failed", True)
        error("ports", "container_bindings_unavailable", True)
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:  # noqa: BLE001 - Collector failures must remain isolated and opaque.
                error("containers", "client_close_failed")
    finished = clock()
    return {
        "mode": "observed",
        "sampledAt": datetime.fromtimestamp(started, timezone.utc).isoformat(),
        "ageSeconds": max(0, finished - started),
        "collectionSeconds": max(0, finished - started),
        "source": {
            "procfs": procfs,
            "processScope": "configured-procfs"
            if procfs != "/proc"
            else "collector-namespace",
            "networkScope": "collector-namespace",
            "containerScope": "configured-docker-daemon",
        },
        "status": "partial"
        if any(s["status"] != "ok" or s["truncated"] for s in sections.values())
        else "ok",
        **sections,
        "capabilities": {
            "inspection": True,
            "processActions": False,
            "containerActions": False,
            "portMutation": False,
            "terminal": False,
            "files": False,
        },
        "unavailableFields": [
            "cpuPercent (no sampling interval)",
            "command (not collected)",
            "user (not collected)",
            "restarts (no lifecycle ownership)",
            "container/process association",
            "container binding reachability",
        ],
    }
