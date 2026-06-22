"""Offline tests for the cross-operator comparison sheet (CONTEXT §7 methodology).

Verifies the pure ranking logic (sorted ascending per carrier, rank-aligned across carriers,
shorter carriers blank at higher ranks, Digital = Vivo lite + Claro flex) and that
write_workbook emits a `comparison` sheet without disturbing the others.
"""
from datetime import datetime

import pandas as pd

from mobile_tracker.excel_writer import build_comparison_data, write_workbook
from mobile_tracker.models import Plan


def _latest_df() -> pd.DataFrame:
    rows = [
        # postpaid: vivo 2, claro 1, tim 3  (different counts → tests rank alignment + blanks)
        dict(carrier="vivo", category="postpaid", plan_name="V Pós A", price_brl=180.0, data_gb=60.0, price_promo_brl=None),
        dict(carrier="vivo", category="postpaid", plan_name="V Pós B", price_brl=150.0, data_gb=60.0, price_promo_brl=None),
        dict(carrier="claro", category="postpaid", plan_name="C Pós", price_brl=124.9, data_gb=60.0, price_promo_brl=None),
        dict(carrier="tim", category="postpaid", plan_name="T Black 1", price_brl=129.99, data_gb=70.0, price_promo_brl=None),
        dict(carrier="tim", category="postpaid", plan_name="T Black 2", price_brl=119.99, data_gb=67.0, price_promo_brl=None),
        dict(carrier="tim", category="postpaid", plan_name="T Black 3", price_brl=164.99, data_gb=107.0, price_promo_brl=None),
        # control: claro 1 (with a promo)
        dict(carrier="claro", category="control", plan_name="C Ctrl", price_brl=59.9, data_gb=25.0, price_promo_brl=54.9),
        # digital: vivo lite + claro flex, tim none
        dict(carrier="vivo", category="lite", plan_name="Easy Lite", price_brl=30.0, data_gb=30.0, price_promo_brl=None),
        dict(carrier="claro", category="flex", plan_name="Flex 15", price_brl=44.9, data_gb=15.0, price_promo_brl=None),
        # prepaid: vivo 1
        dict(carrier="vivo", category="prepaid", plan_name="V Pré", price_brl=17.0, data_gb=4.0, price_promo_brl=None),
    ]
    return pd.DataFrame(rows)


def _groups():
    return {g["title"]: g for g in build_comparison_data(_latest_df())}


def test_ranking_ascending_per_carrier_and_aligned():
    pp = _groups()["Pure Postpaid"]
    vivo = [r[0] for r in pp["per_carrier"]["vivo"]]
    claro = [r[0] for r in pp["per_carrier"]["claro"]]
    tim = [r[0] for r in pp["per_carrier"]["tim"]]
    assert vivo == [150.0, 180.0]               # ascending
    assert tim == [119.99, 129.99, 164.99]       # ascending
    assert claro == [124.9]
    # rank-1 row = each carrier's cheapest postpaid
    assert (vivo[0], claro[0], tim[0]) == (150.0, 124.9, 119.99)
    assert pp["max_rank"] == 3                    # tim has the most
    assert len(claro) == 1                        # claro blank at ranks 2 & 3


def test_digital_pulls_lite_and_flex_tim_empty():
    dig = _groups()["Digital"]
    assert [r[1] for r in dig["per_carrier"]["vivo"]] == ["Easy Lite"]   # vivo lite
    assert [r[1] for r in dig["per_carrier"]["claro"]] == ["Flex 15"]    # claro flex
    assert dig["per_carrier"]["tim"] == []                               # TIM has no digital line


def test_prepaid_group_carries_unit_caveat():
    note = _groups()["Prepaid"]["note"] or ""
    assert "daily" in note.lower() or "dia" in note.lower()


def test_all_four_groups_present_in_order():
    titles = [g["title"] for g in build_comparison_data(_latest_df())]
    assert titles == ["Pure Postpaid", "Control / Hybrid", "Prepaid", "Digital"]


def test_write_workbook_adds_comparison_sheet_without_disturbing_others(tmp_path):
    out = tmp_path / "p.xlsx"
    plans = []
    for row in _latest_df().to_dict("records"):
        p = Plan(carrier=row["carrier"], category=row["category"], state="SP",
                 plan_name=row["plan_name"], plan_id=f'{row["carrier"]}:{row["plan_name"]}',
                 price_brl=row["price_brl"], data_gb=row["data_gb"],
                 price_promo_brl=row["price_promo_brl"], source_url="http://x")
        p.snapshot_date = "2026-06-22"
        p.snapshot_ts = "2026-06-22T23:00:00"
        plans.append(p)
    write_workbook(plans, out, datetime(2026, 6, 22, 23))
    xls = pd.ExcelFile(out)
    assert "comparison" in xls.sheet_names
    assert {"history", "latest", "changes", "summary"}.issubset(set(xls.sheet_names))
