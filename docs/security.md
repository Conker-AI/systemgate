# SystemGate security model

SystemGate is intentionally narrow. It exists so a local dashboard or agent harness can show operational state without receiving host write access.

- **Read-only API**: there are no write, exec, restart, package-install, file-edit, or Docker mutation endpoints. Package and log collection shell out to a fixed, non-injectable command set; no caller input reaches a shell.
- **Admin-key auth**: every endpoint except `/health` requires `X-SystemGate-Key`.
- **PBKDF2 key storage**: the first configured `SYSTEMGATE_ADMIN_KEY` is stored as a PBKDF2 hash under `data/admin-key.pbkdf2`; the raw key is not stored by SystemGate. Once a key has matched (at startup, from the configured key), later requests compare a SHA-256 of the presented key in constant time instead of running PBKDF2 again, so a caller sending wrong keys cannot tie up the service with slow hashing. A new key file is checked in full again.
- **Server-side proxy friendly**: a dashboard can call SystemGate from its backend so the browser never receives the SystemGate key.
- **Loopback binding**: compose publishes the API on `127.0.0.1:8040` only.
- **Private Docker network**: the standalone compose file uses `systemgate_net` for local service-to-service traffic.
- **Narrow host mounts**: only `/proc` and the configured backup directory are mounted read-only. The shipped deployment mounts neither the Docker socket nor the host root.
- **No Docker daemon credential**: a read-only bind flag does not make Docker's API read-only, so SystemGate does not connect to the daemon. Container inventory and Docker-published port mappings report unavailable instead of silently becoming empty results.
- **Container-scoped disk figures**: the host root is not visible to SystemGate. `/vitals` reports the disk path and scope so callers do not mistake container filesystem capacity for host capacity.
- **Says which machine it measured**: `/vitals` reports `source.scope` as `host` or `container`, with the procfs and disk paths actually in use - read back from psutil, not from the configuration, so it reports where the numbers came from rather than where they were asked to come from. Host figures require `SYSTEMGATE_PROCFS_PATH=/host/proc`, the host root mount and `uts: host`, all set by the bundled compose file. psutil honours no environment variable for procfs redirection, so SystemGate assigns `psutil.PROCFS_PATH` itself at import; setting an environment variable alone silently does nothing.
- **Bounded outputs**: process, log, package, backup, and container responses are capped so host telemetry cannot become an unbounded data leak.
- **No command lines**: `/processes`, `/services` and `/runtime` never collect a process's command line or environment, which often carry passwords and keys.
- **Clean text**: log and package output loses terminal control codes, and a command that cannot run is reported by its kind of error, not its message.
- **No secret logging**: endpoints return system telemetry only; admin keys and upstream service secrets are not returned in responses.
- **Telemetry only**: SystemGate can observe process lists, packages, journal errors, vitals, and backup timestamps, but it cannot change them. Container telemetry requires a future least-authority collector contract; it is not inferred from daemon access.

In short: SystemGate is a read-only window, not a remote control.
