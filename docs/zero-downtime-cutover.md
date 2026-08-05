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
egress. Click by click, from a browser (nothing here can be done from the Render shell).

> Labels move — Cloudflare reorganises this dashboard. The landmarks below are what to
> look for; if a button is worded differently, the shape of the flow is still the same.

**Create the bucket**

1. Sign in at **dash.cloudflare.com**.
2. Left sidebar → **R2** (sometimes shown as *R2 Object Storage*).
3. **First time only:** R2 asks you to add a payment method before it will enable, even
   on the free tier. This is expected; you will not be charged at our volume.
4. **Create bucket**.
5. Name it exactly `chordential-media`. Location: **Automatic**, or the hint nearest your
   Render region.
6. **Create bucket**. Leave every other setting alone.

**Keep it private** — there is nothing to switch on. Do **not** open Settings → Public
access, and do **not** enable the `r2.dev` subdomain. The app serves media by presigned
GET (`storage/s3.py::url`, 1-hour expiry) minted only after the payment/token gate has
passed. A public bucket would make every client master readable by anyone who can guess
a filename.

**Create the S3 credential**

7. Back on the **R2** page (not inside the bucket), find **Manage R2 API Tokens** — it
   sits in the right-hand sidebar or as an *API* link near the top right.
8. **Create API token**.
9. **Token name**: `chordential-render` (anything; it is only a label for you).
10. **Permissions**: choose **Object Read & Write**. Not *Admin Read & Write* — the app
    only ever puts, gets, heads and deletes objects, and a narrower token is a smaller
    blast radius if Render is ever compromised.
11. **Specify bucket(s)** → *Apply to specific buckets* → tick `chordential-media`.
    Leaving it account-wide would let this one credential reach every future bucket.
12. **TTL**: leave as-is (no expiry). An expiring token means client media silently stops
    loading on a date nobody has written down.
13. Skip client IP filtering — Render's egress IPs are not stable.
14. **Create API Token**.

**The result page is shown once.** Copy all three before leaving it:

| The page shows | Goes into |
|---|---|
| **Access Key ID** | `CHORDENTIAL_S3_ACCESS_KEY` |
| **Secret Access Key** | `CHORDENTIAL_S3_SECRET_KEY` |
| **Use jurisdiction-specific endpoints for S3 clients** → the `https://…r2.cloudflarestorage.com` URL | `CHORDENTIAL_S3_ENDPOINT` |

> ⚠️ **Two different credentials, one of which does not work here.** This flow — R2 →
> Manage R2 API Tokens — issues an **S3** credential: an Access Key ID and a Secret
> Access Key. A general **Cloudflare API token** (My Profile → API Tokens, the kind
> `wrangler` uses) is a single opaque string, is *not* an S3 credential, and `boto3`
> cannot use it. If what you copied is one long token and no key/secret pair, you are in
> the wrong place.

If you lose the secret, you cannot recover it — delete that token and create another.
Nothing else needs redoing.

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

**Observed in the field, 2026-08-05:** it *did* fail. `render.yaml` had the `s3` extra
and the change had deployed, yet `boto3` was still missing — Render builds from the
service's **stored** settings and only re-reads `render.yaml` on an explicit Blueprint
sync, so the dashboard's copy wins. Editing the blueprint is not enough.

Fix it where Render actually reads it: **service → Settings → Build & Deploy → Build
Command** → `pip install '.[web,gmail,ai,stripe,postgres,s3]'` → Save → **Manual Deploy
→ Deploy latest commit**. Then re-run the check before going further.

What this looked like when it was wrong — and why it was safe:

```
boto3     : MISSING
requested : s3          <- the env vars were right
active    : local       <- it fell back to the disk
durable   : False
VERDICT   : NOT READY - do not migrate yet
```

`requested: s3` with `active: local` is the seam refusing to pretend. Uploads kept
landing on the disk **with the SQLite mirror on**, so nothing was lost. Before the
SDK check existed this same state reported `active: s3, durable: True` and dropped
every upload into nowhere.

Then redeploy and read the **first line of the log**:

| Line | Meaning |
|---|---|
| `[storage] object storage active — uploads are durable.` | ✅ go on |
| `[storage] WARNING: … falling back to the LOCAL disk` | ✗ a variable is wrong or the SDK is missing — fix before continuing |
| `[storage] local disk at … — not durable` | ✗ `CHORDENTIAL_STORAGE` is not `s3` |

### 1c-bis — or skip the shell entirely: **/settings/storage**

The console has a page for all of this — the operator should not need a terminal at the
moment a terminal is least likely to cooperate. Open **/settings/storage** and it shows
which store is live, how many files are waiting, how many exist only in the database
mirror, and gives three buttons: *test the bucket*, *dry run*, *copy for real* — with
per-file results and the SHA of each object copied.

It calls the same functions as the script (`chordential_oia.storage.migrate`), so the
button and the command cannot drift; a test asserts the script still imports them rather
than carrying its own copy. The copy button is disabled, **and the call refuses
server-side**, while the active store is the local disk.

Everything below still works from the shell if you prefer it.

### 1d — prove the bucket actually works, before touching real media

`durable: True` means the credentials and the SDK are present. It does **not** mean a
byte has ever reached the bucket — nothing in that check makes a network call. And a
`--dry-run` will not catch a bad credential either: a failed `get()` returns None, which
looks exactly like "not uploaded yet".

So round-trip one throwaway object first:

```
python -c "
import os
from chordential_oia.storage import get_object_store
s = get_object_store(os.environ.get('CHORDENTIAL_UPLOAD_DIR',''))
k, body = '_probe-delete-me.txt', b'chordential round trip'
ok_put = s.put(k, body, 'text/plain')
back   = s.get(k)
ok_del = s.delete(k)
print('put       :', ok_put)
print('read back :', back == body)
print('cleaned up:', ok_del)
print('VERDICT   :', 'BUCKET WORKS' if (back == body and ok_del) else 'BUCKET NOT WORKING - stop')
"
```

Anything other than `BUCKET WORKS` means the key, secret, endpoint or bucket name is
wrong — fix it before going near the media. The probe deletes itself.

### 1e — copy the media, then verify it
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

### 1f — prove it with the product, not the script
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

> ⛔ Do not start this until **Step 1e reported `failed=0`** and you have played a master
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
