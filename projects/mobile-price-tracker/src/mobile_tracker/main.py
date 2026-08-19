"""Mobile Price Tracker entrypoint / orchestrator.

Usage:
    python -m mobile_tracker.main --demo      # offline: uses adapters' demo_plans, no network
    python -m mobile_tracker.main             # live: calls adapters' fetch() (Code implements)
    python -m mobile_tracker.main --only claro # restrict to one carrier (live or demo)

Behavior:
    - Loads config/sources.yaml, iterates active (carrier, category, state) targets.
    - Collects Plans, stamps the snapshot time, validates, writes the workbook.
    - Exits non-zero if a carrier yields zero rows (so CI/cron can alert) — never let an
      empty scrape silently wipe history (GOVERNANCE §6).
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime

from . import alerts as alerts_mod
from . import config
from .adapters import ADAPTERS
from .excel_writer import write_workbook
from .models import Plan


def project_now(settings) -> datetime:
    """`datetime.now()` in the PROJECT's timezone (config `project.timezone`), not the runner's.

    A snapshot_date must be the SÃO PAULO calendar day — these are Brazilian prices. CI runs on a UTC
    machine, and the daily cron (21:00 UTC == 18:00 BRT) happens to land on the same date in both
    zones, which hid this for 44 snapshots. A manual run after 21:00 BRT is past midnight UTC, and
    2026-08-05's evening scrape was filed as `2026-08-06` — tomorrow's date, for prices that no
    longer existed by then.

    Returned NAIVE (tzinfo stripped) so `snapshot_ts` keeps the exact format every stored row uses;
    the value is the local wall clock, which is what the column has always meant. An unknown/missing
    tz name falls back to the old behaviour rather than failing the run."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(settings.timezone)).replace(tzinfo=None)
    except Exception as e:      # bad tz name, missing tzdata — never let a clock detail stop a scrape
        print(f"config: timezone '{getattr(settings, 'timezone', '?')}' unusable "
              f"({type(e).__name__}) - falling back to the local clock", file=sys.stderr)
        return datetime.now()


def snapshot_gaps(path, day: str, carriers) -> set[str]:
    """Which of `carriers` have NO rows for `day` in the stored history (#40).

    Used by --only-if-incomplete so the catch-up run can tell "today is already complete" (do
    nothing — never scrape a source twice in a day) from "a carrier is missing" (worth one retry).
    A missing/unreadable workbook means every carrier is missing, which is the safe answer."""
    import pandas as pd
    try:
        df = pd.read_excel(path, sheet_name="history", dtype={"snapshot_date": str})
    except Exception:
        return set(carriers)
    today = df[df["snapshot_date"].astype(str).str[:10] == str(day)]
    have = set(today["carrier"].dropna().astype(str)) if len(today) else set()
    return {c for c in carriers if c not in have}


def stored_plans_for(path, day: str) -> list:
    """Today's ALREADY-STORED rows, rebuilt as Plan objects (#41).

    ⚠️ Load-bearing for the catch-up pass. `_merge_history` is idempotent per snapshot_date: writing
    a date REPLACES every row that date already had. So a supplementary pass that scraped only the
    missing carrier would DELETE the carriers the earlier pass collected — turning the rescue into a
    second data loss. (Caught by test, not by review.) The catch-up therefore re-submits today's
    existing rows alongside the new ones. This is not carrying data forward from another day: these
    rows were collected today, for today."""
    import pandas as pd
    from .models import COLUMNS
    try:
        df = pd.read_excel(path, sheet_name="history", dtype={"snapshot_date": str, "snapshot_ts": str})
    except Exception:
        return []
    today = df[df["snapshot_date"].astype(str).str[:10] == str(day)]
    out = []
    for r in today.itertuples(index=False):
        kw = {c: getattr(r, c) for c in COLUMNS
              if c not in ("snapshot_date", "snapshot_ts") and pd.notna(getattr(r, c, None))}
        p = Plan(**kw)
        p.snapshot_date, p.snapshot_ts = str(r.snapshot_date), str(r.snapshot_ts)
        out.append(p)
    return out


def run(demo: bool = False, only: str | None = None, only_if_incomplete: bool = False) -> int:
    settings = config.load()
    run_ts = project_now(settings)
    targets = [t for t in settings.targets() if (only is None or t.carrier == only)]

    # CATCH-UP MODE (#40). A second scheduled pass exists purely to rescue a day that the main run
    # left incomplete — e.g. 2026-08-18, when TIM 403'd the runner. It scrapes ONLY when something is
    # actually missing, so a healthy day costs zero extra requests and the one-pass-a-day politeness
    # rule still holds for every source that already answered.
    if only_if_incomplete and not demo:
        wanted = {t.carrier for t in targets}
        missing = snapshot_gaps(settings.output_xlsx, run_ts.date().isoformat(), wanted)
        if not missing:
            print(f"catch-up: {run_ts.date().isoformat()} already has all carriers "
                  f"({', '.join(sorted(wanted))}) - nothing to do, not scraping.")
            return 0
        print(f"catch-up: {run_ts.date().isoformat()} is missing {sorted(missing)} - retrying those.")
        targets = [t for t in targets if t.carrier in missing]

    # STALENESS CHECK (#37/F2) — the gap the sanity guardrail cannot cover: sanity only validates data
    # when the job RUNS, so a job that fails or never fires is completely silent. (On 2026-08-04 the
    # scheduled run died in the test step BEFORE scraping and that day's snapshot was lost with no
    # notification.) The first run that does fire therefore reports how stale the history had become
    # and which dates are missing. Informational only — fully guarded, never blocks.
    if not demo:
        try:
            msg = alerts_mod.check_staleness(settings.output_xlsx,
                                             int(settings.sanity.get("max_snapshot_age_days", 2)))
            if msg:
                print(f"STALE DATA: {msg}", file=sys.stderr)
                subj, body = alerts_mod.format_staleness_email(msg, run_ts.date().isoformat())
                sent = alerts_mod.send_alert_email(settings.alerts, subj, body)
                print(f"alerts: stale-data email {'sent' if sent else 'not sent'}", file=sys.stderr)
        except Exception as e:
            print(f"alerts: staleness check error ({type(e).__name__}: {e}) - continuing", file=sys.stderr)

    plans: list[Plan] = []
    per_carrier: dict[str, int] = {}
    errors: list[str] = []
    # Per carrier: how many targets we attempted, and how many of those FAILED to fetch at all.
    # This is what separates "the carrier refused us" from "the carrier answered with junk" (#40).
    attempted: dict[str, int] = {}
    fetch_failed: dict[str, int] = {}

    for t in targets:
        adapter = ADAPTERS[t.carrier](settings)
        attempted[t.carrier] = attempted.get(t.carrier, 0) + 1
        try:
            got = adapter.demo_plans(t) if demo else adapter.fetch(t)
        except NotImplementedError as e:
            errors.append(f"{t.carrier}/{t.category}/{t.state}: not implemented ({e})")
            fetch_failed[t.carrier] = fetch_failed.get(t.carrier, 0) + 1
            got = []
        except Exception as e:  # keep going; one target failing shouldn't abort the run
            errors.append(f"{t.carrier}/{t.category}/{t.state}: {type(e).__name__}: {e}")
            fetch_failed[t.carrier] = fetch_failed.get(t.carrier, 0) + 1
            got = []
        valid = [p.stamp(run_ts) for p in got if p.is_valid()]
        plans.extend(valid)
        per_carrier[t.carrier] = per_carrier.get(t.carrier, 0) + len(valid)

    # UNAVAILABLE (not degraded): every target we tried for this carrier failed to fetch, so we have
    # NO data from it — as opposed to a carrier that answered and produced an implausible count,
    # which is a parser/site problem and must still block. See check_sanity(unavailable=...).
    unavailable = {c for c in attempted
                   if per_carrier.get(c, 0) == 0 and fetch_failed.get(c, 0) == attempted[c]}

    print(f"Collected {len(plans)} valid plans across {len(targets)} targets.")
    for c, n in sorted(per_carrier.items()):
        print(f"  {c}: {n}{'  [UNAVAILABLE - all targets refused/failed]' if c in unavailable else ''}")
    for e in errors:
        print(f"  ! {e}")

    if not plans:
        print("No plans collected — aborting write so history is not wiped.", file=sys.stderr)
        return 2

    # CONVERGENT (combo) offers — a SEPARATE domain (#31, CONTEXT §14), collected AFTER the mobile
    # pass and FULLY GUARDED: every failure mode (import error, network, parse, bad config) is caught
    # per target and logged, so a convergent problem can NEVER block the mobile scrape, the workbook
    # write, or the commit (collection of mobile data > convergent). Skipped entirely in demo mode.
    # NOTE: passing an empty list to write_workbook PRESERVES the existing convergent history — the
    # sheet is always re-read and re-emitted (a rebuild would otherwise drop it).
    convergent: list = []
    per_carrier_conv: dict[str, int] = {}
    if not demo:
        try:
            from .adapters import CONVERGENT_ADAPTERS
            for ctarget, adapter_name in settings.convergent_targets():
                cls = CONVERGENT_ADAPTERS.get(adapter_name)
                if cls is None:
                    print(f"  ! convergent {ctarget.carrier}: unknown adapter '{adapter_name}' - skipped")
                    continue
                try:
                    got = cls(settings).fetch(ctarget)
                    valid = [o.stamp(run_ts) for o in got if o.is_valid()]
                    convergent.extend(valid)
                    per_carrier_conv[ctarget.carrier] = (per_carrier_conv.get(ctarget.carrier, 0)
                                                         + len(valid))
                    print(f"  convergent {ctarget.carrier}/{ctarget.category}: {len(valid)} offer(s)")
                except Exception as e:                      # one source failing must not stop the rest
                    print(f"  ! convergent {ctarget.carrier}/{ctarget.category}: "
                          f"{type(e).__name__}: {e} - skipped")
        except Exception as e:      # config/registry-level failure — skip the whole convergent pass
            print(f"  ! convergent pass skipped ({type(e).__name__}: {e})")

    # LIVE SANITY GUARDRAIL (GOVERNANCE §6) — extends the zero-guard from "zero" to "implausible", and
    # since #37 it judges BOTH domains, so it runs after the convergent pass. If any carrier's count
    # is outside its band, or any price is absurd, BLOCK: do NOT write/commit (the non-zero EXIT is
    # what stops the workflow's commit step — no degraded snapshot ever lands) AND send a SANITY email
    # (guarded: the e-mail is never what crashes the run, and its failure does not un-block anything).
    # ⚠️ Contrast with the price digest below, which is purely informational and must NEVER block.
    # A carrier that REFUSED us (403/CAPTCHA/network) contributes no data, and #40 stops that from
    # costing the carriers that DID answer. It is reported loudly and separately — never silently.
    # Mobile only. A convergent source failing is already logged-and-skipped by design and must never
    # escalate (CONTEXT §14) — it cannot cost the day, so it does not belong in this alert.
    if not demo and unavailable:
        names = ", ".join(sorted(unavailable))
        print(f"CARRIER UNAVAILABLE: mobile=[{names}] — committing the carriers that DID answer; "
              f"the missing ones are a recorded gap, never carried forward or invented.",
              file=sys.stderr)
        try:
            subj, body = alerts_mod.format_unavailable_email(sorted(unavailable), errors,
                                                            run_ts.date().isoformat())
            sent = alerts_mod.send_alert_email(settings.alerts, subj, body)
            print(f"alerts: carrier-unavailable email {'sent' if sent else 'not sent'}", file=sys.stderr)
        except Exception as e:
            print(f"alerts: unavailable-alert error ({type(e).__name__}: {e}) - continuing",
                  file=sys.stderr)

    if not demo:
        issues = alerts_mod.check_sanity(per_carrier, plans, settings.sanity,
                                         per_carrier_convergent=per_carrier_conv,
                                         convergent=convergent,
                                         unavailable=unavailable)
        # #40: split by domain. A CONVERGENT anomaly must never cost the mobile snapshot (CONTEXT
        # §14) — we drop this run's combo rows instead, which PRESERVES the stored convergent
        # history (write_workbook re-emits it when passed an empty list) and lets mobile commit.
        conv_issues = [i for i in issues if getattr(i, "domain", "mobile") == "convergent"]
        issues = [i for i in issues if getattr(i, "domain", "mobile") != "convergent"]
        if conv_issues:
            for i in conv_issues:
                print(f"SANITY (convergent, NOT blocking): [{i.carrier}] {i.kind}: {i.detail}",
                      file=sys.stderr)
            print(f"convergent: dropping this run's {len(convergent)} offer(s) — the stored "
                  f"convergent history is preserved and mobile still commits.", file=sys.stderr)
            convergent = []
            try:
                subj, body = alerts_mod.format_sanity_email(conv_issues, run_ts.date().isoformat())
                alerts_mod.send_alert_email(settings.alerts, subj.replace("SANITY CHECK FAILED",
                                                                          "CONVERGENT DATA SKIPPED"),
                                            body)
            except Exception as e:
                print(f"alerts: convergent-sanity alert error ({type(e).__name__}) - continuing",
                      file=sys.stderr)
        if issues:
            for i in issues:
                print(f"SANITY FAIL: [{i.carrier}] {i.kind}: {i.detail}", file=sys.stderr)
            try:
                subj, body = alerts_mod.format_sanity_email(issues, run_ts.date().isoformat())
                sent = alerts_mod.send_alert_email(settings.alerts, subj, body)
                print(f"alerts: sanity-fail email {'sent' if sent else 'not sent'}", file=sys.stderr)
            except Exception as e:  # the alert must never be the thing that crashes the run
                print(f"alerts: sanity-alert error ({type(e).__name__}: {e}) - continuing", file=sys.stderr)
            print(f"ALERT: sanity check failed ({len(issues)} issue(s)) — NOT committing this snapshot.",
                  file=sys.stderr)
            return 4

    # CATCH-UP MERGE (#41): re-submit the rows this day already has, or writing the date would
    # replace them with only what this pass scraped. See stored_plans_for().
    if only_if_incomplete and not demo:
        already = stored_plans_for(settings.output_xlsx, run_ts.date().isoformat())
        if already:
            fresh_carriers = {p.carrier for p in plans}
            keep = [p for p in already if p.carrier not in fresh_carriers]
            print(f"catch-up: carrying {len(keep)} row(s) already collected today for "
                  f"{sorted({p.carrier for p in keep})} into the merged snapshot.")
            plans = keep + plans

    result = write_workbook(plans, settings.output_xlsx, run_ts, convergent=convergent)
    print(
        f"Wrote {result['path']}: {result['plans_in_latest']} plans in latest "
        f"({result['snapshot_date']}), {result['snapshots_in_history']} snapshot(s), "
        f"{result['changes']} change(s); convergent: {len(convergent)} collected, "
        f"{result['convergent_rows']} row(s) over {result['convergent_snapshots']} snapshot(s)."
    )

    # Daily price-change email alert (live only). Fully guarded — alerts must NEVER fail the job or
    # block the data commit (collection > notification). Needs >= 2 snapshots to fire.
    acfg = settings.alerts
    if not demo and acfg.get("enabled"):
        try:
            from . import alerts as _alerts
            thr = float(acfg.get("threshold_pct", 3.0))
            found, date = _alerts.alerts_from_workbook(settings.output_xlsx, thr)
            if found:
                subject, body = _alerts.format_alert_email(found, date, thr)
                sent = _alerts.send_alert_email(acfg, subject, body)
                print(f"alerts: {len(found)} change(s) >={thr:g}% - email {'sent' if sent else 'not sent'}")
            else:
                print(f"alerts: none >={thr:g}% (or <2 snapshots yet)")
        except Exception as e:  # never let alerting break the run
            print(f"alerts: error ({type(e).__name__}: {e}) - continuing")

    # Note: a carrier scraping zero is now caught by the sanity guard above (0 < min_plans →
    # count_low → blocked + alerted before the workbook is written).
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Brazil mobile plan price tracker")
    ap.add_argument("--demo", action="store_true", help="offline run using sample data")
    ap.add_argument("--only", help="restrict to one carrier (vivo|claro|tim)")
    ap.add_argument("--only-if-incomplete", action="store_true",
                    help="catch-up pass: scrape ONLY the carriers missing from today's snapshot, "
                         "and do nothing at all if today is already complete (#40)")
    args = ap.parse_args()
    sys.exit(run(demo=args.demo, only=args.only, only_if_incomplete=args.only_if_incomplete))


if __name__ == "__main__":
    main()
