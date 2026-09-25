# SystemGate security model

SystemGate is intentionally narrow. It exists so a local dashboard or agent harness can show operational state without receiving host write access.

- **Read-only API**: there are no write, exec, restart, package-install, file-edit, or Docker mutation endpoints. Package and log collection shell out to a fixed, non-injectable command set; no caller input reaches a shell.
- **Admin-key auth**: every endpoint except `/health` requires `X-SystemGate-Key`.
- **PBKDF2 key storage**: the first configured `SYSTEMGATE_ADMIN_KEY` is stored as a PBKDF2 hash under `data/admin-key.pbkdf2`; the raw key is not stored by SystemGate.
- **Server-side proxy friendly**: a dashboard can call SystemGate from its backend so the browser never receives the SystemGate key.
- **Loopback binding**: compose publishes the API on `127.0.0.1:8040` only.
- **Private Docker network**: the standalone compose file uses `systemgate_net` for local service-to-service traffic.
- **Read-only host mounts**: the Docker socket, `/proc`, the host root and the backup directory are all mounted `:ro`.
- **The host root mount is a deliberate trade-off, stated plainly**: reporting the host's disk usage requires the host filesystem to be visible, so `/` is mounted at `/host/root` read-only. This is what host telemetry exporters do, and it means anything able to read files from inside this container can read any file on the host. SystemGate exposes no file-read endpoint, and adding one would turn this mount into a serious hole. Drop the mount if you would rather have container-scoped disk figures; `/vitals` will say `scope: container` and remain truthful.
- **Says which machine it measured**: `/vitals` reports `source.scope` as `host` or `container`, with the procfs and disk paths actually in use - read back from psutil, not from the configuration, so it reports where the numbers came from rather than where they were asked to come from. Host figures require `SYSTEMGATE_PROCFS_PATH=/host/proc`, the host root mount and `uts: host`, all set by the bundled compose file. psutil honours no environment variable for procfs redirection, so SystemGate assigns `psutil.PROCFS_PATH` itself at import; setting an environment variable alone silently does nothing.
- **Bounded outputs**: process, log, package, backup, and container responses are capped so host telemetry cannot become an unbounded data leak.
- **No secret logging**: endpoints return system telemetry only; admin keys and upstream service secrets are not returned in responses.
- **Telemetry only**: SystemGate can observe Docker/container state, process lists, packages, logs, vitals, and backup timestamps, but it cannot change them.

In short: SystemGate is a read-only window, not a remote control.
