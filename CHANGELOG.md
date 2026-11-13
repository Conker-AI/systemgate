# Changelog

Versions are the module's own, not an API revision. A change to the shape of
`/health` or any endpoint is a contract change and gets its own entry —
replacing a module has to be a decision with visible consequences.

## Unreleased

## 0.5.3

- **A changed `SYSTEMGATE_ADMIN_KEY` takes effect at the next start.** The first key's hash
  was kept for good, so after a rotation the old key still worked and the new one was refused.
  Now a configured key that does not match the stored hash replaces it (written owner-only,
  then swapped in); with no key configured the stored one stays.
- **Only 100.64.0.0/10 is labelled `tailscale`** in `/services`. Every `100.x` listener was,
  so a public address such as 100.1.2.3 read as private.

- **Each tag gets a GitHub Release page and an SBOM.** The Release page's notes are the
  version's CHANGELOG section. Every image carries an SPDX SBOM (BuildKit attestation) inside
  the image index, and the signed build provenance covers that index digest. Check one with
  `gh attestation verify oci://IMAGE@DIGEST --owner Conker-AI`.
- **Repository tooling, no behaviour change.** The shared .editorconfig, pre-commit hooks that run
  the CI checks, CODEOWNERS and Renovate config; ruff format; a pyright type check with one error baselined
  (the baseline may only shrink); CI fails below 93% test coverage. (#20)

## 0.5.2

- **The image takes Debian's zlib security fix** (zlib1g CVE-2026-76844 and CVE-2026-85091,
  fixed in 1:1.3.dfsg+really1.3.1-1+deb13u1). Rebuild only, no code change.

## 0.5.1

- **The image takes Debian's security fixes newer than its base** (apt, CVE-2026-109518).
  No code change.

## 0.5.0

- **Unavailable data is reported, not hidden or failed.** `/vitals` answers `disk: null` when
  `SYSTEMGATE_DISK_PATH` is invalid instead of a 500; `/services` answers
  `status: "unavailable"` with `errors: ["service_enumeration_unavailable"]` when the host denies
  the listing, instead of an empty inventory reported as success. An invalid or out-of-range
  `SYSTEMGATE_PORT` stops startup with a clear configuration error.

- **Backup verification reads each archive once instead of twice.** `GET /backups` hashed every
  snapshot file and then read every archive member's payload to the end, doubling the disk reads
  of large model archives on each request. The hash already proves the bytes match the manifest,
  and the tar header walk rejects the same truncated archives, so members are now checked by
  their headers, plus the first 16 bytes of each required SQLite store.

- **`/processes` no longer returns command lines, and wrong keys no longer cost PBKDF2.**
  `/processes` listed each host process's command line, which can carry a password or
  a key; it now returns the same metadata as `/runtime` (pid, name, user, CPU, memory).
  Every admin request ran 200,000 rounds of PBKDF2, so anyone who could reach the port
  could tie up the service with wrong keys; after the first match (at startup, from the
  configured key) a constant-time SHA-256 compare decides. Journal and package output
  loses terminal control codes, and a command that cannot run reports only its kind of
  error.

## 0.4.0

- **Remove Docker daemon and host-root authority from the shipped container.**
  Compose no longer mounts `/var/run/docker.sock` or `/`. Container telemetry
  now reports explicitly unavailable while bounded procfs, listener, backup and
  container-scoped disk telemetry continue to work. The Docker SDK dependency
  and Docker log scraping path have also been removed.
- A weekly security check (`.github/workflows/security.yml`) audits every dependency this
  repository ships against the public advisory databases each Monday and whenever they
  change, and fails loudly.

## 0.3.0

- Publish bounded read-only runtime inventory with explicit partial and unavailable
  results and stable duplicate observations.
- Keep truncated inventory references consistent without claiming unseen host data.

## 0.2.3

- **Backup telemetry reads the mounted location and verifies what it reports.**
  It looked under a path that did not exist in the container, and treated any
  directory as a backup, choosing the latest by modification time — so an
  incomplete snapshot could be shown as the newest recovery point. It now reads
  the real backup root, verifies manifests and hashes, and reports incomplete or
  unreadable snapshots separately.


- Align the container backup root with its `/backups` mount. Verify complete
  `conker-snapshot-1` manifests, inventories, hashes and archives before listing
  recovery candidates. Select latest by manifest creation time; report rejected
  candidates and unavailable roots explicitly. Integrity verification is separate
  from restore readiness, deletion replay and action reconciliation.

## 0.2.2

- **`/health` reported `0.1.0` while the module shipped as v0.2.1.** The
  version was hardcoded in the FastAPI constructor, where nothing pointed at
  it during a release. It is a named constant now, so `/health` and the
  OpenAPI document cannot drift apart again. A health contract is only worth
  having if it can be believed.
- **`.dockerignore`, and a CI job that builds the image and searches it for
  secrets.** This build context was already clean; ToolGate's was not, and
  shipped a real `.env` to the registry. The check belongs in every module,
  because the next leak will be in whichever repository nobody thought to
  look at.

## 0.2.1

Publish workflow only: attestation is skipped while the repository is private,
so a successful image push is no longer reported as a failure.

## 0.2.0

**`/vitals` was describing the container, not the host.** `docker-compose.yml`
mounted `/proc` at `/host/proc`, but nothing referenced it: psutil resolves
procfs from a module attribute and honours **no** environment variable for it,
so the mount sat inert while every figure came from this container. Setting
`PROCFS_PATH` in compose looked correct and did nothing. SystemGate now assigns
`psutil.PROCFS_PATH` in code from `SYSTEMGATE_PROCFS_PATH`, mounts the host root
read-only for disk figures, and shares the host UTS namespace so the hostname is
the host's — `/proc/sys/kernel/hostname` resolves from the reading process's
namespace, not from the mount, so bind-mounting alone could never fix it.

**`/vitals` now reports `source`** — the procfs and disk paths in use, read back
from psutil rather than from configuration, and whether the scope is `host` or
`container`. Either is legitimate; leaving the caller to guess which produced a
number is not.

**`/health` probed nothing.** It returned a hardcoded `ok`, so a broken Docker
socket left `/containers` failing while health claimed all was well. It now
probes procfs, the Docker socket and the admin key store, and reports `degraded`
naming what failed. Detail stays coarse because the route is unauthenticated.

**`/health` now answers in the shared module contract shape** — `service`,
`version`, `status`, `degraded`, `checks` keyed by name, `checked_at`,
`age_seconds` — so one dashboard renders any module without special cases.

**README corrected.** `/services` was undocumented, making eight endpoints not
seven. The "no shell" claim overstated the code: package and log collection do
shell out, to a fixed non-injectable command set, which is a stronger statement
than a slogan that does not survive reading the source. The host root mount is
documented as the trade-off it is.

## 0.1.0

First release. Read-only host telemetry: health, vitals, containers, processes,
error logs, packages, backups, services. Admin-key auth on every route except
`/health`, PBKDF2 key storage, loopback binding, bounded outputs.
