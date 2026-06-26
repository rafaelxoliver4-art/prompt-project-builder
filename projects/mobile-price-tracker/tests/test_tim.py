"""Offline unit tests for the TIM adapter's pure parser (no network).

Runs `parse_tim_html` against a trimmed fixture holding the real Drupal `ofertas` JSON
(TIM SP control page, 2026-06-19).
"""
from pathlib import Path

from mobile_tracker.config import Target
from mobile_tracker.adapters.tim import parse_tim_html, _price_brl, _clean_title

FIXTURE = Path(__file__).parent / "fixtures" / "tim_control_sp.html"


def _target() -> Target:
    return Target(carrier="tim", render="html", category="control", category_label="Controle",
                  state="SP", url="https://www.tim.com.br/sp/para-voce/planos/controle")


def _plans():
    return parse_tim_html(FIXTURE.read_text(encoding="utf-8"), _target(), raw_ref="fixture")


def test_extracts_valid_plans():
    plans = _plans()
    assert len(plans) >= 4
    for p in plans:
        assert p.is_valid()
        assert p.carrier == "tim"
        assert p.category == "control"
        assert p.state == "SP"
        assert p.price_brl and p.price_brl > 0
        assert p.plan_name.lower().startswith("tim")
        assert p.raw_ref == "fixture"


def test_known_plan_fields():
    plus = next((p for p in _plans() if "Plus 45GB" in p.plan_name), None)
    assert plus is not None
    assert plus.price_brl == 64.99
    assert plus.data_gb == 45.0
    assert plus.plan_id == "tim:155891"   # native Drupal node id


def test_plan_id_native_nid_and_unique():
    plans = _plans()
    assert all(p.plan_id and p.plan_id.startswith("tim:") for p in plans)
    assert len({p.plan_id for p in plans}) == len(plans)


def test_title_cleaning():
    assert _clean_title("1 Card - TIM Controle Plus 45GB - [PROD]") == "TIM Controle Plus 45GB"
    assert _clean_title("TIM Black - 70GB [On Air]") == "TIM Black 70GB"
    assert _clean_title("TIM Black C Ultra - 95GB - [On Air - ES, MG, SP]") == "TIM Black C Ultra 95GB"
    assert _clean_title([{"value": "TIM Pré XIP Plus - 16GB"}]) == "TIM Pré XIP Plus 16GB"


def test_price_parsing():
    assert _price_brl("64,99") == 64.99       # the bare JSON value format
    assert _price_brl("R$ 1.234,56") == 1234.56
    assert _price_brl("") is None
    assert _price_brl(None) is None


def test_no_duplicate_name_price():
    keys = [(p.plan_name, p.price_brl) for p in _plans()]
    assert len(keys) == len(set(keys))


def test_control_plans_have_no_validity():
    # regression: validity parsing is PREPAID-only — control plans keep validity_days None.
    assert all(p.validity_days is None for p in _plans())


def test_prepaid_validity_days_is_max_of_dias():
    # #18: TIM prepaid (XIP) has NO clean structured validity field — validity is parsed as the MAX
    # "N dias" in the oferta (the plan period; shorter promo bonuses don't win). Gated on prepaid.
    import json
    settings = {"ofertas": [{
        "nid": [{"value": "59906"}],
        "title": [{"value": "2 Card - TIM Pré XIP Plus - 6GB - [PROD]"}],
        "field_preco_card_oferta": [{"value": "20,00"}],
        # validity lives in the benefits-modal HTML: a 30-day plan with a shorter promo bonus
        "field_layout_canvas_segundo": [{"value": "benefícios válidos por 30 dias; bônus de 5GB por 17 dias"}],
    }]}
    html = ('<script data-drupal-selector="drupal-settings-json" type="application/json">'
            + json.dumps(settings, ensure_ascii=False) + "</script>")
    t = Target(carrier="tim", render="html", category="prepaid", category_label="Pré-pago",
               state="SP", url="https://www.tim.com.br/sp/para-voce/planos/pre-pago")
    plans = parse_tim_html(html, t, raw_ref="fx")
    assert len(plans) == 1
    p = plans[0]
    assert p.category == "prepaid"
    assert p.validity_days == 30          # max(30, 17) — the plan period, not the 17-day bonus
    assert p.data_gb == 6.0 and p.price_brl == 20.0
    assert p.plan_id == "tim:59906"
