"""Offline tests for the phase-2 convergent adapters — CODE TASK #32. No network.

Vivo Total (Playwright-rendered DOM) and Claro Multi (Next.js grid + catalog API) parsed from
trimmed but SHAPE-FAITHFUL captures of the real SP pages, plus the three-carrier sheet behaviour
and the guarantee that one convergent source failing never stops the others or the mobile write.
"""
import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from mobile_tracker.adapters.claro_convergent import (build_claro_offers, catalog_url,
                                                      next_data, parse_claro_multi_grid)
from mobile_tracker.adapters.vivo_convergent import page_is_sao_paulo, parse_vivo_total_html
from mobile_tracker.config import Target
from mobile_tracker.convergent import ConvergentOffer
from mobile_tracker.excel_writer import write_workbook
from mobile_tracker.models import Plan

FIX = Path(__file__).parent / "fixtures"
VIVO = FIX / "vivo_total_sp.html"
CLARO_NEXT = FIX / "claro_multi_sp_next.json"
CLARO_CAT = FIX / "claro_multi_sp_catalog.json"


def _vivo_target():
    return Target(carrier="vivo", render="aem", category="total", category_label="Vivo Total",
                  state="SP", url="https://vivo.com.br/para-voce/produtos-e-servicos/combos/vivo-total")


def _claro_target():
    return Target(carrier="claro", render="nextjs", category="multi", category_label="Claro Multi",
                  state="SP", url="https://www.claro.com.br/multi")


def _vivo_offers():
    return parse_vivo_total_html(VIVO.read_text(encoding="utf-8"), _vivo_target(), raw_ref="fx")


def _claro_offers():
    grid = parse_claro_multi_grid(json.loads(CLARO_NEXT.read_text(encoding="utf-8")))
    cat = json.loads(CLARO_CAT.read_text(encoding="utf-8"))
    return grid, build_claro_offers(grid, cat, _claro_target(), raw_ref="fx")


# ---- Vivo Total ------------------------------------------------------------------------------
def test_vivo_parses_combos_with_full_fields():
    offers = {o.offer_name: o for o in _vivo_offers()}
    assert len(offers) == 4
    pro = offers["Vivo Total Pro"]
    assert pro.price_brl == 160.0 and pro.broadband_speed_mbps == 500
    assert pro.mobile_gb == 60.0 and pro.mobile_lines == 1
    assert pro.services == "mobile+broadband" and not pro.has_tv
    assert pro.carrier == "vivo" and pro.state == "SP" and pro.is_valid()

    giga = offers["Vivo Total V 1 Giga"]        # the R$1,200 tier is REAL — never filter it as an outlier
    assert giga.price_brl == 1200.0 and giga.broadband_speed_mbps == 1000
    assert giga.mobile_gb == 600.0 and giga.mobile_lines == 11        # 1 base + "10 linhas adicionais"
    assert giga.has_tv and "Vivo TV Completo" in giga.tv_tier
    assert giga.services == "mobile+broadband+tv"


def test_vivo_offer_id_survives_the_viv_code_collision():
    """The VIV code is NOT unique: Ultra (R$170) and Ultra + TV online (R$190) share
    VIV202604028853. offer_id = code + the card's own sorted productsIds, so the two stay distinct —
    and neither id contains a price."""
    offers = {o.offer_name: o for o in _vivo_offers()}
    a, b = offers["Vivo Total Ultra"], offers["Vivo Total Ultra + TV online"]
    assert "VIV202604028853" in a.offer_id and "VIV202604028853" in b.offer_id   # same carrier code
    assert a.offer_id != b.offer_id                                              # ...distinct ids
    assert "336" in b.offer_id and "336" not in a.offer_id       # the TV product token disambiguates
    for o in _vivo_offers():                                     # never price-derived
        assert str(int(o.price_brl)) not in o.offer_id.split(":")[1].split("-")[0]
    assert len({o.offer_id for o in _vivo_offers()}) == 4


def test_vivo_hidden_price_falls_back_to_the_base_attribute():
    """The paid apps add-on can v-show the price text away (or show base+add-on). The offer must NOT
    be dropped: fall back to data-original-price, and say so when the displayed value differed."""
    html = ('<div class="unique-card"><div class="unique-card__plan">Vivo Total X</div>'
            '<div class="unique-card__header-benefit">700 Mega de Vivo Fibra</div>'
            '<div class="unique-card__benefit">70 GB de Vivo Pós</div>'
            '<span class="total-card-price-value" data-original-price="170"></span></div>'
            # add-on selected: the DISPLAYED number is base+add-on; the offer's own price is the base
            '<div class="unique-card"><div class="unique-card__plan">Vivo Total Y</div>'
            '<div class="unique-card__header-benefit">500 Mega de Vivo Fibra</div>'
            '<div class="unique-card__benefit">60 GB de Vivo Pós</div>'
            '<span class="total-card-price-value" data-original-price="160">215</span></div>')
    by = {o.offer_name: o for o in parse_vivo_total_html(html, _vivo_target())}
    assert by["Vivo Total X"].price_brl == 170.0                  # empty text → attribute, not dropped
    assert by["Vivo Total Y"].price_brl == 160.0                  # base price, NOT the 215 shown
    assert "pacote de apps" in by["Vivo Total Y"].price_note


def test_vivo_struck_through_price_becomes_the_promo():
    """Session-dependent variants: when a card renders a struck-through regular price, the regular is
    the headline and the displayed one is the promo (mirrors the mobile rule)."""
    html = ('<div class="unique-card"><div class="unique-card__plan">Vivo Total Essencial</div>'
            '<div class="unique-card__header-benefit">500 Mega de Vivo Fibra</div>'
            '<div class="unique-card__benefit">50 GB de Vivo Pós</div>'
            '<div class="unique-card__price-old">R$ 160</div>'
            '<span class="total-card-price-value" data-original-price="130">130</span></div>')
    o = parse_vivo_total_html(html, _vivo_target())[0]
    assert o.price_brl == 160.0 and o.price_promo_brl == 130.0
    assert "desconto" in o.price_note


@pytest.mark.parametrize("raw,expected", [
    ("1.200,00", 1200.00),      # pt-BR: dot = thousands, comma = decimal
    ("160,00", 160.00),
    ("160.00", 160.00),         # dot-DECIMAL — the #35 blocker: this used to parse as 16000 (100x)
    ("1,200.00", 1200.00),      # en-US: comma = thousands, dot = decimal
    ("89,99", 89.99),
    ("170", 170.0),
    ("1.200", 1200.0),          # a lone separator + exactly 3 digits is a thousands group
    ("R$ 1.329,05", 1329.05),
    ("", None),
    ("sem preço", None),
])
def test_price_from_handles_both_brl_conventions(raw, expected):
    """#36 (P0): `_price_from` decides the separator roles BY PATTERN. The old version stripped every
    '.' as a thousands separator, so a dot-decimal `data-original-price="160.00"` became R$16 000 —
    a silent 100x error feeding the convergent matrix."""
    from mobile_tracker.adapters.vivo_convergent import _price_from
    assert _price_from(raw) == expected


def test_vivo_combo_prices_unchanged_after_the_parser_fix():
    """The real captured grid must parse identically to before the fix (no 100x, no regression)."""
    prices = sorted(o.price_brl for o in _vivo_offers())
    assert prices == [160.0, 170.0, 190.0, 1200.0]        # the 4 cards kept in the fixture
    assert all(p < 2000 for p in prices)                   # nothing inflated by a factor of 100


def test_vivo_sp_label_detection():
    assert page_is_sao_paulo(VIVO.read_text(encoding="utf-8")) is True
    assert page_is_sao_paulo("<div>no location bar</div>") is False
    assert page_is_sao_paulo('<div class="new-compass-top-bar__text-container">'
                             "<span>Ofertas para</span><span>Rio de Janeiro (RJ)</span></div>") is False


# ---- Claro Multi -----------------------------------------------------------------------------
def test_claro_grid_found_by_component_name_not_index():
    """The page also carries a card_360 of a DIFFERENT product line, and component order is not
    stable — the grid must be located by component name."""
    grid = parse_claro_multi_grid(json.loads(CLARO_NEXT.read_text(encoding="utf-8")))
    assert len(grid) == 4 and all(g["uid"] for g in grid)
    assert {g["tab"] for g in grid} == {"Fibra + Móvel", "Fibra + TV"}
    assert parse_claro_multi_grid({}) == []                     # restructured page → [], no crash
    assert parse_claro_multi_grid(next_data("<html><body>no next data</body></html>")) == []


def test_claro_excludes_ghost_offers():
    """The CMS lists combos SP does not sell; their catalog entry is {"notFound": true}. Ghosts are
    excluded (they have no price at all) — the rendered/priced set is the truth."""
    grid, offers = _claro_offers()
    assert len(grid) == 4 and len(offers) == 3                    # exactly one ghost dropped
    ghost = "claro:d41393cf-82b4-4331-bce1-e08482161aa6"
    assert ghost not in {o.offer_id for o in offers}
    assert all(o.is_valid() for o in offers)


def test_claro_price_sums_centavos_and_handles_absent_precoCombo():
    """Price = Σ(precoCombo if the KEY is present else preco), integer centavos → BRL. On Fibra+TV
    cards precoCombo is ABSENT (not null) on internet — a falsy-default read would drop the whole
    fibre component and under-price the combo by R$99,90."""
    _, offers = _claro_offers()
    by = {o.offer_id.split(":")[1][:8]: o for o in offers}
    assert by["a866ea9a"].price_brl == 129.80        # 7990 (combo) + 4990 (combo)
    assert by["d47e2a3b"].price_brl == 299.90        # 11990 + 18000
    fibra_tv = by["545261b1"]
    assert fibra_tv.price_brl == 219.80              # 9990 (preco: precoCombo ABSENT) + 11990 (combo)
    assert fibra_tv.has_broadband and fibra_tv.has_tv and not fibra_tv.has_mobile


def test_claro_fields_come_from_the_catalog_not_the_stale_cms_names():
    _, offers = _claro_offers()
    by = {o.offer_id.split(":")[1][:8]: o for o in offers}
    entry = by["a866ea9a"]
    assert entry.broadband_speed_mbps == 350                 # recursosDescritivos 602 "350 Mbps"
    assert entry.mobile_gb == 40.0                           # catalog says 40GB (CMS text says "41GB")
    assert entry.mobile_lines == 1
    assert entry.payment_method == "debit_auto"              # acrescimoNaoDCC = 500 on this tier
    assert "sem débito automático" in entry.price_note
    assert by["d47e2a3b"].mobile_lines == 2                  # 1 base + "1 linha adicional inclusa"
    assert by["d47e2a3b"].payment_method is None             # no surcharge on that tier


def test_claro_catalog_url_pins_sao_paulo_and_batches_uuids():
    url = catalog_url(["u1", "u2", "u3"])
    assert "state=SP" in url and "city=sao_paulo" in url     # SP is an explicit input, not geolocated
    assert "uuids=u1,u2,u3" in url                           # ONE call for every card (politeness)
    assert url.count("http") == 1


# ---- three carriers in the sheet + the guard --------------------------------------------------
def _plan(name, price, date):
    p = Plan(carrier="tim", category="postpaid", state="SP", plan_name=name, plan_id=f"tim:{name}",
             price_brl=price, source_url="x")
    p.snapshot_date, p.snapshot_ts = date, f"{date}T18:00:00"
    return p


def _co(carrier, name, oid, price, date):
    o = ConvergentOffer(carrier=carrier, state="SP", offer_name=name, offer_id=oid, price_brl=price,
                        has_mobile=True, has_broadband=True, source_url="x")
    o.snapshot_date, o.snapshot_ts = date, f"{date}T18:00:00"
    return o


def test_three_carriers_append_and_same_date_idempotency(tmp_path):
    out = tmp_path / "w.xlsx"
    day1 = [_co("tim", "UC7", "tim:1", 89.99, "2026-08-03"),
            _co("vivo", "Total Pro", "vivo:VIV1-2", 160.0, "2026-08-03"),
            _co("claro", "Multi 350", "claro:uid1", 129.80, "2026-08-03")]
    write_workbook([_plan("A", 100.0, "2026-08-03")], out, datetime(2026, 8, 3, 18), convergent=day1)
    c = pd.read_excel(out, sheet_name="convergent_history")
    assert set(c["carrier"]) == {"tim", "vivo", "claro"} and len(c) == 3

    # same date re-run with a re-priced set → REPLACES that date (never duplicates a carrier)
    day1b = [_co("tim", "UC7", "tim:1", 94.99, "2026-08-03"),
             _co("vivo", "Total Pro", "vivo:VIV1-2", 165.0, "2026-08-03"),
             _co("claro", "Multi 350", "claro:uid1", 129.80, "2026-08-03")]
    write_workbook([_plan("A", 100.0, "2026-08-03")], out, datetime(2026, 8, 3, 18), convergent=day1b)
    c = pd.read_excel(out, sheet_name="convergent_history")
    assert len(c) == 3
    assert float(c[c.carrier == "tim"].iloc[0]["price_brl"]) == 94.99

    # next day accumulates all three again
    write_workbook([_plan("A", 100.0, "2026-08-04")], out, datetime(2026, 8, 4, 18),
                   convergent=[_co(k, n, i, p, "2026-08-04") for k, n, i, p in
                               (("tim", "UC7", "tim:1", 89.99), ("vivo", "Total Pro", "vivo:VIV1-2", 160.0),
                                ("claro", "Multi 350", "claro:uid1", 139.80))])
    c = pd.read_excel(out, sheet_name="convergent_history")
    assert len(c) == 6 and c["snapshot_date"].astype(str).nunique() == 2


def test_one_convergent_source_failing_does_not_stop_the_others_or_mobile(monkeypatch, tmp_path):
    """The per-target guard in main.run(): a raising adapter is logged and skipped while the other
    carriers still collect and the mobile workbook is still written."""
    from mobile_tracker import main as main_mod

    class _Boom:
        def __init__(self, settings): pass
        def fetch(self, target): raise RuntimeError("vivo render exploded")

    class _Ok:
        def __init__(self, settings): pass
        def fetch(self, target):
            return [ConvergentOffer(carrier=target.carrier, state=target.state, offer_name="Combo",
                                    offer_id=f"{target.carrier}:1", price_brl=99.0,
                                    has_mobile=True, has_broadband=True)]

    # This test is about the CONVERGENT guard only, so neutralise the run-blocking output guard —
    # otherwise a stub carrier count outside its band aborts the run for an unrelated reason.
    # `raising=False`: the attribute may not exist in every checkout.
    class _NoSanity:
        @staticmethod
        def check_sanity(*a, **k):
            return []
    monkeypatch.setattr(main_mod, "alerts_mod", _NoSanity, raising=False)
    # ⚠️ REGRESSION GUARD (#37): stub ALL THREE carriers and do NOT restrict with `only`. The earlier
    # version stubbed just `tim`, so vivo/claro collected 0 plans — which the zero-guard in the THEN
    # COMMITTED main.py turned into exit 3 while this test asserted 0. It passed locally (where a
    # different output guard was in place) and FAILED IN CI, and because the workflow runs the tests
    # BEFORE the scrape, that failure cost the 2026-08-04 snapshot entirely. Keep this guard-agnostic:
    # give every carrier plans so no output guard can fire for an unrelated reason.
    monkeypatch.setattr(main_mod, "ADAPTERS",
                        {"tim": _MobileStub, "vivo": _MobileStub, "claro": _MobileStub})
    monkeypatch.setitem(__import__("mobile_tracker.adapters", fromlist=["x"]).CONVERGENT_ADAPTERS,
                        "vivo_total", _Boom)
    monkeypatch.setitem(__import__("mobile_tracker.adapters", fromlist=["x"]).CONVERGENT_ADAPTERS,
                        "tim_ultracombo", _Ok)
    monkeypatch.setitem(__import__("mobile_tracker.adapters", fromlist=["x"]).CONVERGENT_ADAPTERS,
                        "claro_multi", _Ok)
    captured = {}
    monkeypatch.setattr(main_mod, "write_workbook",
                        lambda plans, path, ts, convergent=None: captured.update(
                            plans=plans, convergent=convergent) or {
                            "path": str(path), "snapshot_date": "d", "plans_in_latest": len(plans),
                            "snapshots_in_history": 1, "changes": 0,
                            "convergent_rows": len(convergent or []), "convergent_snapshots": 1})
    rc = main_mod.run(demo=False)                           # every carrier stubbed — no `only`
    assert rc == 0                                          # the run SUCCEEDS despite vivo blowing up
    assert captured["plans"], "mobile plans must still be written"
    carriers = {o.carrier for o in captured["convergent"]}
    assert "vivo" not in carriers                           # the failed source contributed nothing...
    assert {"tim", "claro"} <= carriers                     # ...and the others still collected


class _MobileStub:
    """A network-free mobile adapter so the guard test never touches a carrier site. Returns rows for
    WHICHEVER carrier it is registered under, so no carrier ends the run at zero plans (#37)."""
    def __init__(self, settings): pass

    def fetch(self, target):
        return [Plan(carrier=target.carrier, category=target.category, state=target.state,
                     plan_name=f"Stub {target.carrier} {target.category}",
                     plan_id=f"{target.carrier}:stub-{target.category}", price_brl=100.0,
                     source_url="x")]

    def demo_plans(self, target):
        return self.fetch(target)
