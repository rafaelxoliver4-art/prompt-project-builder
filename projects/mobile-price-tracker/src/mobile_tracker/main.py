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

from . import config
from .adapters import ADAPTERS
from .excel_writer import write_workbook
from .models import Plan


def run(demo: bool = False, only: str | None = None) -> int:
    settings = config.load()
    run_ts = datetime.now()
    targets = [t for t in settings.targets() if (only is None or t.carrier == only)]

    plans: list[Plan] = []
    per_carrier: dict[str, int] = {}
    errors: list[str] = []

    for t in targets:
        adapter = ADAPTERS[t.carrier](settings)
        try:
            got = adapter.demo_plans(t) if demo else adapter.fetch(t)
        except NotImplementedError as e:
            errors.append(f"{t.carrier}/{t.category}/{t.state}: not implemented ({e})")
            got = []
        except Exception as e:  # keep going; one target failing shouldn't abort the run
            errors.append(f"{t.carrier}/{t.category}/{t.state}: {type(e).__name__}: {e}")
            got = []
        valid = [p.stamp(run_ts) for p in got if p.is_valid()]
        plans.extend(valid)
        per_carrier[t.carrier] = per_carrier.get(t.carrier, 0) + len(valid)

    print(f"Collected {len(plans)} valid plans across {len(targets)} targets.")
    for c, n in sorted(per_carrier.items()):
        print(f"  {c}: {n}")
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
                    print(f"  convergent {ctarget.carrier}/{ctarget.category}: {len(valid)} offer(s)")
                except Exception as e:                      # one source failing must not stop the rest
                    print(f"  ! convergent {ctarget.carrier}/{ctarget.category}: "
                          f"{type(e).__name__}: {e} - skipped")
        except Exception as e:      # config/registry-level failure — skip the whole convergent pass
            print(f"  ! convergent pass skipped ({type(e).__name__}: {e})")

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

    # In live mode, a carrier scraping zero is an alert condition (GOVERNANCE §6).
    if not demo:
        zero = [c for c in ("vivo", "claro", "tim") if per_carrier.get(c, 0) == 0]
        if zero:
            print(f"ALERT: zero plans for {zero} — investigate.", file=sys.stderr)
            return 3
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Brazil mobile plan price tracker")
    ap.add_argument("--demo", action="store_true", help="offline run using sample data")
    ap.add_argument("--only", help="restrict to one carrier (vivo|claro|tim)")
    args = ap.parse_args()
    sys.exit(run(demo=args.demo, only=args.only))


if __name__ == "__main__":
    main()
