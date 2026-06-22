"""Offline tests for the price-evolution matrix `comparison` sheet (CODE TASK #12).

Builds a 2-date history and asserts the Date × (category × carrier) matrix structure, that value
cells are LIVE MINIFS formulas over the history sheet, a heatmap colour-scale, the Ranking view
preserved on its own sheet, and same-day idempotency (a re-run replaces that date's rows).
"""
from datetime import datetime

import openpyxl

from mobile_tracker.excel_writer import write_workbook, evolution_dates
from mobile_tracker.models import Plan
import pandas as pd


def _mk(carrier, cat, name, price, date):
    p = Plan(carrier=carrier, category=cat, state="SP", plan_name=name,
             plan_id=f"{carrier}:{name}", price_brl=price, source_url="x")
    p.snapshot_date = date
    p.snapshot_ts = f"{date}T18:00:00"
    return p


def _two_day_workbook(path):
    day1 = [_mk("tim", "postpaid", "TB", 120.0, "2026-06-21"),
            _mk("vivo", "postpaid", "VP", 150.0, "2026-06-21"),
            _mk("claro", "postpaid", "CP", 125.0, "2026-06-21"),
            _mk("vivo", "lite", "EL", 30.0, "2026-06-21"),
            _mk("claro", "flex", "FX", 45.0, "2026-06-21")]
    day2 = [_mk("tim", "postpaid", "TB", 119.0, "2026-06-22"),
            _mk("vivo", "postpaid", "VP", 150.0, "2026-06-22"),
            _mk("claro", "postpaid", "CP", 124.9, "2026-06-22")]
    write_workbook(day1, path, datetime(2026, 6, 21, 18))
    write_workbook(day2, path, datetime(2026, 6, 22, 18))
    return openpyxl.load_workbook(path)


def test_matrix_structure(tmp_path):
    wb = _two_day_workbook(tmp_path / "m.xlsx")
    ws = wb["comparison"]
    assert ws["A3"].value == "Date"
    titles = [ws.cell(row=3, column=c).value for c in (2, 5, 8, 11)]
    assert titles == ["Control (R$/mo)", "Post (R$/mo)", "Pre (R$, recarga)", "Digital (R$/mo)"]
    assert [ws.cell(row=4, column=c).value for c in (2, 3, 4)] == ["TIM", "Vivo", "Claro"]
    # one matrix row per distinct date, chronological
    assert ws["A5"].value == "2026-06-21"
    assert ws["A6"].value == "2026-06-22"


def test_value_cells_are_live_history_formulas(tmp_path):
    wb = _two_day_workbook(tmp_path / "m.xlsx")
    ws = wb["comparison"]
    post_tim = ws["E5"].value                      # Post group, TIM, first date
    assert isinstance(post_tim, str) and post_tim.startswith("=")
    assert "MINIFS" in post_tim and "history!" in post_tim
    assert '"tim"' in post_tim and '"postpaid"' in post_tim
    digital_vivo = ws["L5"].value                  # Digital = min over lite/flex
    assert "lite" in digital_vivo and "flex" in digital_vivo


def test_heatmap_colorscale_present(tmp_path):
    wb = _two_day_workbook(tmp_path / "m.xlsx")
    assert len(list(wb["comparison"].conditional_formatting)) >= 1


def test_ranking_view_preserved(tmp_path):
    wb = _two_day_workbook(tmp_path / "m.xlsx")
    assert "Ranking" in wb.sheetnames
    # the Ranking sheet keeps the rank-aligned header
    assert wb["Ranking"].cell(row=1, column=1).value.startswith("Ranking")


def test_evolution_dates_helper():
    hist = pd.DataFrame({"snapshot_date": ["2026-06-22", "2026-06-21", "2026-06-22", None]})
    assert evolution_dates(hist) == ["2026-06-21", "2026-06-22"]


def test_same_day_rerun_replaces_not_unions(tmp_path):
    out = tmp_path / "m.xlsx"
    write_workbook([_mk("tim", "postpaid", "A", 120.0, "2026-06-22"),
                    _mk("vivo", "postpaid", "B", 150.0, "2026-06-22")],
                   out, datetime(2026, 6, 22, 18))
    # re-run the SAME date with a different (smaller) set → that date is replaced, not unioned
    write_workbook([_mk("tim", "postpaid", "A", 117.0, "2026-06-22")], out, datetime(2026, 6, 22, 19))
    hist = pd.read_excel(out, sheet_name="history")
    rows_0622 = hist[hist["snapshot_date"].astype(str) == "2026-06-22"]
    assert len(rows_0622) == 1                     # replaced (not 2)
    assert float(rows_0622.iloc[0]["price_brl"]) == 117.0
