"""Offline tests for the per-operator sheets (one tab per carrier).

Verifies the pure grouping/sorting (each carrier gets only its plans, grouped by category in order,
price-sorted within a block, the readable column set, promos shown) and that write_workbook emits
one sheet per present carrier without disturbing the others (and none for an absent carrier).
"""
from datetime import datetime

import pandas as pd

from mobile_tracker.excel_writer import build_operator_sheets, write_workbook, OPERATOR_COLUMNS
from mobile_tracker.models import Plan


def _latest_df() -> pd.DataFrame:
    rows = [
        dict(carrier="vivo", category="postpaid", plan_name="V Pós B", price_brl=150.0, price_promo_brl=None,
             data_gb=60.0, data_note=None, voice="ligações ilimitadas", unlimited_apps="WhatsApp",
             streaming="Netflix", extra_benefits="5G", price_note=None),
        dict(carrier="vivo", category="postpaid", plan_name="V Pós A", price_brl=180.0, price_promo_brl=None,
             data_gb=60.0, data_note=None, voice=None, unlimited_apps=None, streaming=None,
             extra_benefits=None, price_note=None),
        dict(carrier="vivo", category="lite", plan_name="Easy Lite", price_brl=30.0, price_promo_brl=None,
             data_gb=30.0, data_note=None, voice=None, unlimited_apps=None, streaming=None,
             extra_benefits=None, price_note=None),
        dict(carrier="claro", category="control", plan_name="C Ctrl", price_brl=59.9, price_promo_brl=54.9,
             data_gb=25.0, data_note="20+5 bônus", voice=None, unlimited_apps="WhatsApp", streaming=None,
             extra_benefits=None, price_note="De R$59,90"),
    ]
    return pd.DataFrame(rows)


def _by_carrier():
    return {op["carrier"]: op for op in build_operator_sheets(_latest_df())}


def test_one_sheet_per_present_carrier_tim_absent():
    displays = [op["display"] for op in build_operator_sheets(_latest_df())]
    assert displays == ["Vivo", "Claro"]      # TIM not in latest → no sheet; known carriers first


def test_blocks_grouped_in_order_and_price_sorted():
    vivo = _by_carrier()["vivo"]
    assert [b["label"] for b in vivo["blocks"]] == ["Postpaid", "Digital"]   # no control/prepaid for vivo here
    pp = next(b for b in vivo["blocks"] if b["label"] == "Postpaid")
    assert [r[0] for r in pp["rows"]] == ["V Pós B", "V Pós A"]   # ascending by price
    assert [r[1] for r in pp["rows"]] == [150.0, 180.0]


def test_only_that_carriers_plans():
    claro = _by_carrier()["claro"]
    names = [r[0] for blk in claro["blocks"] for r in blk["rows"]]
    assert names == ["C Ctrl"]               # no vivo plans leaked in


def test_columns_and_promo_and_data():
    claro = _by_carrier()["claro"]
    ctrl = claro["blocks"][0]
    assert ctrl["label"] == "Control"
    row = ctrl["rows"][0]
    assert len(row) == len(OPERATOR_COLUMNS) == 8
    # Plan | Price | Promo | Data | Voice | Unlimited apps | Streaming | Notes
    assert row[0] == "C Ctrl"
    assert row[1] == 59.9 and row[2] == 54.9          # price + promo
    assert "25 GB" in row[3] and "bônus" in row[3]    # data with data_note
    assert row[5] == "WhatsApp"                       # unlimited apps
    assert "De R$59,90" in (row[7] or "")             # notes carries price_note


def test_prepaid_row_shows_validity_in_data_cell():
    # #18: a prepaid plan's validity_days is shown in the operator-sheet Data cell (e.g. "12 GB · 30d").
    df = pd.DataFrame([dict(
        carrier="claro", category="prepaid", plan_name="Prezão 12GB (30 dias)", price_brl=30.0,
        price_promo_brl=None, data_gb=12.0, data_note=None, validity_days=30, voice=None,
        unlimited_apps=None, streaming=None, extra_benefits=None, price_note=None)])
    op = {o["carrier"]: o for o in build_operator_sheets(df)}["claro"]
    rows = [r for blk in op["blocks"] for r in blk["rows"]]
    assert len(rows) == 1
    data_cell = rows[0][3]                              # the Data column
    assert "12 GB" in data_cell and "30d" in data_cell


def test_write_workbook_emits_carrier_sheets_only_for_present(tmp_path):
    out = tmp_path / "p.xlsx"
    plans = []
    for rec in _latest_df().to_dict("records"):
        p = Plan(carrier=rec["carrier"], category=rec["category"], state="SP",
                 plan_name=rec["plan_name"], plan_id=f'{rec["carrier"]}:{rec["plan_name"]}',
                 price_brl=rec["price_brl"], price_promo_brl=rec["price_promo_brl"],
                 data_gb=rec["data_gb"], data_note=rec["data_note"], voice=rec["voice"],
                 unlimited_apps=rec["unlimited_apps"], streaming=rec["streaming"],
                 extra_benefits=rec["extra_benefits"], price_note=rec["price_note"], source_url="http://x")
        p.snapshot_date = "2026-06-22"
        p.snapshot_ts = "2026-06-22T23:00:00"
        plans.append(p)
    write_workbook(plans, out, datetime(2026, 6, 22, 23))
    names = set(pd.ExcelFile(out).sheet_names)
    assert {"Vivo", "Claro"}.issubset(names)
    assert "TIM" not in names                          # absent carrier → no sheet
    assert {"history", "latest", "changes", "summary", "comparison"}.issubset(names)
