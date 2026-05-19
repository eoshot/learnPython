# Tesla Order Tracker

A small personal tool that polls Tesla's owner API on a schedule, snapshots
the full order detail blob, diffs it against the previous run, logs every
change to a local SQLite database, and pings a Discord webhook whenever
something moves (EDD shift, VIN assigned, factory/transit status change,
MVPA, odometer reading, etc.).

Pulls richer data than tesla.com shows. No third-party services or fees.

> **Security warning**: your Tesla access token gives full account access
> (vehicle commands, account settings, the lot). Don't commit it, don't
> share the machine you run this on, and don't run this on hardware you
> don't trust. `.env`, `base/tesla_tokens.json`, `snapshots/`, and
> `history.db` are all in `.gitignore` — keep it that way.

## How it works

```
cron --> tracker.py --> base/tesla_order_status.py --> Tesla API
                |              |
                |              v
                |          base/tesla_orders.json (overwritten each run)
                v
            snapshots/<timestamp>.json  +  history.db  +  Discord embed
```

- `base/` is a vendored copy of [niklaswa/tesla-order-status][upstream]
  that handles OAuth and the two-stage order fetch. Don't edit it.
- `tracker.py` shells out to that script, snapshots the JSON, diffs
  against the previous snapshot, writes changes to `history.db`, and
  calls `notify.py`.
- `notify.py` posts a Discord embed via webhook when there are changes.
  Silent on no-change runs.

[upstream]: https://github.com/niklaswa/tesla-order-status

## Setup

Requires **Python 3.11 or newer**.

```bash
git clone <this-repo> tesla-tracker
cd tesla-tracker
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env and paste your Discord webhook URL
```

### First-run Tesla login (interactive, one-time)

```bash
cd base
python tesla_order_status.py
```

This opens your browser to `auth.tesla.com`. Log in (and complete 2FA if
enabled). After login you'll be redirected to a URL that looks like
`https://auth.tesla.com/void/callback?code=...&state=...` and the page
will show "Page Not Found" — that's expected. **Copy the entire URL from
your browser's address bar and paste it back into the terminal prompt.**

The script will then:
1. Exchange the code for tokens, ask whether to save them. Answer `y`.
2. Fetch your orders, ask whether to save them. Answer `y`.

After this, `base/tesla_tokens.json` and `base/tesla_orders.json` exist
and `tracker.py` can run unattended.

To re-authenticate later (e.g. token revoked, password changed):
delete `base/tesla_tokens.json` and re-run the command above.

### Smoke-test the wrapper

```bash
cd ..
python tracker.py
```

First run saves a snapshot and nothing else (no previous snapshot to
diff against). Run it again a few seconds later — it should rate-limit
itself and exit. Wait 15+ minutes, then run again to see a real diff
(if anything changed) or "no changes since…".

## Running on a schedule

### Linux / Raspberry Pi (cron)

```bash
crontab -e
```

Add this line — every 30 minutes — adjusting paths:

```cron
*/30 * * * * cd /home/pi/tesla-tracker && /home/pi/tesla-tracker/.venv/bin/python tracker.py >> /home/pi/tesla-tracker/tracker.log 2>&1
```

If you don't use a venv, swap in `/usr/bin/python3`.

### macOS (launchd)

Create `~/Library/LaunchAgents/com.you.tesla-tracker.plist` (replace
`USERNAME` with your macOS username and adjust paths):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.you.tesla-tracker</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/USERNAME/tesla-tracker/.venv/bin/python</string>
        <string>/Users/USERNAME/tesla-tracker/tracker.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/USERNAME/tesla-tracker</string>
    <key>StartInterval</key>
    <integer>1800</integer>
    <key>StandardOutPath</key>
    <string>/Users/USERNAME/tesla-tracker/tracker.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/USERNAME/tesla-tracker/tracker.log</string>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
```

Load it:

```bash
launchctl load ~/Library/LaunchAgents/com.you.tesla-tracker.plist
```

`StartInterval` is in seconds (`1800` = 30 min). Note: launchd only fires
when the Mac is awake — if you close the lid, no polls. Use a Pi or VM
for true always-on tracking.

### Cheap always-on hosting options

- **Raspberry Pi** (any model, even a Pi Zero 2 W) — install Raspberry
  Pi OS Lite, follow the Linux cron section above. Total cost ~$15 plus
  power.
- **Oracle Cloud Free Tier** — Oracle gives away two AMD VM.Standard.E2.1.Micro
  instances forever for free (no credit card expiration). Spin up an
  Ubuntu instance, follow the Linux cron section. The catch: Oracle
  occasionally reclaims idle free-tier instances, so install something
  small that exercises the box (like the tracker itself) to keep it active.
- Any old PC, NAS, home server, or always-on desktop also works fine.

## Querying history

Everything that ever changed lives in `history.db`. Examples:

```bash
# All EDD-related changes ever, newest first
sqlite3 history.db "SELECT timestamp, old_value, new_value FROM history WHERE field LIKE '%deliveryWindow%' OR field LIKE '%etaToDelivery%' ORDER BY timestamp DESC;"

# Full history for one order
sqlite3 history.db "SELECT timestamp, field, old_value, new_value FROM history WHERE rn = 'RNXXXXXXXX' ORDER BY timestamp;"

# Run audit log
sqlite3 history.db "SELECT timestamp, status, message FROM runs ORDER BY timestamp DESC LIMIT 20;"
```

## Files

| Path | Purpose | Tracked in git? |
|---|---|---|
| `tracker.py` | Main wrapper script | yes |
| `notify.py` | Discord webhook sender | yes |
| `base/` | Vendored upstream auth + fetch | yes |
| `requirements.txt` | Pinned third-party deps | yes |
| `.env` | Your Discord webhook + poll interval | **no** |
| `base/tesla_tokens.json` | Your OAuth tokens (full account access) | **no** |
| `base/tesla_orders.json` | Latest order fetch (rewritten each run) | **no** |
| `snapshots/*.json` | Per-run timestamped order snapshots | **no** |
| `history.db` | SQLite log of every field change + run audit | **no** |
| `tracker.log` | Stdout/stderr from scheduled runs | **no** |
