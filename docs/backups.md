# Backup integrity telemetry

What `GET /backups` verifies, and what it deliberately does not claim.

`GET /backups` verifies the `conker-snapshot-1` format from Companion's recovery script. It checks
the complete manifest, required stores, image identities, exact file inventory, sizes, SHA-256
hashes, PostgreSQL dump header and archive structure/required SQLite headers. Archives are read,
never extracted. A snapshot changing during verification is rejected.

`results` and `latest` contain only verified snapshots, ordered by the manifest's timezone-aware
`created_at`, never filesystem modification time. Every candidate is checked before the newest
20 verified entries are selected, so incomplete directories cannot hide a valid snapshot.
`rejected` separately lists up to 20 incomplete, invalid, unsupported or unverifiable directories;
`verified_count` and `rejected_count` give the full counts. Missing/unreadable roots report
`unavailable`, an empty root reports `empty`, and rejected candidates make the response `degraded`.
An incomplete directory does not become a recovery point merely because it has a recent name.

Verification reads the snapshot files in full on each request; large model archives can make
this endpoint slow. Poll it deliberately rather than at dashboard animation frequency. Responses
include `checked_at` and per-snapshot `verified_at`; there is no stale success cache. Hashes establish
consistency with the manifest, not authenticity against an attacker who can rewrite both.
`restore_status: not_tested` is explicit: this telemetry does not test decryption, restore a stack,
replay later deletions or reconcile actions. Manifest deletion-ledger and execution-journal states
are preserved instead of interpreting a complete snapshot as permission to resume.
