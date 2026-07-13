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


def test_creates_expected_sheets(tmp_path):
    out = tmp_path / "plans.xlsx"
    write_workbook([_plan("A", 50.0, "2026-06-10")], out, datetime(2026, 6, 10, 23))
    names = set(pd.ExcelFile(out).sheet_names)
    assert {"history", "latest", "changes", "summary", "comparison"}.issubset(names)
    assert "Claro" in names                       # operator sheet for the (claro) plan present
    assert {"Vivo", "TIM"}.isdisjoint(names)      # carriers absent from latest → no sheet


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


def _idplan(name, pid, price, date, carrier="tim", cat="control"):
    p = Plan(carrier=carrier, category=cat, state="SP", plan_name=name, plan_id=pid,
             price_brl=price, source_url="http://x")
    p.snapshot_date = date
    p.snapshot_ts = f"{date}T23:00:00"
    return p


def test_changes_survive_plan_id_rotation(tmp_path):
    """#29 (the missed TIM alert): the carrier republishes the SAME plans under fresh native ids.
    The changes sheet must report the real price moves as price_change (via the unambiguous same-name
    pairing) — not a wall of removed+new — and a pure re-key (same name, same price) must be silent."""
    out = tmp_path / "plans.xlsx"
    write_workbook([_idplan("TIM Controle 41GB", "tim:162901", 58.99, "2026-07-05"),
                    _idplan("TIM Controle Premium 53GB", "tim:162896", 84.99, "2026-07-05"),
                    _idplan("TIM Controle Pro Express", "tim:143576", 64.99, "2026-07-05")],
                   out, datetime(2026, 7, 5, 23))
    write_workbook([_idplan("TIM Controle 41GB", "tim:167036", 49.99, "2026-07-06"),      # −15.3%
                    _idplan("TIM Controle Premium 53GB", "tim:167041", 69.99, "2026-07-06"),  # −17.6%
                    _idplan("TIM Controle Pro Express", "tim:167051", 64.99, "2026-07-06")],  # re-key only
                   out, datetime(2026, 7, 6, 23))
    changes = pd.read_excel(out, sheet_name="changes")
    kinds = dict(zip(changes["plan_name"], changes["change_type"]))
    assert kinds == {"TIM Controle 41GB": "price_change",
                     "TIM Controle Premium 53GB": "price_change"}     # re-key row absent; NO new/removed
    row = changes[changes.plan_name == "TIM Controle 41GB"].iloc[0]
    assert row["plan_id"] == "tim:167036"                             # reported under the NEW id
    assert abs(float(row["delta_brl"]) + 9.0) < 1e-9
    # history keeps BOTH days' rows untouched (rotation affects only the diff view)
    hist = pd.read_excel(out, sheet_name="history")
    assert len(hist) == 6


def test_changes_rotation_ambiguous_names_stay_new_removed(tmp_path):
    """#29 guard: duplicated names among the unmatched rows must NOT pair — keep honest new+removed."""
    out = tmp_path / "plans.xlsx"
    write_workbook([_idplan("Dup", "tim:1", 100.0, "2026-07-05"),
                    _idplan("Dup", "tim:2", 200.0, "2026-07-05")],
                   out, datetime(2026, 7, 5, 23))
    write_workbook([_idplan("Dup", "tim:9", 150.0, "2026-07-06")],
                   out, datetime(2026, 7, 6, 23))
    changes = pd.read_excel(out, sheet_name="changes")
    assert sorted(changes["change_type"]) == ["new", "removed", "removed"]   # no guessed pairing


def test_merge_history_enforces_schema_order(tmp_path):
    # #18 regression: a pre-#18 history (no validity_days column) merged with new rows that DO have it
    # must keep COLUMNS order — otherwise pd.concat appends validity_days at the end and the matrix's
    # column-letter formulas (history!$M:$M) point at the wrong column.
    from mobile_tracker.excel_writer import _merge_history
    from mobile_tracker.models import COLUMNS
    old_cols = [c for c in COLUMNS if c != "validity_days"]
    existing = pd.DataFrame([dict(snapshot_date="2026-06-22", carrier="claro", category="prepaid",
                                  state="SP", plan_name="Prezão", plan_id="claro:x", price_brl=1.0)],
                            columns=old_cols)
    fresh = pd.DataFrame([dict(snapshot_date="2026-06-23", carrier="claro", category="prepaid",
                               state="SP", plan_name="Prezão 12GB", plan_id="claro:prezao-30d-12gb",
                               price_brl=30.0, validity_days=30)], columns=COLUMNS)
    merged = _merge_history(existing, fresh)
    assert list(merged.columns) == COLUMNS                # validity_days at its schema position (M), not end


def test_rerun_same_day_is_idempotent(tmp_path):
    out = tmp_path / "plans.xlsx"
    write_workbook([_plan("A", 50.0, "2026-06-10")], out, datetime(2026, 6, 10, 23))
    write_workbook([_plan("A", 55.0, "2026-06-10")], out, datetime(2026, 6, 10, 23, 30))
    history = pd.read_excel(out, sheet_name="history")
    assert len(history) == 1                       # same key+date => updated, not duplicated
    assert history["price_brl"].iloc[0] == 55.0


def _plan_id(name, pid, price, date):
    p = Plan(carrier="claro", category="control", state="SP",
             plan_name=name, plan_id=pid, price_brl=price, source_url="http://x")
    p.snapshot_date = date
    p.snapshot_ts = f"{date}T23:00:00"
    return p


def test_same_name_distinct_plan_id_both_survive_in_latest(tmp_path):
    # The whole point of plan_id: two plans sharing a display name must NOT collapse.
    out = tmp_path / "plans.xlsx"
    write_workbook([
        _plan_id("Controle 30GB", "claro:plano-controle-30gb", 69.90, "2026-06-19"),
        _plan_id("Controle 30GB", "claro:plano-controle-30gb-gaming", 99.90, "2026-06-19"),
    ], out, datetime(2026, 6, 19, 23))
    latest = pd.read_excel(out, sheet_name="latest")
    assert len(latest) == 2                                    # NOT collapsed by name
    assert set(latest["plan_id"]) == {"claro:plano-controle-30gb",
                                      "claro:plano-controle-30gb-gaming"}
    assert list(latest["plan_name"]) == ["Controle 30GB", "Controle 30GB"]


def test_price_change_tracked_per_plan_id_not_name(tmp_path):
    # Same name, distinct ids: a price move on one must not be confused with the other.
    out = tmp_path / "plans.xlsx"
    write_workbook([
        _plan_id("Controle 30GB", "claro:plano-controle-30gb", 69.90, "2026-06-19"),
        _plan_id("Controle 30GB", "claro:plano-controle-30gb-gaming", 99.90, "2026-06-19"),
    ], out, datetime(2026, 6, 19, 23))
    write_workbook([
        _plan_id("Controle 30GB", "claro:plano-controle-30gb", 74.90, "2026-06-20"),       # +5
        _plan_id("Controle 30GB", "claro:plano-controle-30gb-gaming", 99.90, "2026-06-20"),  # unchanged
    ], out, datetime(2026, 6, 20, 23))
    changes = pd.read_excel(out, sheet_name="changes")
    moved = changes[changes.change_type == "price_change"]
    assert len(moved) == 1
    assert moved["plan_id"].iloc[0] == "claro:plano-controle-30gb"
    assert abs(moved["delta_brl"].iloc[0] - 5.0) < 1e-9
