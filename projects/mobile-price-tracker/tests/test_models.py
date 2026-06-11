from datetime import datetime

from mobile_tracker.models import COLUMNS, Plan


def test_row_has_all_columns_in_order():
    p = Plan(carrier="vivo", category="postpaid", state="SP",
             plan_name="X", price_brl=100.0)
    row = p.as_row()
    assert list(row.keys()) == COLUMNS


def test_validity_requires_core_fields_and_price():
    assert Plan("vivo", "postpaid", "SP", "X", price_brl=10).is_valid()
    assert not Plan("vivo", "postpaid", "SP", "X").is_valid()          # no price
    assert not Plan("nope", "postpaid", "SP", "X", price_brl=10).is_valid()  # bad carrier
    assert not Plan("vivo", "weird", "SP", "X", price_brl=10).is_valid()     # bad category


def test_stamp_sets_date_and_ts():
    p = Plan("tim", "prepaid", "SP", "X", price_brl=30).stamp(datetime(2026, 6, 11, 23, 0, 0))
    assert p.snapshot_date == "2026-06-11"
    assert p.snapshot_ts.startswith("2026-06-11T23:00")
