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
    assert p.plan_id == "claro:plano-controle-25gb"   # native slug


def test_plan_id_native_slug_and_unique():
    plans = _plans()
    assert all(p.plan_id and p.plan_id.startswith("claro:") for p in plans)
    ids = [p.plan_id for p in plans]
    assert len(ids) == len(set(ids))                  # never price-derived; unique
    assert any("plano-pos-60gb" in p.plan_id for p in plans)


def test_prepaid_30day_plan_with_validity():
    # #18: Claro prepaid now captures the REAL 30-day Prezão plan + validity_days (NOT the "R$1 por
    # dia" headline the old parser grabbed). Tiers come from the page's rich text ("R$ 30/30 dias – 12GB").
    import json
    from mobile_tracker.adapters.claro import parse_claro_prepaid
    fixture = Path(__file__).parent / "fixtures" / "claro_prepaid_sp.json"
    data = json.loads(fixture.read_text(encoding="utf-8"))
    t = Target(carrier="claro", render="nextjs", category="prepaid", category_label="Prezão (Pré)",
               state="SP", url="https://www.claro.com.br/celular/planos-pre/prezao")
    plans = parse_claro_prepaid(data, t, raw_ref="fx")
    assert len(plans) >= 1
    # every prepaid plan carries a validity and a real recarga price (no R$1/dia headline anymore)
    assert all(p.validity_days and p.price_brl and p.price_brl >= 15 for p in plans)
    assert all(p.category == "prepaid" and p.plan_id.startswith("claro:") for p in plans)
    # the real 30-day plan is present: R$30 / 30 dias / 12GB; plan_id is validity+gb (never price-derived)
    thirty = [p for p in plans if p.validity_days >= 28]
    assert thirty, f"no 30-day plan in {[(p.plan_id, p.validity_days) for p in plans]}"
    cheapest = min(thirty, key=lambda p: p.price_brl)
    assert cheapest.price_brl == 30.0           # was R$1 before #18
    assert cheapest.data_gb == 12.0
    assert cheapest.validity_days == 30
    assert cheapest.plan_id == "claro:prezao-30d-12gb"


def test_prepaid_collision_keeps_cheaper():
    # #18: two tiers with the SAME (validity, gb) — e.g. R$35 sem anúncio vs R$30 com anúncio, both
    # 30d/12GB — collapse to one plan (id is validity+gb, not price), keeping the CHEAPER recarga.
    from mobile_tracker.adapters.claro import parse_claro_prepaid
    data = {"rich": "R$ 35/30 dias – 12GB sem anúncio • R$ 30/30 dias – 12GB com anúncio"}
    t = Target(carrier="claro", render="nextjs", category="prepaid", category_label="Prezão (Pré)",
               state="SP", url="https://www.claro.com.br/celular/planos-pre/prezao")
    plans = parse_claro_prepaid(data, t)
    pset = [p for p in plans if p.validity_days == 30 and int(p.data_gb) == 12]
    assert len(pset) == 1                        # collapsed by (validity, gb)
    assert pset[0].price_brl == 30.0             # the cheaper recarga won
    assert pset[0].plan_id == "claro:prezao-30d-12gb"


def test_postpaid_has_no_validity():
    # regression: validity is PREPAID-only — postpaid plans (parse_next_data) keep validity_days None.
    assert all(p.validity_days is None for p in _plans())


def test_cross_sell_card_is_not_claimed_by_the_page_it_sits_on():
    """#39. Claro's controle page cross-sells a FLEX plan (`plano-flex-20gb`, R$44,90 there vs
    R$59,90 on the flex page). `category` and `plan_name` are inherited from the page being read, so
    that card became a "Controle 20GB" row at R$44,90 — undercutting every real Controle plan, and
    making the SAME R$44,90 drive both the Control and the Digital matrix columns. The product line
    is declared by Claro's own slug; trust that, not the page."""
    from mobile_tracker.adapters.claro import parse_next_data, slug_line

    assert slug_line("plano-flex-20gb") == "flex"
    assert slug_line("plano-controle-25gb") == "control"
    assert slug_line("plano-pos-60gb") == "postpaid"
    assert slug_line("prezao-30d-12gb") is None          # unknown shape -> never filtered

    def card(accordion_slug, price):
        return {"actions": [{"price": {"price": price},
                             "link": [{"modalContent": {
                                 "title": "Mais detalhes",
                                 "drawer_select_list": [{"accordion_list_relations": {
                                     "name": accordion_slug}}]}}]}]}

    data = {"props": {"pageProps": {"dynamicComponents": {"body": [{
        "component": "card_360",
        "data": {"data": [card("lista-accordion-card-360-plano-controle-25gb-mais-informacoes", "59,90"),
                          card("lista-accordion-card-360-plano-flex-20gb-mais-informacoes", "44,90")]}}]}}}}
    t = Target(carrier="claro", render="nextjs", category="control", category_label="Controle",
               state="SP", url="https://www.claro.com.br/celular/controle")
    plans = parse_next_data(data, t)
    assert [p.plan_id for p in plans] == ["claro:plano-controle-25gb"]   # the flex card is dropped
    assert min(p.price_brl for p in plans) == 59.90                      # a Flex price can't win Control

    # ...and the flex page still keeps its own plan, so nothing is lost overall
    tf = Target(carrier="claro", render="nextjs", category="flex", category_label="Flex",
                state="SP", url="https://www.claro.com.br/celular/flex")
    assert [p.plan_id for p in parse_next_data(data, tf)] == ["claro:plano-flex-20gb"]
