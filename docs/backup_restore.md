# SQLite backup and restore guide

Version 1 stores scenarios, plans, and route-matrix cache entries in a local
SQLite database.

Default path:

```text
data/route_optimizer.db
```

The path can be changed with `DATABASE_PATH`.

## What is stored

- Saved scenario payloads.
- Saved plan results.
- Cached route matrices.

The database should not store Google API keys. Keys belong only in backend
environment configuration or the ignored local `.env` file.

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
