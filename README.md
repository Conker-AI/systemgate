<p align="center"><img src="https://raw.githubusercontent.com/Conker-AI/conker/main/dashboard/public/conker.png" width="64" alt="" /></p>
<h1 align="center">SystemGate</h1>
<p align="center"><b>A read-only window onto the machine. Not a remote control.</b><br/>
Host vitals, processes, packages, logs and verified backups, with no way to change any of them.</p>
<p align="center">
  <a href="https://github.com/Conker-AI/systemgate/actions/workflows/ci.yml"><img src="https://github.com/Conker-AI/systemgate/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <a href="https://github.com/Conker-AI/systemgate/tags"><img src="https://img.shields.io/github/v/tag/Conker-AI/systemgate?sort=semver&label=release" alt="Latest release" /></a>
  <img src="https://img.shields.io/badge/python-3.12-3776AB" alt="Python 3.12" />
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-AGPL--3.0-blue" alt="AGPL-3.0 license" /></a>
  <a href="https://github.com/Conker-AI/conker"><img src="https://img.shields.io/badge/part%20of-Conker-e36b2c" alt="Part of Conker" /></a>
</p>

SystemGate lets a dashboard or an agent see how the machine is doing without ever receiving write
access to it. By design there is no write, exec, restart, install or file-read
endpoint. Part of [Conker](https://github.com/Conker-AI/conker), and usable on its own.

## Where it fits

```mermaid
flowchart LR
    Pi[Conker's Pi<br/>or any dashboard] -->|admin key, server-side| SG[SystemGate]
    SG -.->|narrow read-only mounts| Host["/proc · backups"]
    classDef focus fill:#e36b2c,color:#fff,stroke:#b4521f
    class SG focus
```

## Endpoints

| Route | What it reports |
|---|---|
| `GET /health` | Real probes of procfs and the key store, plus capability state. No key. |
| `GET /vitals` | CPU, memory, disk and uptime, and whether they describe the **host** or the container. |
| `GET /containers` | Reports unavailable; SystemGate holds no Docker daemon credential. |
| `GET /processes` · `GET /services` | Processes, and listening services (metadata only). |
| `GET /packages` · `GET /logs/errors` | Installed packages and recent errors. |
| `GET /backups` | Snapshots whose manifest, hashes and archives verify. [Details](docs/backups.md) |
| `GET /runtime` | Processes, containers and ports in one bounded inventory. [Details](docs/runtime-inventory.md) |

Every route except `/health` needs `X-SystemGate-Key`. Every response is bounded.

## Quick start

Requires Docker with Compose. Published image: `ghcr.io/conker-ai/systemgate`.

```bash
cp .env.example .env              # then set SYSTEMGATE_ADMIN_KEY to a long random value
docker compose up -d --build
curl -H "X-SystemGate-Key: $KEY" http://127.0.0.1:8040/vitals
```

The API listens on `127.0.0.1:8040` only. Backups are read from `~/systemgate-backups` by default;
set `SYSTEMGATE_BACKUP_ROOT` to use another host directory.

## Security model, briefly

- **Read-only by construction.** Package and log collection use a fixed command set; no caller input
  reaches a shell.
- **Narrow read-only mounts.** Only `/proc` and the configured backup directory are mounted `:ro`.
- **No Docker authority.** The shipped container has no Docker socket and no host-root mount.
- **Truthful scope.** Host CPU/memory/process telemetry comes from `/proc`; disk figures are
  container-scoped, and `/vitals` says so.
- **Keys** are stored as PBKDF2 hashes. Use it from a server-side proxy so browsers never hold one.

Full model: [security](docs/security.md).

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest tests -q
```

## Documentation

| | |
|---|---|
| [Security model](docs/security.md) | Keys, mounts and what it can never do |
| [Backups](docs/backups.md) | Which snapshots count as verified |
| [Runtime inventory](docs/runtime-inventory.md) | Processes, containers and ports in one bounded view |

## License

[AGPL-3.0](LICENSE), version 3 only. Copyright (C) 2026 alexeybe1kin. Releases published before 24 October 2026 were under MIT and stay under MIT.
