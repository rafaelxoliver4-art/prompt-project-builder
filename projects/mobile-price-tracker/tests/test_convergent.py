"""Offline tests for the CONVERGENT (combo) domain — CODE TASK #31. No network.

Covers: the TIM Ultracombo parser against a trimmed real capture, the schema's validity rule, the
`convergent_history` sheet (append + same-date idempotency + the critical PRESERVE-on-empty
behaviour), and the guard that keeps any convergent failure from touching the mobile pipeline.
"""
from datetime import datetime
from pathlib import Path

import openpyxl
import pandas as pd
import pytest

from mobile_tracker.adapters.tim_convergent import parse_tim_ultracombo_html
from mobile_tracker.config import Target
from mobile_tracker.convergent import CONVERGENT_COLUMNS, ConvergentOffer
from mobile_tracker.excel_writer import write_workbook
from mobile_tracker.models import Plan

FIXTURE = Path(__file__).parent / "fixtures" / "tim_ultracombo_sp.html"


def _target(state="SP") -> Target:
    return Target(carrier="tim", render="html", category="ultracombo",
                  category_label="TIM Ultracombo (fibra + móvel)", state=state,
                  url="https://www.tim.com.br/sp/internet/tim-ultracombo")


def _offers(state="SP"):
    return parse_tim_ultracombo_html(FIXTURE.read_text(encoding="utf-8"), _target(state), raw_ref="fx")


# ---- the TIM Ultracombo parser -------------------------------------------------------------
def test_parses_the_three_sp_combos():
    """The Ultracombo page (live 2026-08-03) publishes 3 DISCRETE priced tiers — fibre + 1 mobile
    line, no TV/landline. Prices come from field_description, ids from the native Drupal nid."""
    offers = _offers()
    assert len(offers) == 3
    by = {o.offer_id: o for o in offers}
    assert set(by) == {"tim:167761", "tim:167751", "tim:167756"}

    uc7 = by["tim:167761"]
    assert uc7.offer_name == "TIM Ultracombo 7"
    assert uc7.price_brl == 89.99
    assert uc7.broadband_speed_mbps == 500 and uc7.mobile_gb == 65.0 and uc7.mobile_lines == 1
    assert (uc7.has_mobile, uc7.has_broadband, uc7.has_tv, uc7.has_landline) == (True, True, False, False)
    assert uc7.services == "mobile+broadband"
    assert uc7.carrier == "tim" and uc7.state == "SP" and uc7.is_valid()

    assert by["tim:167751"].price_brl == 139.99 and by["tim:167751"].broadband_speed_mbps == 1000
    assert by["tim:167756"].price_brl == 169.99 and by["tim:167756"].mobile_gb == 115.0


def test_ghost_price_fields_never_become_a_promo():
    """REGRESSION GUARD (#31): field_preco_adicional_original ("Por R$129,99") and
    field_preco_adicional_tracejado ("De R$149,99") are byte-identical on ALL three tiers and
    contradict every real price — template leftovers. The MOBILE tim adapter reads
    field_preco_adicional_tracejado as a struck-through regular price; reusing that logic here would
    invent a fake promo on every combo. Nothing may leak into price_brl / price_promo_brl."""
    offers = _offers()
    assert all(o.price_promo_brl is None for o in offers)
    assert all(o.loyalty_months is None for o in offers)           # no fidelity on the headline
    assert {o.price_brl for o in offers} == {89.99, 139.99, 169.99}
    assert not any(o.price_brl in (129.99, 149.99) for o in offers)


def test_headline_is_the_debit_auto_price_with_fatura_in_the_note():
    """The card headline is the débito-automático figure; the modal's higher "por fatura" price is
    context (a PAYMENT-METHOD ladder, not a loyalty one — CONTEXT §10.5)."""
    uc7 = next(o for o in _offers() if o.offer_id == "tim:167761")
    assert uc7.payment_method == "debit_auto"
    assert "débito automático" in uc7.price_note
    assert "99,99" in uc7.price_note and "fatura" in uc7.price_note   # the alternative rail, as context


def test_modal_field_is_read_from_the_bare_string_shape():
    """The live page serves `field_layout_canvas_segundo` as a BARE STRING while every other field
    uses Drupal's [{"value": ...}] wrapper — so this is the branch of `_field` that production
    actually exercises here. The fixture reproduces that shape (it previously used the wrapper,
    which left the real branch untested and would have let a narrowed `_field` silently drop the
    fatura context — caught by the #31 adversarial review)."""
    import json
    import re as _re
    raw = FIXTURE.read_text(encoding="utf-8")
    settings = json.loads(_re.search(r'type="application/json">(.*?)</script>', raw, _re.S).group(1))
    modals = [o["field_layout_canvas_segundo"] for o in settings["ofertas"]]
    assert all(isinstance(m, str) for m in modals), "fixture must model the live BARE-STRING shape"
    assert any("permanência" in m for m in modals)      # the etiqueta sentence is kept verbatim
    # and the parser still reads the payment ladder out of that shape
    assert "fatura" in next(o for o in _offers() if o.offer_id == "tim:167761").price_note


def test_streaming_from_icon_media_and_real_absence():
    """Bundled apps live in field_beneficios_destaque[].name ("Icone Paramount - TIM Ultracombo"),
    NOT in any text/alt. UC7's empty list is a REAL absence, not a parse failure."""
    by = {o.offer_id: o for o in _offers()}
    assert by["tim:167761"].streaming is None                       # genuinely bundles none
    assert by["tim:167751"].streaming == "Paramount+, Deezer"        # "Paramount" normalized to +
    assert by["tim:167756"].streaming == "Paramount+, Deezer"


def test_region_gate_uses_field_regioes_not_langcode():
    """Every oferta carries langcode "rj" / about="/rj/node/…" even though the offers are SP-only —
    those are NOT region signals. Gating is on field_regioes (sp / sp-interior), so an SP target
    keeps all three and a target for another state keeps none."""
    assert len(_offers("SP")) == 3
    assert _offers("RJ") == []          # field_regioes has no rj → nothing, despite langcode == "rj"


def test_missing_or_broken_settings_returns_empty():
    """A restructured/pulled page yields [] (reported by the caller) — never a crash, never invented
    rows."""
    t = _target()
    assert parse_tim_ultracombo_html("<html><body>nothing here</body></html>", t) == []
    assert parse_tim_ultracombo_html(
        '<script data-drupal-selector="drupal-settings-json">{not json</script>', t) == []
    assert parse_tim_ultracombo_html(
        '<script data-drupal-selector="drupal-settings-json">{"ofertas": []}</script>', t) == []


# ---- the schema ----------------------------------------------------------------------------
def test_offer_requires_at_least_two_services():
    """A CONVERGENT offer bundles >= 2 services; a single-service offer is a plain plan and belongs
    in the mobile pipeline, not here."""
    base = dict(carrier="tim", state="SP", offer_name="X", offer_id="tim:1", price_brl=100.0)
    assert ConvergentOffer(**base, has_mobile=True, has_broadband=True).is_valid()
    assert not ConvergentOffer(**base, has_mobile=True).is_valid()               # one service only
    assert not ConvergentOffer(**base).is_valid()                                # none
    assert not ConvergentOffer(carrier="oi", state="SP", offer_name="X", price_brl=1.0,
                               has_mobile=True, has_tv=True).is_valid()          # unknown carrier


def test_services_summary_is_canonically_ordered():
    o = ConvergentOffer(carrier="vivo", state="SP", offer_name="X", price_brl=1.0,
                        has_tv=True, has_mobile=True, has_landline=True, has_broadband=True)
    assert o.services == "mobile+broadband+tv+landline"
    assert o.as_row()["services"] == "mobile+broadband+tv+landline"
    assert list(o.as_row()) == CONVERGENT_COLUMNS                    # row obeys the schema order


# ---- the convergent_history sheet -----------------------------------------------------------
def _plan(name, price, date, carrier="tim"):
    p = Plan(carrier=carrier, category="postpaid", state="SP", plan_name=name,
             plan_id=f"{carrier}:{name}", price_brl=price, source_url="x")
    p.snapshot_date, p.snapshot_ts = date, f"{date}T18:00:00"
    return p


def _co(name, oid, price, date, **kw):
    o = ConvergentOffer(carrier="tim", state="SP", offer_name=name, offer_id=oid, price_brl=price,
                        has_mobile=True, has_broadband=True, source_url="x", **kw)
    o.snapshot_date, o.snapshot_ts = date, f"{date}T18:00:00"
    return o


def test_convergent_sheet_exists_even_with_no_offers(tmp_path):
    out = tmp_path / "w.xlsx"
    res = write_workbook([_plan("A", 100.0, "2026-08-01")], out, datetime(2026, 8, 1, 18))
    with pd.ExcelFile(out) as xl:
        names = list(xl.sheet_names)
    assert "convergent_history" in names                     # schema visible from day one
    assert res["convergent_rows"] == 0
    assert {"history", "latest", "changes", "comparison", "Charts"} <= set(names)   # mobile intact


def test_convergent_history_appends_and_is_idempotent_per_date(tmp_path):
    """Same contract as the mobile history: a re-run REPLACES that snapshot_date's rows; other dates
    accumulate."""
    out = tmp_path / "w.xlsx"
    write_workbook([_plan("A", 100.0, "2026-08-01")], out, datetime(2026, 8, 1, 18),
                   convergent=[_co("UC7", "tim:1", 89.99, "2026-08-01"),
                               _co("UC6", "tim:2", 139.99, "2026-08-01")])
    # re-run of the SAME date with one (re-priced) offer → replaces, does not append
    write_workbook([_plan("A", 100.0, "2026-08-01")], out, datetime(2026, 8, 1, 18),
                   convergent=[_co("UC7", "tim:1", 95.0, "2026-08-01")])
    c = pd.read_excel(out, sheet_name="convergent_history")
    assert len(c) == 1 and float(c.iloc[0]["price_brl"]) == 95.0
    # a NEW date accumulates
    write_workbook([_plan("A", 100.0, "2026-08-02")], out, datetime(2026, 8, 2, 18),
                   convergent=[_co("UC7", "tim:1", 99.0, "2026-08-02")])
    c = pd.read_excel(out, sheet_name="convergent_history")
    assert len(c) == 2
    assert sorted(c["snapshot_date"].astype(str)) == ["2026-08-01", "2026-08-02"]


def test_convergent_history_survives_a_run_that_collected_nothing(tmp_path):
    """THE critical guard: write_workbook REBUILDS the file, so a sheet that isn't re-emitted is
    lost. A day where the convergent scrape failed/was skipped (convergent=None) must keep every
    previously collected convergent row."""
    out = tmp_path / "w.xlsx"
    write_workbook([_plan("A", 100.0, "2026-08-01")], out, datetime(2026, 8, 1, 18),
                   convergent=[_co("UC7", "tim:1", 89.99, "2026-08-01")])
    write_workbook([_plan("A", 100.0, "2026-08-02")], out, datetime(2026, 8, 2, 18), convergent=None)
    c = pd.read_excel(out, sheet_name="convergent_history")
    assert len(c) == 1 and str(c.iloc[0]["snapshot_date"]) == "2026-08-01"


# ---- the guard: convergent can never break mobile -------------------------------------------
class _Boom:
    """A convergent offer whose row-building explodes — stands in for any convergent-side bug."""
    def as_row(self):
        raise RuntimeError("convergent exploded")


def test_convergent_failure_does_not_break_the_mobile_workbook(tmp_path, capsys):
    """A convergent problem inside the WRITE path degrades to 'keep what we had' — the mobile
    sheets, matrix and cached-value bake are still written correctly."""
    out = tmp_path / "w.xlsx"
    write_workbook([_plan("A", 100.0, "2026-08-01")], out, datetime(2026, 8, 1, 18),
                   convergent=[_co("UC7", "tim:1", 89.99, "2026-08-01")])
    res = write_workbook([_plan("A", 110.0, "2026-08-02")], out, datetime(2026, 8, 2, 18),
                         convergent=[_Boom()])
    assert "convergent" in capsys.readouterr().out.lower()          # it complained...
    # ...but the mobile side is complete and correct
    assert res["plans_in_latest"] == 1 and res["snapshots_in_history"] == 2
    hist = pd.read_excel(out, sheet_name="history")
    assert len(hist) == 2
    vals = openpyxl.load_workbook(out, data_only=True)["comparison"]
    assert vals.cell(4, 5).value == 110.0                            # Post TIM baked on the 2nd row
    c = pd.read_excel(out, sheet_name="convergent_history")          # earlier rows preserved
    assert len(c) == 1


def test_demo_mode_skips_the_convergent_pass(monkeypatch, tmp_path):
    """`--demo` is the offline path: it must never reach out for convergent data."""
    from mobile_tracker import main as main_mod

    called = []
    monkeypatch.setattr(main_mod, "write_workbook",
                        lambda plans, path, ts, convergent=None: called.append(convergent) or {
                            "path": str(path), "snapshot_date": "d", "plans_in_latest": len(plans),
                            "snapshots_in_history": 1, "changes": 0,
                            "convergent_rows": 0, "convergent_snapshots": 0})
    rc = main_mod.run(demo=True, only="tim")
    assert rc == 0
    assert called and not called[0]           # convergent list empty — no convergent scrape in demo
