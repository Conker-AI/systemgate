# Runtime inventory

`GET /runtime?limit=100` requires the existing `X-SystemGate-Key`; it returns
`Cache-Control: no-store`. It is an observation endpoint, not a control surface.
`systemgate/runtime.py` projects psutil and an optional injected container collector; no command,
restart, kill, container mutation, port edit, terminal, or file API is added.

The response includes `mode: observed`, `sampledAt` (UTC collection start),
`ageSeconds`, `collectionSeconds`, and source scopes. Process scope identifies
configured procfs versus the collector namespace; network scope is reported as
the collector namespace, and container scope says whether a source exists. These do not
assert that all three inventories describe the same host or namespace.

`processes`, `containers`, and `ports` each contain `results`, `status`
(`ok`, `partial`, `unavailable`), `truncated`, and bounded static error codes.
Failures retain successfully collected rows and never expose raw exceptions.
Top-level status is partial if any section fails or truncates. Empty successful
inventory remains distinguishable from unavailable collection.

Process IDs combine PID with exact floating-point creation time, checked again
against a fresh Process object to reject reused PIDs. Listener associations also
recheck that identity. Process RSS is bytes; CPU interval measurements, usernames,
and command lines are not collected. Their fields are null. Unmanaged processes
have no claimed start/restart definition or restart count. When an injected
container collector is present, container identity is the full container ID and
sparse list metadata avoids per-container inspect/stats calls. The shipped
deployment has no container collector. Container-to-process association and
restart count remain null.

Port rows distinguish observed TCP listeners/UDP bindings from container-published
port mappings. IPv6 addresses are preserved. A container mapping never establishes
reachability: `listening` and `bound` are null. UDP `bound: true` does not invent a
TCP listening state. Exposed-only ports without host publication are not
presented as host mappings. No claim is made that stopped configured mappings are
fully discoverable from sparse Docker inventory.

Result limits clamp to 1–200 rows **per section**, and process/listener scanning
stops after 2,000 entries. Ports share a row budget (listeners first, then container
bindings); truncation is explicit. Strings are bounded. Collector internals may materialize full OS socket/container
lists before projection: these limits bound scanning/output, not OS collector
allocation or an overall wall-clock deadline. Results are fresh per request and
not persisted. Capabilities explicitly advertise all mutation, terminal, and file
operations as unavailable. The frontend's fixture-only schema still requires a
separate adapter; this endpoint does not claim P14 completion.

Without a container source, `containers` is `unavailable` with
`container_telemetry_not_configured`; `ports` is `partial` with
`container_bindings_not_configured` while retaining observed OS listeners. This
is intentional: absence of daemon authority must never look like an empty host.

`python -m pytest tests/test_runtime.py -q` uses injected fake collectors and a
temporary authentication directory to verify identities/PID reuse, auth, no
mutation routes, partial failures, bounded scanning/output, and truthful bindings.
No live host inventory, Docker daemon, or external service is needed by these tests.
