# Zero-Downtime Deploys — Cutover Runbook

**Why:** every deploy causes a ~2-minute 502 because the SQLite database lives on a
Render **persistent disk** (single-attach) — Render must stop the old instance before
the new one can mount the disk. Moving the database to **managed Postgres** removes the
disk, which lets Render run old + new at once and switch with **no downtime**.

The code already supports both: `CHORDENTIAL_DB` as a path → SQLite (today); as a
`postgresql://…` URL → Postgres. Nothing else changes. **Follow these steps in order —
the data migration must happen before the disk is removed, or live data is lost.**

---

## Step 0 — the code is already deployed (safe)
The compatibility layer (`web/db.py`) shipped with this change. The app is still running
on SQLite-on-disk exactly as before — no behavior change. ✅ Verify the live site works
normally before continuing.

## Step 1 — create the Render Postgres database
Render dashboard → **New → PostgreSQL** (same region as the web service). Note its
**Internal Database URL** (`postgresql://…`). A `basic-256mb` plan is plenty to start.

## Step 2 — migrate the data (run ON Render, where both DBs are reachable)
Open the web service's **Shell** tab in Render (the disk's SQLite file and the new
Postgres are both reachable from there) and run:

```
python scripts/migrate_sqlite_to_postgres.py /var/data/chordential.db "<INTERNAL_POSTGRES_URL>"
```

It creates the schema, copies every table, and prints `sqlite=N postgres=N` per table.
**Confirm every row shows `ok` and counts match** before continuing. (Run it once, on the
fresh empty Postgres.)

## Step 3 — flip to Postgres + remove the disk (the last deploy with downtime)
Edit the service config (Blueprint sync of `render.yaml`, or the dashboard):

1. Set **`CHORDENTIAL_DB`** to the Postgres URL (or use a `fromDatabase` reference).
2. **Remove the `disk:` block** and the old `/var/data` `CHORDENTIAL_DB` value.

`render.yaml` at cutover looks like:

```yaml
services:
  - type: web
    name: chordential
    # …build/start unchanged, healthCheckPath: /healthz already set…
    envVars:
      - key: CHORDENTIAL_DB
        fromDatabase:
          name: chordential-db          # the Postgres below
          property: connectionString
    # ← the disk: block is GONE

databases:
  - name: chordential-db
    plan: basic-256mb
    databaseName: chordential
    user: chordential
```

Deploy. **This one deploy still has the ~2-min blip** (last time the disk detaches).

## Step 4 — verify zero-downtime
1. Confirm the site loads and the data is all there (opportunities, signals, invoices),
   and a create→read works (e.g., add a note, see it persist).
2. Prove it: in a terminal, run a 1-second health loop **while you trigger another deploy**:
   ```
   while true; do curl -s -o /dev/null -w "%{http_code} " https://chordential.com/healthz; sleep 1; done
   ```
   It should print `200 200 200 …` continuously through the deploy — **no 502**. 🎉

From here, every push deploys with zero downtime.

---

## Notes / safety
- **Back up first:** before Step 3, keep a copy of `/var/data/chordential.db` (download it
  via the Shell) in case you need to re-run the migration.
- The migration script is **not** idempotent — run it once against the empty Postgres. To
  redo it, drop/recreate the Postgres schema first.
- Local dev + the test suite are unaffected — they stay on SQLite (no `postgresql://` URL).
- Rollback before Step 3 is trivial (nothing changed in prod yet). After Step 3, rollback
  means pointing `CHORDENTIAL_DB` back at the disk path and re-attaching the disk.
- Validation already done in the sandbox: the full app boots on Postgres, all routes 200,
  the demo seed (hundreds of rows) loads, and the migration preserves every row
  (`scripts/pg_app_smoke.py`, `scripts/pg_parity_check.py`).
