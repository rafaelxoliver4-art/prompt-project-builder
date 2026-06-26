"""Offline tests for the DAILY price-evolution view (#12/#13/#16/#17/#18/#19).

#19 changed the matrix from MONTHLY rows back to DAILY rows: `comparison` has one row per distinct
snapshot_date (earliest first), each value cell a live EXACT-date MINIFS over `history` (a locale-safe
text date built from the row's date — history stores dates as TEXT, see excel_writer/_minifs_day). The
table-only layout (#17) is unchanged: group titles row 1, TIM/Vivo/Claro row 2, day rows from row 3,
frozen at B3, not protected, the active sheet; the 4 charts live on the `Charts` sheet via cross-sheet
refs. The heatmap is now a 2-color green→yellow scale (JPMorgan style), per carrier column, no red.
"""
import re
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, datetime

import openpyxl
import pandas as pd

from mobile_tracker.excel_writer import write_workbook, evolution_dates, evolution_months
from mobile_tracker.models import Plan

# Table-only `comparison` (#17): header rows 1/2, day data from row 3 (no chart offset).
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


def _multi_day(path):
    """History with 3 distinct snapshot_dates → the matrix should have one row per date, earliest first."""
    for d, tim, vivo, claro in [("2026-06-22", 122.0, 150.0, 125.0),
                                ("2026-06-23", 121.0, 150.0, 124.9),
                                ("2026-06-24", 119.0, 149.0, 124.0)]:
        plans = [_mk("tim", "postpaid", "TB", tim, d),
                 _mk("vivo", "postpaid", "VP", vivo, d),
                 _mk("claro", "postpaid", "CP", claro, d),
                 _mk("vivo", "lite", "EL", 30.0, d),
                 _mk("claro", "flex", "FX", 45.0, d)]
        write_workbook(plans, path, datetime(2026, 6, int(d[-2:]), 18))
    return path


def test_matrix_rows_are_days(tmp_path):
    wb = openpyxl.load_workbook(_multi_day(tmp_path / "m.xlsx"))
    ws = wb["comparison"]
    assert ws.cell(row=H1, column=1).value == "Date"
    titles = [ws.cell(row=H1, column=c).value for c in (2, 5, 8, 11)]
    assert titles == ["Control (R$/mo)", "Post (R$/mo)", "Pre (R$/mo, 30-day)", "Digital (R$/mo)"]
    assert [ws.cell(row=H2, column=c).value for c in (2, 3, 4)] == ["TIM", "Vivo", "Claro"]
    # one row per snapshot_date, stored as real dates, EARLIEST first
    d1 = ws.cell(row=FIRST, column=1).value
    d2 = ws.cell(row=FIRST + 1, column=1).value
    d3 = ws.cell(row=FIRST + 2, column=1).value
    assert (d1.year, d1.month, d1.day) == (2026, 6, 22)       # 2026-06-22 is the FIRST row
    assert (d2.year, d2.month, d2.day) == (2026, 6, 23)
    assert (d3.year, d3.month, d3.day) == (2026, 6, 24)
    assert ws.cell(row=FIRST + 3, column=1).value is None       # only three dates present


def test_day_cells_display_dd_mmm(tmp_path):
    ws = openpyxl.load_workbook(_multi_day(tmp_path / "m.xlsx"))["comparison"]
    assert ws.cell(row=FIRST, column=1).number_format == "dd-mmm"      # 2026-06-22 → "22-Jun"
    assert ws.cell(row=FIRST + 2, column=1).number_format == "dd-mmm"


def test_value_cells_are_exact_date_minifs_over_history(tmp_path):
    ws = openpyxl.load_workbook(_multi_day(tmp_path / "m.xlsx"))["comparison"]
    post_tim = ws.cell(row=FIRST, column=5).value          # Post group, TIM column
    assert isinstance(post_tim, str)
    assert "MINIFS" in post_tim and "history!" in post_tim
    assert '"tim"' in post_tim and '"postpaid"' in post_tim
    # EXACT date = a text date built from the date cell ($A3): YEAR/MONTH/DAY, NO wildcard
    assert f"YEAR($A{FIRST})" in post_tim and f"DAY($A{FIRST})" in post_tim
    assert '"-*"' not in post_tim                            # exact date, NOT a month prefix
    # digital = cheapest of lite OR flex, same exact-date scope, via the reciprocal-max min trick
    digital_vivo = ws.cell(row=FIRST, column=12).value
    assert '"lite"' in digital_vivo and '"flex"' in digital_vivo and f"DAY($A{FIRST})" in digital_vivo
    assert "MAX(" in digital_vivo and "1/" in digital_vivo


def test_distinct_dates_one_row_each(tmp_path):
    """Daily: two snapshots on DIFFERENT dates → TWO rows (one per date), not a roll-up; history keeps both."""
    out = tmp_path / "m.xlsx"
    write_workbook([_mk("tim", "postpaid", "TB", 122.0, "2026-06-22")], out, datetime(2026, 6, 22, 18))
    write_workbook([_mk("tim", "postpaid", "TB", 118.0, "2026-06-23")], out, datetime(2026, 6, 23, 18))
    ws = openpyxl.load_workbook(out)["comparison"]
    d1 = ws.cell(row=FIRST, column=1).value
    d2 = ws.cell(row=FIRST + 1, column=1).value
    assert (d1.month, d1.day) == (6, 22) and (d2.month, d2.day) == (6, 23)   # two distinct daily rows
    assert ws.cell(row=FIRST + 2, column=1).value is None
    hist = pd.read_excel(out, sheet_name="history")
    assert set(hist["snapshot_date"].astype(str)) == {"2026-06-22", "2026-06-23"}


def _mk_pre(carrier, name, price, date_str, validity):
    p = _mk(carrier, "prepaid", name, price, date_str)
    p.validity_days = validity
    return p


def test_pre_column_filters_30day_validity(tmp_path):
    """#18: the Pre cell is a MINIFS that ALSO filters validity_days >= 28, so it picks the cheapest
    30-DAY prepaid plan on that date — not a cheaper short-validity tier (the old R$1/day-style bug)."""
    from openpyxl.utils import get_column_letter
    from mobile_tracker.models import COLUMNS
    out = tmp_path / "m.xlsx"
    # Claro: a cheaper 15-day tier AND the real 30-day tier on the same date → Pre must pick the 30-day.
    write_workbook([
        _mk_pre("claro", "Prezão 5GB (15d)", 15.0, "2026-06-22", 15),
        _mk_pre("claro", "Prezão 12GB (30d)", 30.0, "2026-06-22", 30),
    ], out, datetime(2026, 6, 22, 18))
    wb = openpyxl.load_workbook(out)
    assert "validity_days" in [c.value for c in wb["history"][1]]    # history carries the column
    ws = wb["comparison"]
    pre_claro = ws.cell(row=FIRST, column=10).value     # Pre group cols 8/9/10 = TIM/Vivo/Claro
    assert isinstance(pre_claro, str) and "MINIFS" in pre_claro and '"prepaid"' in pre_claro
    vcol = get_column_letter(COLUMNS.index("validity_days") + 1)
    assert f'history!${vcol}:${vcol},">=28"' in pre_claro    # the 30-day validity filter


def test_heatmap_colorscale_present(tmp_path):
    wb = openpyxl.load_workbook(_multi_day(tmp_path / "m.xlsx"))
    assert len(list(wb["comparison"].conditional_formatting)) >= 1


def test_heatmap_is_green_yellow_2color_no_red(tmp_path):
    """#19: comparison heatmap = a 2-colour green→yellow scale (JPMorgan style), per column, NO red."""
    ws = openpyxl.load_workbook(_multi_day(tmp_path / "m.xlsx"))["comparison"]
    scales = []
    for cf in ws.conditional_formatting:
        for rule in cf.rules:
            if rule.type == "colorScale" and rule.colorScale is not None:
                scales.append([str(c.rgb) for c in rule.colorScale.color])
    assert scales, "no color-scale rules on comparison"
    for colors in scales:
        assert len(colors) == 2                              # 2-colour (not the 3-colour red scale)
    flat = "".join(c for s in scales for c in s)
    assert "A9D08E" in flat and "FFE699" in flat             # soft green (cheaper) + soft yellow (pricier)
    assert "F8696B" not in flat                              # no red


def _color_scales(ws):
    out = []
    for cf in ws.conditional_formatting:
        for rule in cf.rules:
            if rule.type == "colorScale" and rule.colorScale is not None:
                out.append([str(c.rgb) for c in rule.colorScale.color])
    return out


def test_other_sheets_keep_3color_red_scale(tmp_path):
    """#19: ONLY `comparison` switched to green→yellow; latest / Ranking keep the 3-colour RED scale."""
    wb = openpyxl.load_workbook(_multi_day(tmp_path / "m.xlsx"))
    for name in ("latest", "Ranking"):
        scales = _color_scales(wb[name])
        assert scales, f"{name} has no color-scale rule"
        flat = "".join(c for s in scales for c in s)
        assert "F8696B" in flat                             # the red end colour is retained
        assert any(len(s) == 3 for s in scales)             # still a 3-colour scale (not the 2-colour one)


def test_four_line_charts_reference_daily_matrix(tmp_path):
    out = _multi_day(tmp_path / "m.xlsx")
    with zipfile.ZipFile(out) as z:
        xmls = [z.read(n).decode("utf-8")
                for n in z.namelist() if re.match(r"xl/charts/chart\d+\.xml$", n)]
    assert len(xmls) == 4                                       # Control / Post / Pre / Digital
    for xml in xmls:
        assert "'comparison'!$A" in xml                         # X = the Date column
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
    out = _multi_day(tmp_path / "m.xlsx")
    assert "Charts" in openpyxl.load_workbook(out).sheetnames
    with zipfile.ZipFile(out) as z:
        comp_xml = z.read(_sheet_xml_path(z, "comparison")).decode("utf-8")
        charts_xml = z.read(_sheet_xml_path(z, "Charts")).decode("utf-8")
        assert "<drawing" not in comp_xml          # no chart overlay on the table sheet
        assert "<drawing" in charts_xml            # the charts drawing hangs off the Charts sheet


def test_comparison_is_active_sheet(tmp_path):
    """Opening the workbook lands on the clean `comparison` table, not on `history`."""
    wb = openpyxl.load_workbook(_multi_day(tmp_path / "m.xlsx"))
    assert wb.active.title == "comparison"
    selected = [ws.title for ws in wb.worksheets if ws.sheet_view.tabSelected]
    assert selected == ["comparison"]              # the ONLY selected tab → Excel opens on it


def test_comparison_table_only_frozen_b3_and_not_protected(tmp_path):
    """The 'locked' symptom is gone: header frozen at B3, sheet never protected, table starts at the top."""
    ws = openpyxl.load_workbook(_multi_day(tmp_path / "m.xlsx"))["comparison"]
    assert ws.freeze_panes == "B3"
    assert ws.protection.sheet is False
    assert ws.cell(row=1, column=1).value == "Date"            # header at row 1
    assert ws.cell(row=FIRST, column=1).value is not None      # data at row 3


def test_ranking_view_preserved(tmp_path):
    wb = openpyxl.load_workbook(_multi_day(tmp_path / "m.xlsx"))
    assert "Ranking" in wb.sheetnames
    assert wb["Ranking"].cell(row=1, column=1).value.startswith("Ranking")


def test_evolution_dates_helper():
    hist = pd.DataFrame({"snapshot_date": ["2026-06-22", "2026-06-21", "2026-06-22", None]})
    assert evolution_dates(hist) == ["2026-06-21", "2026-06-22"]    # distinct, earliest first


def test_evolution_months_helper():
    # evolution_months is retained as a helper (no longer used by the daily matrix).
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
