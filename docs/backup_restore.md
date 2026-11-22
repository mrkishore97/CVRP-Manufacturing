# SQLite backup and restore guide

The app stores its data in one local SQLite database.

Default path:

```text
data/route_optimizer.db
```

The path can be changed with `DATABASE_PATH`.

## What is stored

- Saved scenarios.
- Solved plans: the newest `PLAN_HISTORY_LIMIT` (default 20) per scenario.
- Kept unsaved edits (drafts), one per scenario, until saved or discarded.
- The address cache: Google's matches for up to 30 days, keyed by a hash, without the
  address text. Expired rows are removed at every backend start.
- Cached travel times from the offline provider. Google travel times are never stored
  (decision D6).
- The schema version (`schema_meta`, version 2 since Version 1.1).

The database never stores Google API keys. Keys belong only in backend environment
configuration or the ignored local `.env` file.

At every start the backend removes Google content its terms do not allow it to keep:
Google travel times (from Version 1.0 databases) and coordinates older than 30 days. A
restored backup is cleaned the same way when the backend next starts.

Before upgrading from Version 1.0, take a backup: the first Version 1.1 start adds tables
and removes Google travel times, as described in [Deployment](deployment.md#upgrading-from-version-10).

## Backup while the app is stopped

The simplest backup is a file copy after stopping both backend and Streamlit:

```powershell
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
New-Item -ItemType Directory -Force backups | Out-Null
Copy-Item data/route_optimizer.db "backups/route_optimizer-$stamp.db"
```

## Backup while the app is running

Use SQLite's online backup command through Python:

```powershell
& .\.venv\Scripts\python.exe -c "import sqlite3; src=sqlite3.connect('data/route_optimizer.db'); dst=sqlite3.connect('backups/route_optimizer-online.db'); src.backup(dst); src.close(); dst.close()"
```

Create the `backups/` folder first if it does not exist.

## Restore

1. Stop Streamlit and backend.
2. Copy the current database aside:

   ```powershell
   Copy-Item data/route_optimizer.db data/route_optimizer.before_restore.db
   ```

3. Copy the backup into place:

   ```powershell
   Copy-Item backups/route_optimizer-YYYYMMDD-HHMMSS.db data/route_optimizer.db
   ```

4. Start the backend and frontend.
5. Load a known saved scenario and solve/export it as a smoke check.

## Retention suggestion

- Keep daily backups for 14 days.
- Keep weekly backups for 8 weeks.
- Keep one backup before any deployment or dependency upgrade.

Adjust retention to the plant's IT policy.
