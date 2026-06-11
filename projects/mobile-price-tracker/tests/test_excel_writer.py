from datetime import datetime

import pandas as pd

from mobile_tracker.excel_writer import write_workbook
from mobile_tracker.models import Plan


def _plan(name, price, date):
    p = Plan(carrier="claro", category="control", state="SP",
             plan_name=name, price_brl=price, source_url="http://x")
    p.snapshot_date = date
    p.snapshot_ts = f"{date}T23:00:00"
    return p


def test_creates_four_sheets(tmp_path):
    out = tmp_path / "plans.xlsx"
    write_workbook([_plan("A", 50.0, "2026-06-10")], out, datetime(2026, 6, 10, 23))
    xls = pd.ExcelFile(out)
    assert set(xls.sheet_names) == {"history", "latest", "changes", "summary"}


def test_history_is_append_only_and_changes_detected(tmp_path):
    out = tmp_path / "plans.xlsx"
    # Day 1: two plans.
    write_workbook([_plan("A", 50.0, "2026-06-10"), _plan("B", 80.0, "2026-06-10")],
                   out, datetime(2026, 6, 10, 23))
    # Day 2: A price rises, B drops out, C is new.
    write_workbook([_plan("A", 60.0, "2026-06-11"), _plan("C", 99.0, "2026-06-11")],
                   out, datetime(2026, 6, 11, 23))

    history = pd.read_excel(out, sheet_name="history")
    latest = pd.read_excel(out, sheet_name="latest")
    changes = pd.read_excel(out, sheet_name="changes")

    assert len(history) == 4                       # nothing overwritten
    assert set(latest["plan_name"]) == {"A", "C"}  # latest = day 2 only
    kinds = dict(zip(changes["plan_name"], changes["change_type"]))
    assert kinds["A"] == "price_change"
    assert kinds["B"] == "removed"
    assert kinds["C"] == "new"
    delta = changes.loc[changes.plan_name == "A", "delta_brl"].iloc[0]
    assert abs(delta - 10.0) < 1e-9


def test_rerun_same_day_is_idempotent(tmp_path):
    out = tmp_path / "plans.xlsx"
    write_workbook([_plan("A", 50.0, "2026-06-10")], out, datetime(2026, 6, 10, 23))
    write_workbook([_plan("A", 55.0, "2026-06-10")], out, datetime(2026, 6, 10, 23, 30))
    history = pd.read_excel(out, sheet_name="history")
    assert len(history) == 1                       # same key+date => updated, not duplicated
    assert history["price_brl"].iloc[0] == 55.0
