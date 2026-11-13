# Local maintenance and recovery

AdCraft remains a local application with its existing SQLite task runtime. Redis,
a separate broker, and microservices are not required for these operations.

## Before updating

From `apps/api`, inspect the configured data directory. The native launcher uses
`../../runtime-data/api`; replace this path when `MEDIA_DATA_DIR` is customized.

```sh
uv run python -m app.cli.local_maintenance check --data-dir ../../runtime-data/api --require-idle
```

The command checks database integrity, schema revision, pending work and local tool
availability without starting workers or contacting providers. A nonzero exit code
with active work means the update should wait. The reported record counts can refer
to different stages of the same task and must not be added as independent job counts.

After work finishes, stop API, Agent and Web with the existing deployment stop
command. Keep the services stopped while creating the maintenance backup:

```sh
uv run python -m app.cli.local_maintenance backup --data-dir ../../runtime-data/api
```

The JSON response identifies the database snapshot and its checksum manifest.
Keep `.env` files and the deployment configuration in a private backup location, and
retain the complete `data/assets` directory. A database snapshot contains project
records, installation model defaults and node settings; it does not contain media
files or environment credentials. A portable backup must include those separately.

Update the application with the existing deployment launcher. On startup, every
pending schema upgrade also receives a verified database snapshot under
`<MEDIA_DATA_DIR>/v2/migration-backups/database/` before Alembic changes the database.
Starting an already-current database does not create another upgrade snapshot.

## Verify a snapshot

```sh
uv run python -m app.cli.local_maintenance verify-backup \
  --database /path/to/adcraft.pre-upgrade-SNAPSHOT.sqlite3 \
  --manifest /path/to/adcraft.pre-upgrade-SNAPSHOT.manifest.json
```

Verification checks the recorded SHA-256 and SQLite integrity without restoring it.
It does not start generation or retry paid requests.

## Recover after a failed upgrade

1. Stop API, Agent and Web. Preserve the entire failed data directory for diagnosis.
2. Verify the snapshot from immediately before the failed upgrade. Read its
   `source_revision` and use the matching previous application release.
3. Create a separate recovery data directory. Copy the verified snapshot to
   `v2/adcraft.sqlite3` and copy the preserved `assets/` directory alongside `v2/`.
   Keep the matching environment configuration. Do not copy SQLite `-wal` or `-shm`
   files from the failed database onto the restored snapshot.
4. Point `MEDIA_DATA_DIR` at the recovery directory and start the previous release
   with the supported supervisor. Confirm `/api/v2/health`, open an existing
   project and verify that its media is accessible before creating new work.

The backup does not undo requests already accepted by a provider. Recovery reuses
durable task identities; do not mass-regenerate nodes to recover downloaded results.
Media removed after the snapshot needs a separate media backup to be recovered.

## Local activity

API Space contains **Local activity**, loaded on request. It summarizes the latest
5,000 execution records updated in the last seven days, with explicit truncation,
outcome counts, observed successful durations and error-code counts. These are local
execution outcomes, not provider billing records or a global model availability
score. Missing durations and costs stay unknown.

## Configuration and concurrency

Installation model defaults, explicit node choices and frozen run parameters keep
their existing separate authorities. Changes to a default apply through the normal
model resolver; they do not rewrite a node's explicit choice or an accepted run.

`V2_MAX_PARALLEL_IMAGE_JOBS`, `V2_MAX_PARALLEL_VIDEO_JOBS`,
`V2_MAX_PARALLEL_AUDIO_JOBS`, and `V2_MAX_PARALLEL_GENERATION_JOBS` now reserve
capacity across projects sharing the database. Remote tasks still consume capacity
while waiting for their provider. Queue saturation leaves work queued for the next
local scheduling cycle.
