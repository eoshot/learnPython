"""Tesla order tracker.

Shells out to base/tesla_order_status.py to fetch the latest order data,
snapshots it to ./snapshots/, diffs against the previous snapshot, logs
every change to history.db, and pings Discord when something moves.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from notify import notify_changes, notify_error

ROOT = Path(__file__).resolve().parent
BASE_DIR = ROOT / "base"
BASE_SCRIPT = BASE_DIR / "tesla_order_status.py"
BASE_ORDERS_JSON = BASE_DIR / "tesla_orders.json"
BASE_TOKENS_JSON = BASE_DIR / "tesla_tokens.json"
SNAPSHOTS_DIR = ROOT / "snapshots"
DB_PATH = ROOT / "history.db"

DEFAULT_POLL_MINUTES = 30
HARD_MIN_INTERVAL_MINUTES = 15
SUBPROCESS_TIMEOUT_SECONDS = 90


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def snapshot_filename(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d_%H%M%S_%f.json")


def init_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            rn TEXT NOT NULL,
            field TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_history_rn ON history(rn);
        CREATE INDEX IF NOT EXISTS idx_history_ts ON history(timestamp);

        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            status TEXT NOT NULL,
            message TEXT
        );
        """
    )
    conn.commit()
    return conn


def log_run(conn: sqlite3.Connection, status: str, message: str = "") -> None:
    conn.execute(
        "INSERT INTO runs(timestamp, status, message) VALUES(?, ?, ?)",
        (iso(now_utc()), status, message),
    )
    conn.commit()


def last_run_at(conn: sqlite3.Connection) -> datetime | None:
    row = conn.execute("SELECT MAX(timestamp) FROM runs").fetchone()
    if not row or not row[0]:
        return None
    return datetime.strptime(row[0], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def rate_limited(conn: sqlite3.Connection, min_minutes: int) -> bool:
    last = last_run_at(conn)
    if last is None:
        return False
    delta_minutes = (now_utc() - last).total_seconds() / 60
    return delta_minutes < min_minutes


def load_orders_file(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


def latest_snapshot_before(now_file: Path) -> Path | None:
    snaps = sorted(p for p in SNAPSHOTS_DIR.glob("*.json") if p != now_file)
    return snaps[-1] if snaps else None


def run_base_script() -> tuple[int, str, str]:
    """Run the vendored script non-interactively. Returns (rc, stdout, stderr)."""
    proc = subprocess.run(
        [sys.executable, str(BASE_SCRIPT)],
        cwd=str(BASE_DIR),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
    )
    return proc.returncode, proc.stdout, proc.stderr


def stringify(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    return str(value)


def diff_dicts(old, new, path: str = "") -> list[tuple[str, str, str]]:
    """Recursively diff two JSON-ish structures.

    Returns a list of (field_path, old_value, new_value) tuples.
    """
    changes: list[tuple[str, str, str]] = []
    if isinstance(old, dict) and isinstance(new, dict):
        for key in old.keys() | new.keys():
            sub_path = f"{path}.{key}" if path else key
            if key not in new:
                changes.append((sub_path, stringify(old[key]), ""))
            elif key not in old:
                changes.append((sub_path, "", stringify(new[key])))
            else:
                changes.extend(diff_dicts(old[key], new[key], sub_path))
    elif isinstance(old, list) and isinstance(new, list):
        for i in range(max(len(old), len(new))):
            sub_path = f"{path}[{i}]"
            if i >= len(new):
                changes.append((sub_path, stringify(old[i]), ""))
            elif i >= len(old):
                changes.append((sub_path, "", stringify(new[i])))
            else:
                changes.extend(diff_dicts(old[i], new[i], sub_path))
    else:
        if old != new:
            changes.append((path, stringify(old), stringify(new)))
    return changes


def rn_for_path(path: str, orders: list) -> str:
    """Pick the order's referenceNumber that the diff path belongs to."""
    if path.startswith("[") and "]" in path:
        try:
            idx = int(path[1 : path.index("]")])
            return orders[idx].get("order", {}).get("referenceNumber", "unknown")
        except (ValueError, IndexError, AttributeError):
            return "unknown"
    if orders:
        return orders[0].get("order", {}).get("referenceNumber", "unknown")
    return "unknown"


def write_history(
    conn: sqlite3.Connection,
    timestamp: str,
    new_orders: list,
    changes: list[tuple[str, str, str]],
) -> None:
    rows = [
        (timestamp, rn_for_path(field, new_orders), field, old, new)
        for field, old, new in changes
    ]
    conn.executemany(
        "INSERT INTO history(timestamp, rn, field, old_value, new_value) VALUES(?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()


def main() -> int:
    load_dotenv(ROOT / ".env")
    SNAPSHOTS_DIR.mkdir(exist_ok=True)
    conn = init_db()

    poll_minutes = max(
        HARD_MIN_INTERVAL_MINUTES,
        int(os.getenv("POLL_INTERVAL_MINUTES", DEFAULT_POLL_MINUTES)),
    )
    floor = max(1, poll_minutes - 2)
    if rate_limited(conn, floor):
        log_run(conn, "rate_limited", f"skipped, floor={floor}m")
        print(f"[tracker] rate-limited (last run < {floor}m ago); exiting")
        return 0

    if not BASE_TOKENS_JSON.exists():
        msg = (
            "tesla_tokens.json missing in base/. Run "
            "`python base/tesla_order_status.py` once interactively to log in."
        )
        log_run(conn, "error", msg)
        notify_error(msg)
        print(f"[tracker] ERROR: {msg}")
        return 1

    try:
        rc, stdout, stderr = run_base_script()
    except subprocess.TimeoutExpired:
        msg = "base script timed out after 90s — Tesla API stuck or auth prompt hit"
        log_run(conn, "error", msg)
        notify_error(msg)
        print(f"[tracker] ERROR: {msg}")
        return 1
    except Exception as exc:
        msg = f"failed to launch base script: {exc!r}"
        log_run(conn, "error", msg)
        notify_error(msg)
        print(f"[tracker] ERROR: {msg}")
        return 1

    if rc != 0:
        msg = f"base script exited rc={rc}. Tail: {(stderr or stdout)[-500:]}"
        log_run(conn, "error", msg)
        notify_error("Tesla tracker broken — re-auth needed.\n\n" + msg)
        print(f"[tracker] ERROR: {msg}")
        return 1

    new_orders = load_orders_file(BASE_ORDERS_JSON)
    if not new_orders:
        msg = "base script ran but tesla_orders.json is missing/empty"
        log_run(conn, "error", msg)
        notify_error(msg)
        print(f"[tracker] ERROR: {msg}")
        return 1

    timestamp = iso(now_utc())
    snap_path = SNAPSHOTS_DIR / snapshot_filename(now_utc())
    snap_path.write_text(json.dumps(new_orders, indent=2, ensure_ascii=False))

    prev_path = latest_snapshot_before(snap_path)
    if prev_path is None:
        log_run(conn, "ok", f"first snapshot saved: {snap_path.name}")
        print(f"[tracker] first snapshot saved ({snap_path.name}); nothing to diff")
        return 0

    old_orders = load_orders_file(prev_path) or []
    changes = diff_dicts(old_orders, new_orders)

    if not changes:
        log_run(conn, "no_changes", f"snapshot {snap_path.name}")
        print(f"[tracker] no changes since {prev_path.name}")
        return 0

    write_history(conn, timestamp, new_orders, changes)
    rn = rn_for_path(changes[0][0], new_orders)
    try:
        notify_changes(rn=rn, timestamp=timestamp, changes=changes)
    except Exception as exc:
        log_run(conn, "ok", f"{len(changes)} changes, notify failed: {exc!r}")
        print(f"[tracker] {len(changes)} changes logged; Discord post failed: {exc!r}")
        return 0

    log_run(conn, "ok", f"{len(changes)} changes notified")
    print(f"[tracker] {len(changes)} changes logged and posted to Discord")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
