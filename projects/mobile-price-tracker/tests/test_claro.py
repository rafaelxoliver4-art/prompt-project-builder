"""Offline unit tests for the Claro adapter's pure parser (no network).

Runs `parse_next_data` against a trimmed real `__NEXT_DATA__` capture saved in
tests/fixtures/claro_pos_sp.json (Claro SP postpaid page, 2026-06-19).
"""
import json
from pathlib import Path

from mobile_tracker.config import Target
from mobile_tracker.adapters.claro import parse_next_data, _parse_brl

FIXTURE = Path(__file__).parent / "fixtures" / "claro_pos_sp.json"


def _target() -> Target:
    return Target(carrier="claro", render="nextjs", category="postpaid",
                  category_label="Pós", state="SP",
                  url="https://www.claro.com.br/celular/pos")


def _plans():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return parse_next_data(data, _target(), raw_ref="fixture")


def test_extracts_valid_plans():
    plans = _plans()
    assert len(plans) >= 4
    for p in plans:
        assert p.is_valid()
        assert p.carrier == "claro"
        assert p.category == "postpaid"
        assert p.state == "SP"
        assert p.price_brl and p.price_brl > 0
        assert p.plan_name
        assert p.source_url.startswith("https://www.claro.com.br")
        assert p.raw_ref == "fixture"


def test_known_plan_fields():
    plans = _plans()
    by_name = {p.plan_name: p for p in plans}
    p100 = next((p for n, p in by_name.items() if "100GB" in n), None)
    assert p100 is not None, f"no 100GB plan in {list(by_name)}"
    assert p100.data_gb == 100.0
    assert p100.price_brl == 179.90
    assert p100.unlimited_apps == "WhatsApp"


def test_generic_title_falls_back_to_slug_name():
    # cards whose modal title is the generic "Mais detalhes" must still be named (e.g. "Pós 60GB").
    names = {p.plan_name for p in _plans()}
    assert not any(n.lower().startswith("mais detalhes") for n in names)
    assert any("60GB" in n for n in names)


def test_no_duplicate_name_price():
    keys = [(p.plan_name, p.price_brl) for p in _plans()]
    assert len(keys) == len(set(keys))  # promo duplicate cards collapsed


def test_brl_parsing():
    assert _parse_brl("R$ 124,90") == 124.90
    assert _parse_brl("R$ 1.234,56") == 1234.56
    assert _parse_brl("54,90") == 54.90          # control/flex store the price without "R$"
    assert _parse_brl("sem preço") is None
    assert _parse_brl(None) is None


def test_promo_pricing_and_slug_name():
    # control/flex layout: bare effective price + struck-through regular in `prefix`,
    # generic modal title → name derived from the accordion slug.
    data = {"props": {"pageProps": {"dynamicComponents": {"body": [
        {"component": "card_360", "data": {"data": [
            {"detail": [{"label": "WhatsApp ilimitado"}],
             "actions": [{
                 "price": {"prefix": "~De R$ 59,90~ Por:", "price": "54,90"},
                 "link": [{"modalContent": {
                     "title": "Informações sobre o plano",
                     "drawer_select_list": [{"accordion_list_relations": {
                         "name": "lista-accordion-card-360-plano-controle-25gb-mais-detalhes"}}],
                 }}],
             }]},
        ]}},
    ]}}}}
    t = Target(carrier="claro", render="nextjs", category="control",
               category_label="Controle", state="SP",
               url="https://www.claro.com.br/celular/controle")
    plans = parse_next_data(data, t, raw_ref="x")
    assert len(plans) == 1
    p = plans[0]
    assert p.plan_name == "Controle 25GB"   # derived from slug, not the generic title
    assert p.price_brl == 59.90             # struck-through regular
    assert p.price_promo_brl == 54.90       # effective/discounted
    assert p.data_gb == 25.0
    assert p.category == "control"
