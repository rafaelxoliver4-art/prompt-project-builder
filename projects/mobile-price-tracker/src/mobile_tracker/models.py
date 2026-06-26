"""Canonical data model for a scraped mobile plan.

One `Plan` == one plan, as seen in one daily snapshot, for one state.
This dataclass IS the schema; the Excel columns derive from `COLUMNS`.
See CONTEXT.md §6 for the field reference.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from datetime import date, datetime
from typing import Optional

# Column order for the spreadsheet (and the contract every adapter must fill).
COLUMNS: list[str] = [
    "snapshot_date",
    "snapshot_ts",
    "carrier",
    "category",
    "state",
    "plan_name",
    "plan_id",
    "price_brl",
    "price_promo_brl",
    "price_note",
    "data_gb",
    "data_note",
    "validity_days",
    "unlimited_apps",
    "voice",
    "sms",
    "streaming",
    "loyalty_months",
    "extra_benefits",
    "source_url",
    "raw_ref",
]

VALID_CATEGORIES = {"postpaid", "control", "prepaid", "lite", "flex"}
VALID_CARRIERS = {"vivo", "claro", "tim"}


@dataclass
class Plan:
    carrier: str
    category: str
    state: str
    plan_name: str
    # Stable, carrier-native (or deterministically derived) id — unique within a carrier,
    # never price-derived. The canonical key for latest/history/changes (CONTEXT §4 decision).
    plan_id: Optional[str] = None
    price_brl: Optional[float] = None
    price_promo_brl: Optional[float] = None
    price_note: Optional[str] = None
    data_gb: Optional[float] = None
    data_note: Optional[str] = None
    # Plan validity period in days — populated for PREPAID (recarga lasts N days); the Pre matrix
    # column compares the cheapest 30-day plan (validity_days >= 28). Null/blank for monthly plans.
    validity_days: Optional[int] = None
    unlimited_apps: Optional[str] = None
    voice: Optional[str] = None
    sms: Optional[str] = None
    streaming: Optional[str] = None
    loyalty_months: Optional[int] = None
    extra_benefits: Optional[str] = None
    source_url: Optional[str] = None
    raw_ref: Optional[str] = None
    # Stamped at write time (kept last so adapters don't have to set them).
    snapshot_date: Optional[str] = None
    snapshot_ts: Optional[str] = None

    def is_valid(self) -> bool:
        """Minimum bar for a usable row (CONTEXT §6)."""
        return bool(
            self.carrier in VALID_CARRIERS
            and self.category in VALID_CATEGORIES
            and self.state
            and self.plan_name
            and self.price_brl is not None
        )

    def stamp(self, when: datetime) -> "Plan":
        self.snapshot_date = when.date().isoformat()
        self.snapshot_ts = when.isoformat(timespec="seconds")
        return self

    def as_row(self) -> dict:
        d = asdict(self)
        return {col: d.get(col) for col in COLUMNS}
