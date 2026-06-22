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
    today = [P("tim", "postpaid", "B", "tim:2", 100.0)]               # tim:2 new today
    assert compute_price_alerts(prev, today, 3.0) == []


def test_matched_by_plan_id_not_name():
    prev = [P("claro", "control", "Controle 30GB", "claro:30gb", 100.0)]
    today_diff_id = [P("claro", "control", "Controle 30GB", "claro:30gb-gaming", 200.0)]  # same name, diff id
    assert compute_price_alerts(prev, today_diff_id, 3.0) == []       # not the same plan → no alert
    today_same_id = [P("claro", "control", "Controle 30GB", "claro:30gb", 110.0)]
    assert len(compute_price_alerts(prev, today_same_id, 3.0)) == 1


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
