"""Snapshot watchdog (#37/F3) — catches a daily job that never ran at all.

The sanity guardrail only validates data when the tracker RUNS; the staleness check only fires on a
run that happens. A job that fails early — or never fires — is otherwise completely silent. That is
exactly what happened on 2026-08-04: the scheduled run died in the test step BEFORE scraping, and the
day's snapshot was simply lost with no notification.

This module powers a SECOND, tiny scheduled workflow that runs a couple of hours after the main job:
it reads the COMMITTED workbook, checks whether today's snapshot_date is present, and e-mails if it
is not. It does **no scraping** — read, compare, e-mail — so it cannot interfere with the main job,
cannot touch the data, and costs one file read.

Exit code is always 0: the watchdog reports, it never fails a workflow (a red X on the watchdog would
itself be noise, and it has no data to protect).
"""
from __future__ import annotations

import sys
from datetime import date as _date
from pathlib import Path

from . import alerts as alerts_mod
from . import config


def snapshot_present(path, day) -> bool:
    """True when `history` holds at least one row for `day`. A missing/unreadable workbook returns
    False — that is itself worth an e-mail."""
    import pandas as pd
    try:
        df = pd.read_excel(path, sheet_name="history", dtype={"snapshot_date": str})
    except Exception as e:
        print(f"watchdog: could not read history ({type(e).__name__}: {e})")
        return False
    if "snapshot_date" not in df.columns:
        return False
    return str(day) in {str(d)[:10] for d in df["snapshot_date"].dropna()}


def format_missing_email(day, newest: str | None):
    subject = f"Mobile Price Tracker — NO SNAPSHOT TODAY — {day}"
    body = (f"{subject}\n\nThe committed workbook has no row for {day}.\n"
            f"Newest snapshot on file: {newest or 'none'}.\n\n"
            f"The daily job did not run, failed before writing, or its commit did not land.\n"
            f"Check the GitHub Actions run history for the mobile-price-tracker workflow.\n")
    return subject, body


def newest_snapshot(path) -> str | None:
    import pandas as pd
    try:
        df = pd.read_excel(path, sheet_name="history", dtype={"snapshot_date": str})
        dates = sorted(d for d in df["snapshot_date"].dropna().unique())
        return str(dates[-1])[:10] if dates else None
    except Exception:
        return None


def run(today=None) -> int:
    today = today or _date.today()
    settings = config.load()
    path = Path(settings.output_xlsx)
    if snapshot_present(path, today.isoformat()):
        print(f"watchdog: snapshot for {today} present - OK")
        return 0
    newest = newest_snapshot(path)
    print(f"watchdog: NO snapshot for {today} (newest on file: {newest})", file=sys.stderr)
    try:
        subject, body = format_missing_email(today.isoformat(), newest)
        sent = alerts_mod.send_alert_email(settings.alerts, subject, body)
        print(f"watchdog: alert email {'sent' if sent else 'not sent'}", file=sys.stderr)
    except Exception as e:      # the watchdog must never be the thing that breaks
        print(f"watchdog: alert error ({type(e).__name__}: {e}) - continuing", file=sys.stderr)
    return 0                     # ALWAYS 0 — the watchdog reports, it never fails a workflow


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
