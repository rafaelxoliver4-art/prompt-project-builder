"""Canonical data model for a CONVERGENT (combo) offer — a bundle of mobile + fixed broadband
(+ TV / landline) sold as one monthly price.

This is a SEPARATE domain from the mobile `Plan` (models.py): a combo is structurally different
(it bundles several services, carries a fiber speed and a line count, and its "tier" is the bundle,
not a single plan). Keeping it in its own dataclass/sheet means the mobile pipeline — schema,
daily matrix, cached-value bake, charts, alerts — is completely untouched by convergent work.

One `ConvergentOffer` == one combo offer, as seen in one daily snapshot, for one state.
The Excel `convergent_history` columns derive from `CONVERGENT_COLUMNS`. See CONTEXT §14.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Optional

# Column order for the `convergent_history` sheet (and the contract every convergent adapter fills).
CONVERGENT_COLUMNS: list[str] = [
    "snapshot_date",
    "snapshot_ts",
    "carrier",
    "state",
    "offer_name",
    "offer_id",
    "price_brl",
    "price_promo_brl",
    "loyalty_months",
    "payment_method",
    "price_note",
    "services",
    "bundle_type",
    "has_mobile",
    "has_broadband",
    "has_tv",
    "has_landline",
    "broadband_speed_mbps",
    "mobile_gb",
    "mobile_lines",
    "tv_tier",
    "streaming",
    "extra_benefits",
    "data_note",
    "source_url",
    "raw_ref",
]

VALID_CARRIERS = {"vivo", "claro", "tim"}
# Canonical service tokens, in the order they appear in the `services` summary string.
SERVICE_ORDER = ["mobile", "broadband", "tv", "landline"]

# BUNDLE TYPES (#33) — the comparison axis. Carriers price very different things under one "combo"
# banner, so the `convergent_comparison` matrix compares the cheapest offer WITHIN a type rather than
# the cheapest overall (a fiber-only-plus-TV bundle is not a competitor to a fiber+mobile one).
# These three cover every SP offer observed 2026-08-03; `bundle_type_of` falls back to a readable
# label built from the service flags, so a genuinely new shape gets its OWN label instead of being
# silently forced into one of these.
# SPELLING (#34): "Fiber" (US), not "Fibre" — the Bridge's call. `_backfill_bundle_type` MIGRATES rows
# stored under the old "Fibre …" spelling, otherwise past dates would stop matching the matrix's
# criteria and render blank.
BUNDLE_FIBER_MOBILE = "Fiber + Mobile"
BUNDLE_FIBER_TV = "Fiber + TV"
BUNDLE_FIBER_MOBILE_TV = "Fiber + Mobile + TV"
CANONICAL_BUNDLE_TYPES = [BUNDLE_FIBER_MOBILE, BUNDLE_FIBER_TV, BUNDLE_FIBER_MOBILE_TV]

# THE single knob controlling which bundle types the `convergent_comparison` matrix DISPLAYS (#34).
# Every bundle type is still COLLECTED into `convergent_history` — this only scopes the view. Adding
# a type back to the matrix is a one-line change here; nothing else hard-codes a group.
COMPARISON_BUNDLE_TYPES = [BUNDLE_FIBER_MOBILE]

# Legacy → current bundle_type labels, applied when migrating a stored history (#34).
BUNDLE_TYPE_RENAMES = {
    "Fibre + Mobile": BUNDLE_FIBER_MOBILE,
    "Fibre + TV": BUNDLE_FIBER_TV,
    "Fibre + Mobile + TV": BUNDLE_FIBER_MOBILE_TV,
}


def bundle_type_of(has_mobile: bool, has_broadband: bool, has_tv: bool,
                   has_landline: bool = False) -> str | None:
    """The comparison group for a combo, derived from the service flags — no extra scraping (#33).
    None when fewer than two services are set (not a convergent offer at all). Anything outside the
    three canonical shapes returns a descriptive label (e.g. "Mobile + TV") so it keeps its own
    identity rather than distorting an existing group."""
    if sum((bool(has_mobile), bool(has_broadband), bool(has_tv), bool(has_landline))) < 2:
        return None
    if has_broadband and has_mobile and has_tv:
        return BUNDLE_FIBER_MOBILE_TV
    if has_broadband and has_mobile:
        return BUNDLE_FIBER_MOBILE
    if has_broadband and has_tv:
        return BUNDLE_FIBER_TV
    label = {"mobile": "Mobile", "broadband": "Fiber", "tv": "TV", "landline": "Landline"}
    flags = {"mobile": has_mobile, "broadband": has_broadband, "tv": has_tv, "landline": has_landline}
    return " + ".join(label[s] for s in SERVICE_ORDER if flags[s])


def migrate_bundle_type_label(value) -> str | None:
    """Map a stored bundle_type onto the current spelling (#34). Used when the service flags are not
    available to re-derive from — otherwise `_backfill_bundle_type` simply recomputes."""
    s = str(value).strip() if value is not None and str(value).strip() else None
    return BUNDLE_TYPE_RENAMES.get(s, s)


@dataclass
class ConvergentOffer:
    carrier: str
    state: str
    offer_name: str
    # Stable, carrier-native (or deterministically derived) id — unique within a carrier and NEVER
    # price-derived, so a price change is seen as a change to the SAME offer rather than a new one
    # (the same rule as the mobile `plan_id`, CONTEXT §4).
    offer_id: Optional[str] = None
    # Headline monthly price. Standing Bridge rule (CONTEXT §10.5): this is the price WITHOUT a
    # loyalty/fidelity commitment whenever the carrier distinguishes them; a commitment price goes
    # to `price_promo_brl` with `loyalty_months` set.
    price_brl: Optional[float] = None
    price_promo_brl: Optional[float] = None
    loyalty_months: Optional[int] = None
    # Billing rail the headline price assumes: "debit_auto" | "bill" | None. Carriers price combos on a
    # payment ladder (TIM Ultracombo advertises the débito-automático figure, with a higher "fatura"
    # price in the modal) — the same dimension as the mobile `payment_method` (#24), and distinct from
    # loyalty (CONTEXT §10.5): it is context, never a reason to prefer a commitment price.
    payment_method: Optional[str] = None
    price_note: Optional[str] = None
    # What the bundle actually contains.
    has_mobile: bool = False
    has_broadband: bool = False
    has_tv: bool = False
    has_landline: bool = False
    broadband_speed_mbps: Optional[int] = None
    mobile_gb: Optional[float] = None
    mobile_lines: Optional[int] = None
    tv_tier: Optional[str] = None
    streaming: Optional[str] = None
    extra_benefits: Optional[str] = None
    data_note: Optional[str] = None
    source_url: Optional[str] = None
    raw_ref: Optional[str] = None
    # Stamped at write time (kept last so adapters don't have to set them).
    snapshot_date: Optional[str] = None
    snapshot_ts: Optional[str] = None

    @property
    def services(self) -> str:
        """Canonical '+'-joined summary of the bundled services, e.g. "mobile+broadband+tv".
        Derived from the flags so the sheet is readable and groupable without extra parsing."""
        flags = {"mobile": self.has_mobile, "broadband": self.has_broadband,
                 "tv": self.has_tv, "landline": self.has_landline}
        return "+".join(s for s in SERVICE_ORDER if flags[s])

    @property
    def bundle_type(self) -> str | None:
        """The comparison group (see `bundle_type_of`) — derived, never scraped separately (#33)."""
        return bundle_type_of(self.has_mobile, self.has_broadband, self.has_tv, self.has_landline)

    def is_valid(self) -> bool:
        """Minimum bar for a usable row: a real carrier, a state, a name, a price, and — the point
        of a CONVERGENT offer — at least TWO bundled services (a single-service offer is a plain
        plan and belongs in the mobile pipeline, not here)."""
        n_services = sum((self.has_mobile, self.has_broadband, self.has_tv, self.has_landline))
        return bool(
            self.carrier in VALID_CARRIERS
            and self.state
            and self.offer_name
            and self.price_brl is not None
            and n_services >= 2
        )

    def stamp(self, when: datetime) -> "ConvergentOffer":
        self.snapshot_date = when.date().isoformat()
        self.snapshot_ts = when.isoformat(timespec="seconds")
        return self

    def as_row(self) -> dict:
        d = asdict(self)
        d["services"] = self.services          # a property, so not in asdict()
        d["bundle_type"] = self.bundle_type    # ditto (#33)
        return {col: d.get(col) for col in CONVERGENT_COLUMNS}
