"""Offline tests for the price-evolution matrix + line charts (`comparison` sheet, #12 + #13).

Builds a 2-date history and asserts: the Date × (category × carrier) matrix structure (now placed
below the chart block), live MINIFS formulas over history, the heatmap, four per-category line
charts referencing the matrix, the Ranking view preserved, and same-day idempotency.
"""
import re
import zipfile
from datetime import datetime

import openpyxl
import pandas as pd

from mobile_tracker.excel_writer import write_workbook, evolution_dates
from mobile_tracker.models import Plan

# The matrix sits below the 2×2 chart block: header rows 35/36, data from row 37 (excel_writer).
H1, H2, FIRST = 35, 36, 37


def _mk(carrier, cat, name, price, date):
    p = Plan(carrier=carrier, category=cat, state="SP", plan_name=name,
             plan_id=f"{carrier}:{name}", price_brl=price, source_url="x")
    p.snapshot_date = date
    p.snapshot_ts = f"{date}T18:00:00"
    return p


def _two_day(path):
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
    return path


def test_matrix_structure(tmp_path):
    wb = openpyxl.load_workbook(_two_day(tmp_path / "m.xlsx"))
    ws = wb["comparison"]
    assert ws.cell(row=H1, column=1).value == "Date"
    titles = [ws.cell(row=H1, column=c).value for c in (2, 5, 8, 11)]
    assert titles == ["Control (R$/mo)", "Post (R$/mo)", "Pre (R$, recarga)", "Digital (R$/mo)"]
    assert [ws.cell(row=H2, column=c).value for c in (2, 3, 4)] == ["TIM", "Vivo", "Claro"]
    assert ws.cell(row=FIRST, column=1).value == "2026-06-21"
    assert ws.cell(row=FIRST + 1, column=1).value == "2026-06-22"


def test_value_cells_are_live_history_formulas(tmp_path):
    wb = openpyxl.load_workbook(_two_day(tmp_path / "m.xlsx"))
    ws = wb["comparison"]
    post_tim = ws.cell(row=FIRST, column=5).value      # Post group, TIM
    assert isinstance(post_tim, str) and "MINIFS" in post_tim and "history!" in post_tim
    assert '"tim"' in post_tim and '"postpaid"' in post_tim
    digital_vivo = ws.cell(row=FIRST, column=12).value  # Digital = min over lite/flex
    assert "lite" in digital_vivo and "flex" in digital_vivo


def test_heatmap_colorscale_present(tmp_path):
    wb = openpyxl.load_workbook(_two_day(tmp_path / "m.xlsx"))
    assert len(list(wb["comparison"].conditional_formatting)) >= 1


def test_four_line_charts_reference_matrix(tmp_path):
    out = _two_day(tmp_path / "m.xlsx")
    with zipfile.ZipFile(out) as z:
        xmls = [z.read(n).decode("utf-8")
                for n in z.namelist() if re.match(r"xl/charts/chart\d+\.xml$", n)]
    assert len(xmls) == 4                                       # Control / Post / Pre / Digital
    for xml in xmls:
        assert "'comparison'!$A" in xml                         # X = the Date column
        series_vals = re.findall(r"'comparison'!\$[B-M]\$\d+:\$[B-M]\$\d+", xml)
        assert len(series_vals) >= 3                            # TIM/Vivo/Claro series
    joined = "".join(xmls)
    for col in "BCDEFGHIJKLM":                                  # all 12 carrier×category columns charted
        assert f"'comparison'!${col}$" in joined
    for color in ("0033A0", "660099", "DA291C"):               # palette line colors (TIM/Vivo/Claro)
        assert color in joined


def test_ranking_view_preserved(tmp_path):
    wb = openpyxl.load_workbook(_two_day(tmp_path / "m.xlsx"))
    assert "Ranking" in wb.sheetnames
    assert wb["Ranking"].cell(row=1, column=1).value.startswith("Ranking")


def test_evolution_dates_helper():
    hist = pd.DataFrame({"snapshot_date": ["2026-06-22", "2026-06-21", "2026-06-22", None]})
    assert evolution_dates(hist) == ["2026-06-21", "2026-06-22"]


def test_same_day_rerun_replaces_not_unions(tmp_path):
    out = tmp_path / "m.xlsx"
    write_workbook([_mk("tim", "postpaid", "A", 120.0, "2026-06-22"),
                    _mk("vivo", "postpaid", "B", 150.0, "2026-06-22")],
                   out, datetime(2026, 6, 22, 18))
    write_workbook([_mk("tim", "postpaid", "A", 117.0, "2026-06-22")], out, datetime(2026, 6, 22, 19))
    hist = pd.read_excel(out, sheet_name="history")
    rows = hist[hist["snapshot_date"].astype(str) == "2026-06-22"]
    assert len(rows) == 1 and float(rows.iloc[0]["price_brl"]) == 117.0
