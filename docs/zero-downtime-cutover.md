# Zero-Downtime Deploys — Cutover Runbook

**Why:** every deploy causes a ~2-minute 502 because the SQLite database lives on a
Render **persistent disk** (single-attach) — Render must stop the old instance before
the new one can mount the disk. Moving the database to **managed Postgres** removes the
disk, which lets Render run old + new at once and switch with **no downtime**.

The code already supports both: `CHORDENTIAL_DB` as a path → SQLite (today); as a
`postgresql://…` URL → Postgres. Nothing else changes. **Follow these steps in order —
the data migration must happen before the disk is removed, or live data is lost.**

> ### 2026-08-04 — this path has now actually been run (ADR-0045)
> Until then it never had been: the dialect shim was regex-only and `psycopg` was not
> even installed, so nothing here was more than plausible. Standing up a real
> PostgreSQL 16 found **three defects, each of which would have failed *during* the
> cutover**, with the disk already being decommissioned:
>
> | # | Defect | What it would have done |
> |---|---|---|
> | 1 | `BLOB` is not a Postgres type | `media_blob` — the DB mirror of every uploaded master — could not be created. **The app would not boot.** |
> | 2 | `COLLATE NOCASE` does not exist | `/agencies`, the decision-maker list and the roster all **500** on their first query. |
> | 3 | The migration script asked every table for its `id` sequence | `media_blob` is keyed by `name`. The script **crashed mid-copy**, after several tables were already written, on your production data. |
>
> All three are fixed, and the whole path is now verified end to end on a real server:
> schema builds, all 251 routes serve, writes work (`lastrowid` via `RETURNING id`),
> the migration completes with matching counts, and an uploaded master survives the
> SQLite→Postgres round trip **byte-for-byte (SHA-256)**.
>
> **Re-verify before you run this for real**, on a scratch database:
> ```
> CHORDENTIAL_TEST_PG=postgresql://user@host:5432/postgres \
>   python -m pytest tests/test_postgres_dialect.py -q
> ```
> Those tests **skip** without that variable, and skipping is not passing — a green CI
> run with no DSN says nothing about Postgres, which is how the shim stayed untested.

---

## Step 0 — the code is already deployed (safe)
The compatibility layer (`web/db.py`) shipped with this change. The app is still running
on SQLite-on-disk exactly as before — no behavior change. ✅ Verify the live site works
normally before continuing.

## Step 1 — move the uploads to the bucket ⛔ **do not skip**

**The disk holds more than the database.** `CHORDENTIAL_UPLOAD_DIR` is `/var/data/uploads`:
every client picture cut, master, stem and built delivery ZIP. Files above the 64 MB
mirror cap have **no other copy anywhere**. Postgres does not carry them. Removing the
disk first destroys them irrecoverably.

### 1a — create the bucket and an S3 credential
Cloudflare R2 is the intended target: no egress fees, and the delivery package is all
egress.

1. Cloudflare dashboard → **R2** → **Create bucket**. Name it `chordential-media`.
   Location: pick the hint nearest your Render region.
2. **Keep the bucket private.** Do not enable public access or the `r2.dev` domain. The
   app serves media by **presigned GET** (`storage/s3.py::url`, 1-hour expiry) minted
   only after the payment/token gate has already passed — a public bucket would make
   every client master readable by anyone who can guess a key.
3. R2 → **Manage R2 API Tokens** → **Create API token** → permission **Object Read &
   Write**, scoped to *this bucket only*. Copy the **Access Key ID** and **Secret Access
   Key** — the secret is shown once.

> ⚠️ R2 issues two different things and only one of them works here. You need the
> **R2 API token**, which yields an S3-style Access Key ID + Secret Access Key. A
> general **Cloudflare API token** (the `wrangler` kind) is not an S3 credential and
> `boto3` cannot use it.

4. The endpoint is `https://<account-id>.r2.cloudflarestorage.com` — the account ID is
   in the R2 overview page's sidebar.

### 1b — set the five variables, in the Render dashboard
```
CHORDENTIAL_STORAGE     = s3
CHORDENTIAL_S3_BUCKET   = chordential-media
CHORDENTIAL_S3_ENDPOINT = https://<account-id>.r2.cloudflarestorage.com
CHORDENTIAL_S3_ACCESS_KEY = <token id>
CHORDENTIAL_S3_SECRET_KEY = <token secret>
CHORDENTIAL_S3_REGION   = auto        # R2 wants exactly this
```
Set them all, then save once — Render restarts the service on the last change.

If media playback later fails with a CORS error in the browser console, add a CORS rule
on the bucket allowing `GET` from `https://chordential.com`. Plain `<audio>`/`<video>`
playback does not need it; a fetch-based waveform read would.

> **The build must already carry `boto3`.** `render.yaml` installs the **`s3` extra** for
> exactly this reason, and it must be deployed *before* you flip the switch. Without the
> SDK, a store with valid credentials used to report `durable = True`, fail every write,
> **and** turn off the SQLite mirror — an uploaded master ended up with **zero** copies
> while the log said "object storage active — uploads are durable." That is now
> impossible: no SDK means half-configured, which falls back to the disk and says so.

### 1c — confirm the app agrees, before moving anything

First, in the Render **Shell**, confirm the SDK is actually in the image. `render.yaml`
asks for it, but the build command only comes from the blueprint if Blueprint sync is on
— otherwise it is whatever the dashboard says, and it may still be the old one:

```
python -c "import boto3, sys; print('boto3', boto3.__version__)"
```

If that fails, fix the build command in the dashboard to
`pip install '.[web,gmail,ai,stripe,postgres,s3]'` and redeploy **before** going further.

Then redeploy and read the **first line of the log**:

| Line | Meaning |
|---|---|
| `[storage] object storage active — uploads are durable.` | ✅ go on |
| `[storage] WARNING: … falling back to the LOCAL disk` | ✗ a variable is wrong or the SDK is missing — fix before continuing |
| `[storage] local disk at … — not durable` | ✗ `CHORDENTIAL_STORAGE` is not `s3` |

### 1d — copy the media, then verify it
In the Render **Shell**:
```
python scripts/migrate_uploads_to_object_store.py --dry-run   # read-only; writes nothing
python scripts/migrate_uploads_to_object_store.py
```
It reads **two** sources — the upload directory *and* the `media_blob` mirror, because
after any redeploy some keys exist only in the mirror and a directory copy would leave
them behind — writes each object, then **reads every one back and compares SHA-256**.
`put()` returning True is not evidence. It prints `moved=N skipped=N failed=N`; **it must
say `failed=0`**, and it exits non-zero otherwise. It is idempotent, so re-run it freely
after fixing anything.

### 1e — prove it with the product, not the script
1. Open a delivery portal and **play a master** — it now streams from the bucket.
2. **Download the delivery ZIP.**
3. **Upload a new version** through the console, publish it, play it back.

Only when all three work is the disk safe to remove.

> **Why this is first, not last.** It is independent of Postgres, it is the step with the
> irrecoverable failure mode, and it can take as long as it takes. The database copy
> (Step 3) is a *snapshot* — every hour between that copy and the flip is an hour of new
> leads, notes and invoices sitting only in SQLite. So do the slow, risky, independent
> work first, and copy the database last, immediately before the switch.

## Step 2 — create the Render Postgres database
Render dashboard → **New → PostgreSQL** (same region as the web service). Note its
**Internal Database URL** (`postgresql://…`). A `basic-256mb` plan is plenty to start.

## Step 3 — migrate the data (run ON Render, where both DBs are reachable)
Open the web service's **Shell** tab in Render (the disk's SQLite file and the new
Postgres are both reachable from there) and run:

```
python scripts/migrate_sqlite_to_postgres.py /var/data/chordential.db "<INTERNAL_POSTGRES_URL>"
```

It creates the schema, copies every table, and prints `sqlite=N postgres=N` per table.
**Confirm every row shows `ok` and counts match** before continuing. (Run it once, on the
fresh empty Postgres.) **Do this immediately before Step 4** — it is a snapshot, and
anything written to SQLite afterwards is not in it.

## Step 4 — flip to Postgres + remove the disk (the last deploy with downtime)

> ⛔ Do not start this until **Step 1 reported `failed=0`** and you have played a master
> and downloaded a ZIP from the bucket.

Edit the service config (Blueprint sync of `render.yaml`, or the dashboard):

1. Set **`CHORDENTIAL_DB`** to the Postgres URL (or use a `fromDatabase` reference).
2. **Remove the `disk:` block** and the old `/var/data` `CHORDENTIAL_DB` value — only
   after Step 1. Leave `CHORDENTIAL_UPLOAD_DIR` set or unset as you like: with
   `CHORDENTIAL_STORAGE=s3` it is only the local fallback root, and nothing writes there.

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

## Step 5 — verify zero-downtime
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
- **Back up first:** before Step 4, keep a copy of `/var/data/chordential.db` (download it
  via the Shell) in case you need to re-run the migration.
- The migration script is **not** idempotent — run it once against the empty Postgres. To
  redo it, drop/recreate the Postgres schema first.
- Local dev + the test suite are unaffected — they stay on SQLite (no `postgresql://` URL).
- Rollback before Step 4 is trivial (nothing changed in prod yet). After Step 4, rollback
  means pointing `CHORDENTIAL_DB` back at the disk path and re-attaching the disk.
- Validation already done in the sandbox: the full app boots on Postgres, all routes 200,
  the demo seed (hundreds of rows) loads, and the migration preserves every row
  (`scripts/pg_app_smoke.py`, `scripts/pg_parity_check.py`).
