<p align="center"><img src="https://raw.githubusercontent.com/Conker-AI/conker/main/dashboard/public/conker.png" width="64" alt="" /></p>
<h1 align="center">SystemGate</h1>
<p align="center"><b>A read-only window onto the machine. Not a remote control.</b><br/>
Host vitals, containers, processes, packages, logs and verified backups, with no way to change any of them.</p>
<p align="center">
  <a href="https://github.com/Conker-AI/systemgate/actions/workflows/ci.yml"><img src="https://github.com/Conker-AI/systemgate/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <img src="https://img.shields.io/badge/python-3.12-3776AB" alt="Python 3.12" />
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT license" /></a>
  <a href="https://github.com/Conker-AI/conker"><img src="https://img.shields.io/badge/part%20of-Conker-e36b2c" alt="Part of Conker" /></a>
</p>

SystemGate lets a dashboard or an agent see how the machine is doing without ever receiving write
access to it. By design there is no write, exec, restart, install or file-read
endpoint. Part of [Conker](https://github.com/Conker-AI/conker), and usable on its own.

## Where it fits

```mermaid
flowchart LR
    Pi[Conker's Pi<br/>or any dashboard] -->|admin key, server-side| SG[SystemGate]
    SG -.->|read-only mounts| Host["/proc · Docker socket · disk · backups"]
    classDef focus fill:#e36b2c,color:#fff,stroke:#b4521f
    class SG focus
```

## Endpoints

| Route | What it reports |
|---|---|
| `GET /health` | Real probes of procfs, the Docker socket and the key store. No key. |
| `GET /vitals` | CPU, memory, disk and uptime, and whether they describe the **host** or the container. |
| `GET /containers` | Docker containers and their state. |
| `GET /processes` · `GET /services` | Processes, and listening services (metadata only). |
| `GET /packages` · `GET /logs/errors` | Installed packages and recent errors. |
| `GET /backups` | Snapshots whose manifest, hashes and archives verify. [Details](docs/backups.md) |
| `GET /runtime` | Processes, containers and ports in one bounded inventory. [Details](docs/runtime-inventory.md) |

Every route except `/health` needs `X-SystemGate-Key`. Every response is bounded.

## Quick start

Requires Docker with Compose.

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
- **Read-only mounts.** The Docker socket, `/proc`, the host root and backups are mounted `:ro`.
- **Stated trade-off.** Host disk figures need the host root visible inside the container. Drop the
  mount for container-only figures, and `/vitals` will say so.
- **Keys** are stored as PBKDF2 hashes. Use it from a server-side proxy so browsers never hold one.

Full model: [security](docs/security.md).

## Development

```bash
pip install -r requirements.txt pytest httpx
python -m pytest tests -q
```

## License

[MIT](LICENSE)
