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
class SanityIssue:
    carrier: str
    kind: str          # "count_low" | "count_high" | "price_out_of_range"
    detail: str


def _band_issues(counts: dict, bands: dict, lo_key: str, hi_key: str, unit: str) -> list[SanityIssue]:
    """Count-band check shared by the mobile and convergent domains (#37)."""
    out: list[SanityIssue] = []
    for carrier, count in (counts or {}).items():
        band = (bands or {}).get(carrier)
        if not band:
            continue
        lo, hi = band.get(lo_key), band.get(hi_key)
        if lo is not None and count < lo:
            out.append(SanityIssue(carrier, "count_low", f"{count} {unit} (< min {lo})"))
        elif hi is not None and count > hi:
            out.append(SanityIssue(carrier, "count_high", f"{count} {unit} (> max {hi})"))
    return out


def check_sanity(per_carrier: dict, plans, cfg: dict,
                 per_carrier_convergent: dict | None = None, convergent=None) -> list[SanityIssue]:
    """Pure: flag a degraded scrape (GOVERNANCE §6). A carrier whose valid-row count falls outside its
    band, or any row priced outside [price_min_brl, price_max_brl], is an issue. Only carriers actually
    scraped (present in the count dicts) are checked, so a partial run is judged on what it attempted.
    Empty list = all sane. Extended in #37 to cover the CONVERGENT domain as well as mobile.

    An issue BLOCKS the commit (main.py exits non-zero) — unlike a price alert, which is purely
    informational and must never block."""
    issues = _band_issues(per_carrier, cfg.get("carriers", {}), "min_plans", "max_plans", "plans")
    issues += _band_issues(per_carrier_convergent, cfg.get("convergent", {}),
                           "min_offers", "max_offers", "combo offers")

    pmin, pmax = cfg.get("price_min_brl"), cfg.get("price_max_brl")
    if pmin is not None or pmax is not None:
        for row in list(plans or []) + list(convergent or []):
            price = _num(getattr(row, "price_brl", None))
            if price is None:
                continue
            if (pmin is not None and price < pmin) or (pmax is not None and price > pmax):
                name = getattr(row, "plan_name", None) or getattr(row, "offer_name", "?")
                rid = getattr(row, "plan_id", None) or getattr(row, "offer_id", "?")
                issues.append(SanityIssue(getattr(row, "carrier", "?"), "price_out_of_range",
                                          f"{name} ({rid}): R$ {price} outside [{pmin}, {pmax}]"))
    return issues


def check_staleness(path, max_age_days: int, today=None) -> str | None:
    """The gap the sanity guard does NOT cover (#37/F2): sanity only validates data when the job RUNS,
    so a job that never runs is silent. Compare the newest `history` snapshot_date with today; return
    a human message when it is older than `max_age_days`, else None. Never raises."""
    from datetime import date as _date
    import pandas as pd
    today = today or _date.today()
    try:
        df = pd.read_excel(path, sheet_name="history", dtype={"snapshot_date": str})
        dates = sorted(d for d in df["snapshot_date"].dropna().unique())
    except Exception as e:
        print(f"alerts: staleness check skipped ({type(e).__name__})")
        return None
    if not dates:
        return None
    try:
        newest = _date.fromisoformat(str(dates[-1])[:10])
    except ValueError:
        return None
    age = (today - newest).days
    if age > max_age_days:
        missing = [str(d) for d in _missing_dates(dates, today)]
        return (f"newest snapshot is {newest} ({age} days old; limit {max_age_days}). "
                f"Missing date(s): {', '.join(missing) if missing else 'none'}")
    return None


def _missing_dates(dates, today):
    """Calendar dates between the first snapshot and today with no row at all."""
    from datetime import date as _date, timedelta
    have = {str(d)[:10] for d in dates}
    try:
        cur = _date.fromisoformat(str(dates[0])[:10])
    except ValueError:
        return []
    out = []
    while cur <= today:
        if cur.isoformat() not in have:
            out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out


def format_staleness_email(message: str, date):
    subject = f"Mobile Price Tracker — STALE DATA — {date}"
    return subject, (f"{subject}\n\nThe tracker's history has not advanced as expected:\n\n"
                     f"  {message}\n\nThe daily job may have failed or never fired — check the "
                     f"GitHub Actions run history.\n")


def format_sanity_email(issues: list[SanityIssue], date):
    """Pure: (subject, body) for a SANITY-FAIL alert — the run is being blocked, you should know now."""
    subject = f"Mobile Price Tracker — SANITY CHECK FAILED — {date}"
    lines = [f"[{i.carrier.upper()}] {i.kind}: {i.detail}" for i in issues]
    body = (subject + "\n\nThe daily snapshot was NOT committed (data looked degraded). Issues:\n\n"
            + "\n".join(lines) + "\n")
    return subject, body


@dataclass
class Alert:
    carrier: str
    category: str
    plan_name: str
    plan_id: str
    old_price: float
    new_price: float
    pct: float
    domain: str = "mobile"        # "mobile" | "convergent" — groups the digest's sections (#37)
    rekeyed_from: str | None = None   # set when the row was paired via the name fallback (#37)

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


def _key(p, id_attr="plan_id"):
    # `category` is part of the identity (#37/C): a carrier's native id is only unique WITHIN a
    # category page. Claro's controle page reuses the flex slug, so `claro:plano-flex-20gb` is both a
    # R$44,90 Controle plan and a R$59,90 Flex plan in the same snapshot — keyed without `category`
    # they collapse into one and the R$15 difference reads as a 25% price cut. Convergent offers have
    # no `category` attribute; getattr returns None consistently on both sides, so they are unaffected.
    return (getattr(p, "carrier", None), getattr(p, "state", None),
            getattr(p, "category", None), getattr(p, id_attr, None))


def _name_key(p, name_attr="plan_name"):
    return (getattr(p, "carrier", None), getattr(p, "state", None),
            getattr(p, "category", None), getattr(p, name_attr, None))


def compute_price_moves(prev_rows, today_rows, threshold_pct: float, *,
                        id_attr: str = "plan_id", name_attr: str = "plan_name",
                        domain: str = "mobile") -> list[Alert]:
    """Pure: rows present in BOTH snapshots whose price moved >= threshold_pct (either direction).

    Matched on (carrier, state, <id_attr>). The field names are parameters so the SAME rule serves
    both domains (#37): mobile rows carry plan_id/plan_name, convergent rows offer_id/offer_name.

    ID-ROTATION FALLBACK (#29): carriers republish rows under fresh native ids (TIM rotated every
    Drupal nid on 2026-07-06 and again on 2026-08-04 while cutting Controle prices), which makes a
    real move look like remove+add and silently skips the alert. Id-unmatched rows are therefore
    re-paired by (carrier, state, category, name).

    ⚠️ TIGHTENED in #37 after the #35 audit: the name must be unique in the FULL snapshot on BOTH
    sides, not merely among the unmatched rows. The old scope let an ordinary lineup change — one
    tier of a same-named family dropped, another added — join two genuinely different plans and
    report a price the named plan never had (demonstrated: "Vivo Lite R$35 → R$75 +114 %"). 176 such
    non-unique name groups exist in the real history. No match is better than a wrong match.
    Genuinely new/removed rows are still never flagged. Sorted by |pct| desc."""
    def _count_names(rows):
        counts: dict = {}
        for r in rows:
            counts[_name_key(r, name_attr)] = counts.get(_name_key(r, name_attr), 0) + 1
        return counts

    prev = {}
    for p in prev_rows:
        k = _key(p, id_attr)
        if k[-1] and _num(getattr(p, "price_brl", None)) is not None:   # k[-1] is the id
            prev[k] = p
    # name multiplicity across the WHOLE snapshot (the #37 tightening), both sides
    prev_names, today_names = _count_names(prev_rows), _count_names(today_rows)

    today_ids = {_key(p, id_attr) for p in today_rows}
    leftover_by_name: dict = {}
    for k, p in prev.items():
        if k not in today_ids:
            leftover_by_name.setdefault(_name_key(p, name_attr), []).append(p)

    out: list[Alert] = []
    for p in today_rows:
        old, rekeyed = prev.get(_key(p, id_attr)), None
        if old is None:                                    # id rotated? try the UNAMBIGUOUS name match
            nk = _name_key(p, name_attr)
            cands = leftover_by_name.get(nk, [])
            if (len(cands) == 1 and prev_names.get(nk, 0) == 1 and today_names.get(nk, 0) == 1):
                old = cands[0]
                rekeyed = getattr(old, id_attr, None)
        if old is None:
            continue
        op, np_ = _num(old.price_brl), _num(p.price_brl)
        if op is None or np_ is None or op == 0:
            continue
        pct = (np_ - op) / op * 100.0
        if abs(pct) >= threshold_pct:
            out.append(Alert(p.carrier, getattr(p, "category", domain),
                             getattr(p, name_attr, "?"), getattr(p, id_attr, "?"),
                             op, np_, pct, domain=domain, rekeyed_from=rekeyed))
    out.sort(key=lambda a: abs(a.pct), reverse=True)
    return out


def compute_price_alerts(prev_plans, today_plans, threshold_pct: float) -> list[Alert]:
    """MOBILE price moves (plan_id / plan_name). Thin wrapper over `compute_price_moves`."""
    return compute_price_moves(prev_plans, today_plans, threshold_pct,
                               id_attr="plan_id", name_attr="plan_name", domain="mobile")


def compute_convergent_alerts(prev_offers, today_offers, threshold_pct: float) -> list[Alert]:
    """CONVERGENT (combo) price moves — the same >=3 % rule over `convergent_history` rows, matched on
    the carrier-native `offer_id` (#37). Before this the combo domain was entirely unmonitored: a Vivo
    Total combo going R$160 → R$200 e-mailed nothing (#35 audit)."""
    return compute_price_moves(prev_offers, today_offers, threshold_pct,
                               id_attr="offer_id", name_attr="offer_name", domain="convergent")


def format_alert_email(alerts: list[Alert], date, threshold_pct: float = 3.0):
    """Pure: (subject, body) for the digest. One body line per alert, already sorted by |pct| desc."""
    subject = f"Mobile Price Tracker — {len(alerts)} price change(s) ≥{threshold_pct:g}% — {date}"

    def _line(a):
        s = (f"[{a.carrier.upper()}] {a.plan_name} ({a.category}): "
             f"R$ {a.old_price:.2f} → R$ {a.new_price:.2f}  ({a.direction} {abs(a.pct):.1f}%)")
        if a.rekeyed_from:                    # make a fallback pairing visible to the reader (#37)
            s += f"   [re-keyed {a.rekeyed_from} → {a.plan_id}]"
        return s

    # ONE digest, two clearly labelled sections (#37) — a section is omitted when it has no moves.
    body = [subject, ""]
    for domain, title in (("mobile", "MOBILE PLANS"), ("convergent", "CONVERGENT (COMBO) OFFERS")):
        rows = [a for a in alerts if a.domain == domain]
        if not rows:
            continue
        body += [f"{title} ({len(rows)}):", *[f"  {_line(a)}" for a in rows], ""]
    return subject, "\n".join(body)


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


def _two_latest(path, sheet: str):
    """(prev_rows, today_rows, latest_date) for a sheet's two most recent snapshot_dates, or
    ([], [], date_or_None). Never raises — a missing/unreadable sheet is logged and skipped."""
    import pandas as pd
    try:
        df = pd.read_excel(path, sheet_name=sheet, dtype={"snapshot_date": str})
    except Exception as e:
        print(f"alerts: could not read {sheet} ({type(e).__name__}) - skipping")
        return [], [], None
    if "snapshot_date" not in df.columns:
        return [], [], None
    dates = sorted(d for d in df["snapshot_date"].dropna().unique())
    if len(dates) < 2:
        return [], [], (dates[-1] if dates else None)
    return (list(df[df.snapshot_date == dates[-2]].itertuples(index=False)),
            list(df[df.snapshot_date == dates[-1]].itertuples(index=False)),
            dates[-1])


def alerts_from_workbook(path, threshold_pct: float):
    """Diff the two latest snapshot_dates of BOTH domains → (list[Alert], latest_date) (#37).

    Until now this read only `history`, so the whole convergent domain was unmonitored. It now also
    diffs `convergent_history` on the carrier-native `offer_id`, and both sets go into ONE digest
    (`format_alert_email` renders them as separate sections). A workbook with no convergent sheet
    (or fewer than 2 convergent snapshots) simply contributes nothing — never an error."""
    mob_prev, mob_today, mob_date = _two_latest(path, "history")
    alerts = compute_price_alerts(mob_prev, mob_today, threshold_pct) if mob_today else []

    conv_prev, conv_today, conv_date = _two_latest(path, "convergent_history")
    # ⚠️ Only diff the combos when they were actually collected THIS run. The convergent pass is fully
    # guarded and legitimately yields nothing (one carrier blocked, a page restructured), and
    # `_merge_convergent` then adds no new snapshot_date — it preserves the old rows by design. Diffing
    # the sheet's own two latest dates regardless would re-send yesterday's already-reported combo
    # moves, stamped with today's date, EVERY day until a fresh convergent snapshot lands. A digest
    # that repeats itself is a digest people stop reading. (#37, found by adversarial review.)
    if conv_today and conv_date == mob_date:
        alerts = alerts + compute_convergent_alerts(conv_prev, conv_today, threshold_pct)
    elif conv_today and conv_date:
        print(f"alerts: convergent snapshot is {conv_date}, mobile is {mob_date} - "
              f"not re-reporting stale combo moves")

    alerts.sort(key=lambda a: (a.domain != "mobile", -abs(a.pct)))   # mobile first, then |pct| desc
    return alerts, (mob_date or conv_date)
