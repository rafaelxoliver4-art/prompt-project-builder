"""Offline tests for the MONTHLY price-evolution view (#12/#13/#16/#17).

#17 SPLIT the view into two sheets: `comparison` is now a TABLE-ONLY monthly matrix at the TOP of the
sheet (group titles row 1, TIM/Vivo/Claro row 2, months row 3+, frozen at B3, not protected, the active
sheet on open), and the 4 line charts moved to a separate `Charts` sheet that references the matrix via
cross-sheet refs. These tests assert: one matrix row per month (first-of-month date, 'mmm-yy' display),
each value cell a live MINIFS over `history` scoped to that month (text-prefix from the month cell —
EOMONTH date bounds can't filter history's text-stored dates, see excel_writer/_minifs_month), the
per-group heatmap, the table/charts split (no chart overlay on `comparison`), the Ranking view, and
same-day idempotency.
"""
import re
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, datetime

import openpyxl
import pandas as pd

from mobile_tracker.excel_writer import write_workbook, evolution_dates, evolution_months
from mobile_tracker.models import Plan

# Table-only `comparison` (#17): header rows 1/2, month data from row 3 (no chart offset).
H1, H2, FIRST = 1, 2, 3


def _sheet_xml_path(z: zipfile.ZipFile, sheet_name: str) -> str:
    """Map a sheet display name → its xl/worksheets/sheetN.xml path (via workbook.xml + rels)."""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
          "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    rid_to_target = {rel.get("Id"): rel.get("Target") for rel in rels}
    for sh in wb.find("m:sheets", ns):
        if sh.get("name") == sheet_name:
            rid = sh.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
            target = rid_to_target[rid].lstrip("/")
            return target if target.startswith("xl/") else "xl/" + target
    raise AssertionError(f"sheet {sheet_name!r} not found")


def _mk(carrier, cat, name, price, date_str):
    p = Plan(carrier=carrier, category=cat, state="SP", plan_name=name,
             plan_id=f"{carrier}:{name}", price_brl=price, source_url="x")
    p.snapshot_date = date_str
    p.snapshot_ts = f"{date_str}T18:00:00"
    return p


def _two_month(path):
    """History spanning May + June 2026 → the matrix should have exactly two month rows."""
    may = [_mk("tim", "postpaid", "TB", 122.0, "2026-05-20"),
           _mk("vivo", "postpaid", "VP", 150.0, "2026-05-20"),
           _mk("claro", "postpaid", "CP", 125.0, "2026-05-20"),
           _mk("vivo", "lite", "EL", 35.0, "2026-05-20"),
           _mk("claro", "flex", "FX", 50.0, "2026-05-20")]
    jun = [_mk("tim", "postpaid", "TB", 119.0, "2026-06-22"),
           _mk("vivo", "postpaid", "VP", 150.0, "2026-06-22"),
           _mk("claro", "postpaid", "CP", 124.9, "2026-06-22"),
           _mk("vivo", "lite", "EL", 30.0, "2026-06-22"),
           _mk("claro", "flex", "FX", 45.0, "2026-06-22")]
    write_workbook(may, path, datetime(2026, 5, 20, 18))
    write_workbook(jun, path, datetime(2026, 6, 22, 18))
    return path


def test_matrix_rows_are_months(tmp_path):
    wb = openpyxl.load_workbook(_two_month(tmp_path / "m.xlsx"))
    ws = wb["comparison"]
    assert ws.cell(row=H1, column=1).value == "Month"
    titles = [ws.cell(row=H1, column=c).value for c in (2, 5, 8, 11)]
    assert titles == ["Control (R$/mo)", "Post (R$/mo)", "Pre (R$/mo, 30-day)", "Digital (R$/mo)"]
    assert [ws.cell(row=H2, column=c).value for c in (2, 3, 4)] == ["TIM", "Vivo", "Claro"]
    # one row per month, stored as first-of-month dates, chronological
    m1 = ws.cell(row=FIRST, column=1).value
    m2 = ws.cell(row=FIRST + 1, column=1).value
    assert (m1.year, m1.month, m1.day) == (2026, 5, 1)
    assert (m2.year, m2.month, m2.day) == (2026, 6, 1)
    assert ws.cell(row=FIRST + 2, column=1).value is None       # only two months present


def test_month_cells_display_mmm_yy(tmp_path):
    wb = openpyxl.load_workbook(_two_month(tmp_path / "m.xlsx"))
    ws = wb["comparison"]
    assert ws.cell(row=FIRST, column=1).number_format == "mmm-yy"      # 2026-06-01 → "Jun-26"
    assert ws.cell(row=FIRST + 1, column=1).number_format == "mmm-yy"


def test_value_cells_are_month_scoped_minifs_over_history(tmp_path):
    wb = openpyxl.load_workbook(_two_month(tmp_path / "m.xlsx"))
    ws = wb["comparison"]
    post_tim = ws.cell(row=FIRST, column=5).value          # Post group, TIM column
    assert isinstance(post_tim, str)
    assert "MINIFS" in post_tim and "history!" in post_tim
    assert '"tim"' in post_tim and '"postpaid"' in post_tim
    # month scope = a text-prefix built from the month cell ($A3), not an exact-date match
    assert f"YEAR($A{FIRST})" in post_tim and f"MONTH($A{FIRST})" in post_tim and '"-*"' in post_tim
    # digital = cheapest of lite OR flex, same month scope, via the reciprocal-max min trick
    digital_vivo = ws.cell(row=FIRST, column=12).value
    assert '"lite"' in digital_vivo and '"flex"' in digital_vivo and f"MONTH($A{FIRST})" in digital_vivo
    assert "MAX(" in digital_vivo and "1/" in digital_vivo


def test_two_snapshots_same_month_roll_up_to_one_row(tmp_path):
    """The core roll-up: two daily snapshots in the SAME month collapse to ONE matrix row, while the
    daily detail stays in `history`. (The cheapest-across-days value is verified by real-Excel recalc;
    offline we assert the structure — one month row, a single month-scoped MINIFS spanning the month.)"""
    out = tmp_path / "m.xlsx"
    write_workbook([_mk("tim", "postpaid", "TB", 122.0, "2026-06-10"),
                    _mk("vivo", "postpaid", "VP", 150.0, "2026-06-10")],
                   out, datetime(2026, 6, 10, 18))
    write_workbook([_mk("tim", "postpaid", "TB", 118.0, "2026-06-20"),
                    _mk("vivo", "postpaid", "VP", 150.0, "2026-06-20")],
                   out, datetime(2026, 6, 20, 18))
    ws = openpyxl.load_workbook(out)["comparison"]
    m1 = ws.cell(row=FIRST, column=1).value
    assert (m1.year, m1.month, m1.day) == (2026, 6, 1)          # both days → the single Jun row
    assert ws.cell(row=FIRST + 1, column=1).value is None        # NOT two rows
    post_tim = ws.cell(row=FIRST, column=5).value
    assert "MINIFS" in post_tim and f"MONTH($A{FIRST})" in post_tim  # one MINIFS scoped to the whole month
    hist = pd.read_excel(out, sheet_name="history")
    assert set(hist["snapshot_date"].astype(str)) == {"2026-06-10", "2026-06-20"}  # daily detail kept


def _mk_pre(carrier, name, price, date_str, validity):
    p = _mk(carrier, "prepaid", name, price, date_str)
    p.validity_days = validity
    return p


def test_pre_column_filters_30day_validity(tmp_path):
    """#18: the Pre cell is a MINIFS that ALSO filters validity_days >= 28, so it picks the cheapest
    30-DAY prepaid plan — not a cheaper short-validity tier (the old R$1/day-style bug)."""
    from openpyxl.utils import get_column_letter
    from mobile_tracker.models import COLUMNS
    out = tmp_path / "m.xlsx"
    # Claro: a cheaper 15-day tier AND the real 30-day tier in the same month → Pre must pick the 30-day.
    write_workbook([
        _mk_pre("claro", "Prezão 5GB (15d)", 15.0, "2026-06-22", 15),
        _mk_pre("claro", "Prezão 12GB (30d)", 30.0, "2026-06-22", 30),
    ], out, datetime(2026, 6, 22, 18))
    wb = openpyxl.load_workbook(out)
    # history carries the new validity_days column
    assert "validity_days" in [c.value for c in wb["history"][1]]
    ws = wb["comparison"]
    pre_claro = ws.cell(row=FIRST, column=10).value     # Pre group cols 8/9/10 = TIM/Vivo/Claro
    assert isinstance(pre_claro, str) and "MINIFS" in pre_claro and '"prepaid"' in pre_claro
    vcol = get_column_letter(COLUMNS.index("validity_days") + 1)
    assert f'history!${vcol}:${vcol},">=28"' in pre_claro    # the 30-day validity filter


def test_evolution_months_year_boundary():
    """Dec→Jan rolls over correctly: sorted by (year, month), distinct first-of-month dates."""
    hist = pd.DataFrame({"snapshot_date": ["2027-01-05", "2026-12-20", "2026-12-31", "2027-01-28"]})
    assert evolution_months(hist) == [date(2026, 12, 1), date(2027, 1, 1)]


def test_heatmap_colorscale_present(tmp_path):
    wb = openpyxl.load_workbook(_two_month(tmp_path / "m.xlsx"))
    assert len(list(wb["comparison"].conditional_formatting)) >= 1


def test_four_line_charts_reference_monthly_matrix(tmp_path):
    out = _two_month(tmp_path / "m.xlsx")
    with zipfile.ZipFile(out) as z:
        xmls = [z.read(n).decode("utf-8")
                for n in z.namelist() if re.match(r"xl/charts/chart\d+\.xml$", n)]
    assert len(xmls) == 4                                       # Control / Post / Pre / Digital
    for xml in xmls:
        assert "'comparison'!$A" in xml                         # X = the Month column
        series_vals = re.findall(r"'comparison'!\$[B-M]\$\d+:\$[B-M]\$\d+", xml)
        assert len(series_vals) >= 3                            # TIM/Vivo/Claro value ranges (data rows)
        # series NAMES resolve to the row-2 carrier header (titles_from_data) → legend shows TIM/Vivo/Claro
        name_refs = re.findall(r"'comparison'!\$?[B-M]\$?2(?![0-9])", xml)
        assert len(name_refs) >= 3
    joined = "".join(xmls)
    for col in "BCDEFGHIJKLM":                                  # all 12 carrier×category columns charted
        assert f"'comparison'!${col}$" in joined
    for color in ("0033A0", "660099", "DA291C"):               # palette line colors (TIM/Vivo/Claro)
        assert color in joined


def test_charts_sheet_exists_and_comparison_is_table_only(tmp_path):
    """#17: the 4 charts hang off the `Charts` sheet; `comparison` is a chart-free table."""
    out = _two_month(tmp_path / "m.xlsx")
    assert "Charts" in openpyxl.load_workbook(out).sheetnames
    with zipfile.ZipFile(out) as z:
        comp_xml = z.read(_sheet_xml_path(z, "comparison")).decode("utf-8")
        charts_xml = z.read(_sheet_xml_path(z, "Charts")).decode("utf-8")
        assert "<drawing" not in comp_xml          # no chart overlay on the table sheet
        assert "<drawing" in charts_xml            # the charts drawing hangs off the Charts sheet


def test_comparison_is_active_sheet(tmp_path):
    """Opening the workbook lands on the clean `comparison` table, not on `history`."""
    wb = openpyxl.load_workbook(_two_month(tmp_path / "m.xlsx"))
    assert wb.active.title == "comparison"
    # and it is the ONLY selected tab, so Excel actually opens on it
    selected = [ws.title for ws in wb.worksheets if ws.sheet_view.tabSelected]
    assert selected == ["comparison"]


def test_comparison_table_only_frozen_b3_and_not_protected(tmp_path):
    """The 'locked' symptom is gone: header frozen at B3 (not a 36-row block), sheet never protected."""
    ws = openpyxl.load_workbook(_two_month(tmp_path / "m.xlsx"))["comparison"]
    assert ws.freeze_panes == "B3"
    assert ws.protection.sheet is False
    # the table truly starts at the top — header at row 1, data at row 3 (no chart offset)
    assert ws.cell(row=1, column=1).value == "Month"
    assert ws.cell(row=FIRST, column=1).value is not None


def test_ranking_view_preserved(tmp_path):
    wb = openpyxl.load_workbook(_two_month(tmp_path / "m.xlsx"))
    assert "Ranking" in wb.sheetnames
    assert wb["Ranking"].cell(row=1, column=1).value.startswith("Ranking")


def test_evolution_dates_helper():
    hist = pd.DataFrame({"snapshot_date": ["2026-06-22", "2026-06-21", "2026-06-22", None]})
    assert evolution_dates(hist) == ["2026-06-21", "2026-06-22"]


def test_evolution_months_helper():
    hist = pd.DataFrame(
        {"snapshot_date": ["2026-06-22", "2026-05-01", "2026-06-10", "2026-07-30", None]})
    assert evolution_months(hist) == [date(2026, 5, 1), date(2026, 6, 1), date(2026, 7, 1)]


def test_same_day_rerun_replaces_not_unions(tmp_path):
    out = tmp_path / "m.xlsx"
    write_workbook([_mk("tim", "postpaid", "A", 120.0, "2026-06-22"),
                    _mk("vivo", "postpaid", "B", 150.0, "2026-06-22")],
                   out, datetime(2026, 6, 22, 18))
    write_workbook([_mk("tim", "postpaid", "A", 117.0, "2026-06-22")], out, datetime(2026, 6, 22, 19))
    hist = pd.read_excel(out, sheet_name="history")
    rows = hist[hist["snapshot_date"].astype(str) == "2026-06-22"]
    assert len(rows) == 1 and float(rows.iloc[0]["price_brl"]) == 117.0
