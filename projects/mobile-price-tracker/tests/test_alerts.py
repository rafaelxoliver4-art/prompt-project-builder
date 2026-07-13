"""Offline tests for the price-change alert (CODE TASK #15). Pure functions + graceful-degradation;
no real SMTP is contacted."""
import mobile_tracker.alerts as alerts
from mobile_tracker.alerts import compute_price_alerts, format_alert_email, send_alert_email
from mobile_tracker.models import Plan


def P(carrier, cat, name, pid, price):
    return Plan(carrier=carrier, category=cat, state="SP", plan_name=name, plan_id=pid, price_brl=price)


def test_rise_and_drop_flagged_small_ignored():
    prev = [P("tim", "postpaid", "Black 70GB", "tim:1", 100.0),
            P("vivo", "control", "Controle", "vivo:2", 100.0),
            P("claro", "postpaid", "Pós", "claro:3", 100.0)]
    today = [P("tim", "postpaid", "Black 70GB", "tim:1", 105.0),     # +5%  → ▲
             P("vivo", "control", "Controle", "vivo:2", 96.0),       # -4%  → ▼
             P("claro", "postpaid", "Pós", "claro:3", 102.0)]        # +2%  → ignored
    found = compute_price_alerts(prev, today, 3.0)
    by = {a.plan_id: a for a in found}
    assert set(by) == {"tim:1", "vivo:2"}
    assert by["tim:1"].direction == "▲" and abs(by["tim:1"].pct - 5.0) < 1e-9
    assert by["vivo:2"].direction == "▼" and abs(by["vivo:2"].pct + 4.0) < 1e-9
    assert [a.plan_id for a in found] == ["tim:1", "vivo:2"]          # sorted by |pct| desc


def test_exactly_threshold_is_flagged():
    prev = [P("tim", "postpaid", "X", "tim:1", 100.0)]
    today = [P("tim", "postpaid", "X", "tim:1", 103.0)]               # exactly +3%
    assert len(compute_price_alerts(prev, today, 3.0)) == 1


def test_new_and_removed_not_flagged():
    prev = [P("tim", "postpaid", "A", "tim:1", 100.0)]                # tim:1 removed today
    today = [P("tim", "postpaid", "B", "tim:2", 100.0)]               # tim:2 new today (DIFFERENT name)
    assert compute_price_alerts(prev, today, 3.0) == []


def test_id_rotation_falls_back_to_name_match():
    """#29 (the missed TIM alert, 2026-07-06): TIM republished EVERY Controle plan under a fresh Drupal
    nid while cutting prices — id-matching saw remove+add and no alert went out. Same-name unmatched
    plans now pair across the rotation, so the real moves are flagged; same-price re-keys stay silent."""
    prev = [P("tim", "control", "TIM Controle 41GB", "tim:162901", 58.99),
            P("tim", "control", "TIM Controle Plus 45GB", "tim:155891", 64.99),
            P("tim", "control", "TIM Controle Premium 53GB", "tim:162896", 84.99),
            P("tim", "control", "TIM Controle Light Express 31GB", "tim:143536", 60.99),
            P("tim", "control", "TIM Controle Pro Express", "tim:143576", 64.99)]
    today = [P("tim", "control", "TIM Controle 41GB", "tim:167036", 49.99),          # −15.3%
             P("tim", "control", "TIM Controle Plus 45GB", "tim:167031", 59.99),     # −7.7%
             P("tim", "control", "TIM Controle Premium 53GB", "tim:167041", 69.99),  # −17.6%
             P("tim", "control", "TIM Controle Light Express 31GB", "tim:167046", 60.99),  # re-key only
             P("tim", "control", "TIM Controle Pro Express", "tim:167051", 64.99)]         # re-key only
    found = compute_price_alerts(prev, today, 3.0)
    assert {a.plan_name for a in found} == {"TIM Controle 41GB", "TIM Controle Plus 45GB",
                                            "TIM Controle Premium 53GB"}
    assert found[0].plan_name == "TIM Controle Premium 53GB"          # sorted by |pct| desc (−17.6% first)
    assert all(a.direction == "▼" for a in found)


def test_rotation_ambiguous_names_not_paired():
    """#29 guard: the name fallback pairs ONLY 1:1 — duplicated names on either unmatched side must
    not produce a (possibly false) alert."""
    prev = [P("tim", "control", "Dup", "tim:1", 100.0),
            P("tim", "control", "Dup", "tim:2", 200.0)]               # two prev plans, same name
    today = [P("tim", "control", "Dup", "tim:9", 150.0)]              # which one is it? → don't guess
    assert compute_price_alerts(prev, today, 3.0) == []
    prev2 = [P("tim", "control", "Dup", "tim:1", 100.0)]
    today2 = [P("tim", "control", "Dup", "tim:8", 150.0),
              P("tim", "control", "Dup", "tim:9", 150.0)]             # two claimants today → don't guess
    assert compute_price_alerts(prev2, today2, 3.0) == []


def test_rotation_fallback_still_id_first():
    """#29: an intact id match wins; the fallback only engages for ids that VANISHED. A plan whose id
    survives is never re-paired by name, and its leftover-free name can't be claimed."""
    prev = [P("claro", "control", "Controle 30GB", "claro:a", 100.0)]
    today = [P("claro", "control", "Controle 30GB", "claro:a", 110.0),  # id match: +10% → alert
             P("claro", "control", "Controle 30GB", "claro:b", 999.0)]  # new same-name card: NOT paired
    found = compute_price_alerts(prev, today, 3.0)
    assert len(found) == 1 and found[0].plan_id == "claro:a" and abs(found[0].pct - 10.0) < 1e-9


def test_format_email_subject_and_body():
    found = compute_price_alerts([P("tim", "postpaid", "Black 70GB", "tim:1", 100.0)],
                                 [P("tim", "postpaid", "Black 70GB", "tim:1", 110.0)], 3.0)
    subject, body = format_alert_email(found, "2026-06-23", 3.0)
    assert "1 price change" in subject and "2026-06-23" in subject and "3%" in subject
    assert "[TIM] Black 70GB (postpaid)" in body
    assert "R$ 100.00" in body and "R$ 110.00" in body and "▲" in body and "10.0%" in body


def test_send_skips_without_password(monkeypatch):
    monkeypatch.delenv("EMAIL_APP_PASSWORD", raising=False)
    cfg = {"from_email": "a@b.com", "to_email": "c@d.com", "smtp_host": "smtp.x", "smtp_port": 587}
    assert send_alert_email(cfg, "subj", "body") is False             # graceful skip, no exception


def test_send_catches_smtp_error(monkeypatch):
    monkeypatch.setenv("EMAIL_APP_PASSWORD", "dummy")

    def boom(*a, **k):
        raise OSError("smtp unreachable")

    monkeypatch.setattr(alerts.smtplib, "SMTP", boom)
    cfg = {"from_email": "a@b.com", "to_email": "c@d.com", "smtp_host": "smtp.x", "smtp_port": 587}
    assert send_alert_email(cfg, "s", "b") is False                  # caught, never raises


def test_alerts_from_workbook_needs_two_snapshots(tmp_path):
    # the integration glue main.py uses: read history, diff the two latest snapshot_dates
    from datetime import datetime
    from mobile_tracker.excel_writer import write_workbook

    def mk(price, d):
        p = Plan(carrier="tim", category="postpaid", state="SP", plan_name="Black",
                 plan_id="tim:b", price_brl=price, source_url="x")
        p.snapshot_date = d
        p.snapshot_ts = f"{d}T18:00:00"
        return p

    out1 = tmp_path / "one.xlsx"
    write_workbook([mk(100.0, "2026-06-21")], out1, datetime(2026, 6, 21, 18))
    assert alerts.alerts_from_workbook(out1, 3.0)[0] == []            # <2 snapshots → nothing

    out2 = tmp_path / "two.xlsx"
    write_workbook([mk(100.0, "2026-06-21")], out2, datetime(2026, 6, 21, 18))
    write_workbook([mk(110.0, "2026-06-22")], out2, datetime(2026, 6, 22, 18))  # +10%
    found, date = alerts.alerts_from_workbook(out2, 3.0)
    assert date == "2026-06-22"
    assert len(found) == 1 and found[0].plan_id == "tim:b" and abs(found[0].pct - 10.0) < 1e-9
