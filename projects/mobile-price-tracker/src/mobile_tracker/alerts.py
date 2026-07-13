"""Daily price-change email alert.

After each live scrape, compare today's snapshot to the previous one and email a digest of every plan
whose headline price moved >= the threshold (default 3%, up OR down). Matching is by
(carrier, state, plan_id) — the same identity the `changes` sheet uses — so the alert and the sheet
agree, with an id-ROTATION fallback by plan name (#29, mirrored in `_compute_changes`): see
`compute_price_alerts`. Genuinely new/removed plans are NOT price-move alerts.

SECURITY: the SMTP password is read ONLY from the EMAIL_APP_PASSWORD environment variable (a GitHub
Actions Secret). It is never hardcoded, printed, logged, or committed. Addresses + threshold live in
config (non-secret).

ROBUSTNESS: alerts must NEVER fail the job or block the data commit. Missing password → skip; any SMTP
error → caught and logged. Collection > notification.
"""
from __future__ import annotations

import os
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage


@dataclass
class Alert:
    carrier: str
    category: str
    plan_name: str
    plan_id: str
    old_price: float
    new_price: float
    pct: float

    @property
    def direction(self) -> str:
        return "▲" if self.pct >= 0 else "▼"


def _num(x) -> float | None:
    """A finite float, else None (filters None / NaN / non-numeric)."""
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return None if f != f else f          # f != f is True only for NaN


def _key(p):
    return (getattr(p, "carrier", None), getattr(p, "state", None), getattr(p, "plan_id", None))


def _name_key(p):
    return (getattr(p, "carrier", None), getattr(p, "state", None),
            getattr(p, "category", None), getattr(p, "plan_name", None))


def compute_price_alerts(prev_plans, today_plans, threshold_pct: float) -> list[Alert]:
    """Pure: plans present in BOTH snapshots whose price moved >= threshold_pct (either direction),
    matched by (carrier, state, plan_id) — with an id-ROTATION fallback (#29): carriers republish
    plans under fresh native ids (TIM rotated every Drupal nid on 2026-07-06 while cutting Controle
    −15%), which made real moves look like remove+add and silently skipped the alert. Id-unmatched
    plans are therefore re-paired by (carrier, state, category, plan_name) — names are stable across
    rotations — and ONLY when that name is unique on both unmatched sides (ambiguity → no pairing, no
    false alert). Genuinely new/removed plans are still not flagged. Sorted by |pct| desc."""
    prev = {}
    for p in prev_plans:
        k = _key(p)
        if k[2] and _num(getattr(p, "price_brl", None)) is not None:
            prev[k] = p
    # rotation fallback index (#29): yesterday's plans whose id vanished today, keyed by name
    today_ids = {_key(p) for p in today_plans}
    leftover_by_name: dict = {}
    for k, p in prev.items():
        if k not in today_ids:
            leftover_by_name.setdefault(_name_key(p), []).append(p)
    # today-side uniqueness guard: two same-name id-unmatched plans must not both claim one leftover
    unmatched_today_names: dict = {}
    for p in today_plans:
        if _key(p) not in prev:
            nk = _name_key(p)
            unmatched_today_names[nk] = unmatched_today_names.get(nk, 0) + 1

    out: list[Alert] = []
    for p in today_plans:
        old = prev.get(_key(p))
        if old is None:                                    # id rotated? try the unambiguous name match
            cands = leftover_by_name.get(_name_key(p), [])
            if len(cands) == 1 and unmatched_today_names.get(_name_key(p)) == 1:
                old = cands[0]
        if old is None:
            continue
        op, np_ = _num(old.price_brl), _num(p.price_brl)
        if op is None or np_ is None or op == 0:
            continue
        pct = (np_ - op) / op * 100.0
        if abs(pct) >= threshold_pct:
            out.append(Alert(p.carrier, p.category, p.plan_name, p.plan_id, op, np_, pct))
    out.sort(key=lambda a: abs(a.pct), reverse=True)
    return out


def format_alert_email(alerts: list[Alert], date, threshold_pct: float = 3.0):
    """Pure: (subject, body) for the digest. One body line per alert, already sorted by |pct| desc."""
    subject = f"Mobile Price Tracker — {len(alerts)} price change(s) ≥{threshold_pct:g}% — {date}"
    lines = [f"[{a.carrier.upper()}] {a.plan_name} ({a.category}): "
             f"R$ {a.old_price:.2f} → R$ {a.new_price:.2f}  ({a.direction} {abs(a.pct):.1f}%)"
             for a in alerts]
    body = subject + "\n\n" + "\n".join(lines) + "\n"
    return subject, body


def send_alert_email(cfg: dict, subject: str, body: str) -> bool:
    """Live send over STARTTLS using the env password. Returns True if sent.
    Never raises: missing password → skip (False); any SMTP error → logged + False."""
    password = (os.environ.get("EMAIL_APP_PASSWORD") or "").strip()
    if not password:
        print("alerts: no password configured (EMAIL_APP_PASSWORD) - skipping send")
        return False
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = cfg["from_email"]
        msg["To"] = cfg["to_email"]
        msg.set_content(body)
        with smtplib.SMTP(cfg["smtp_host"], int(cfg["smtp_port"]), timeout=30) as smtp:
            smtp.starttls()
            smtp.login(cfg["from_email"], password)       # password used here only; never logged
            smtp.send_message(msg)
        return True
    except Exception as e:                                  # noqa: BLE001 - must not break the job
        print(f"alerts: email send failed ({type(e).__name__}: {e}) - continuing")
        return False


def alerts_from_workbook(path, threshold_pct: float):
    """Read the workbook's history, diff the two latest snapshot_dates → (list[Alert], latest_date).
    Returns ([], date_or_None) when there are fewer than 2 snapshots."""
    import pandas as pd
    try:
        hist = pd.read_excel(path, sheet_name="history", dtype={"snapshot_date": str})
    except Exception as e:
        print(f"alerts: could not read history ({type(e).__name__}) - skipping")
        return [], None
    dates = sorted(d for d in hist["snapshot_date"].dropna().unique())
    if len(dates) < 2:
        return [], (dates[-1] if dates else None)
    prev = list(hist[hist.snapshot_date == dates[-2]].itertuples(index=False))
    today = list(hist[hist.snapshot_date == dates[-1]].itertuples(index=False))
    return compute_price_alerts(prev, today, threshold_pct), dates[-1]
