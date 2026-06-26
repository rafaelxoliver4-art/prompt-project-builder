"""Offline unit tests for the Vivo adapter's pure DOM parser (no network, no browser).

Runs `parse_vivo_html` against a trimmed real Playwright-rendered capture saved in
tests/fixtures/vivo_postpaid_sp.html (Vivo SP postpaid page, 2026-06-19).
"""
from pathlib import Path

from mobile_tracker.config import Target
from mobile_tracker.adapters.vivo import parse_vivo_html, _price_from

FIXTURE = Path(__file__).parent / "fixtures" / "vivo_postpaid_sp.html"


def _target() -> Target:
    return Target(carrier="vivo", render="aem", category="postpaid", category_label="Pós-pago",
                  state="SP",
                  url="https://vivo.com.br/para-voce/produtos-e-servicos/para-o-celular/planos-pos-pago")


def _plans():
    return parse_vivo_html(FIXTURE.read_text(encoding="utf-8"), _target(), raw_ref="fixture")


def test_extracts_valid_plans():
    plans = _plans()
    assert len(plans) >= 5
    for p in plans:
        assert p.is_valid()
        assert p.carrier == "vivo"
        assert p.category == "postpaid"
        assert p.state == "SP"
        assert p.price_brl and p.price_brl > 0
        assert p.plan_name.lower().startswith("vivo")
        assert p.raw_ref == "fixture"


def test_headline_amazon_plan():
    amazon = next((p for p in _plans() if "Amazon" in p.plan_name), None)
    assert amazon is not None, "expected the Vivo Pós com Amazon card"
    assert amazon.price_brl == 150.0
    assert amazon.data_gb == 60.0


def test_streaming_bundle_detected():
    netflix = next((p for p in _plans() if "Netflix" in p.plan_name), None)
    assert netflix is not None
    assert netflix.streaming == "Netflix"


def test_price_parsing():
    assert _price_from("150") == 150.0          # Vivo renders a plain integer
    assert _price_from("R$ 1.329,05") == 1329.05
    assert _price_from("24,99") == 24.99
    assert _price_from("") is None
    assert _price_from(None) is None


def test_no_duplicate_name_price():
    keys = [(p.plan_name, p.price_brl) for p in _plans()]
    assert len(keys) == len(set(keys))


def test_plan_id_native_offer_code():
    plans = _plans()
    assert all(p.plan_id and p.plan_id.startswith("vivo:") for p in plans)
    assert len({p.plan_id for p in plans}) == len(plans)        # unique per card
    amazon = next(p for p in plans if "Amazon" in p.plan_name)
    assert amazon.plan_id.startswith(("vivo:VIV", "vivo:SELF"))  # native offer code


PREPAID_FIXTURE = Path(__file__).parent / "fixtures" / "vivo_prepaid_sp.html"


def _prepaid_target() -> Target:
    return Target(carrier="vivo", render="aem", category="prepaid", category_label="Pré-pago",
                  state="SP", url="https://vivo.com.br/.../pre-pago/vivo-pre")


def test_prepaid_tiers_are_distinct():
    # All 4 prepaid tiers share ONE page-level offer code + the name "Vivo Pré"; the data allowance
    # (non-price) must keep them distinct so none collapse.
    plans = parse_vivo_html(PREPAID_FIXTURE.read_text(encoding="utf-8"), _prepaid_target(), raw_ref="fx")
    assert len(plans) == 4
    assert len({p.plan_id for p in plans}) == 4                 # not collapsed
    assert all(p.plan_id.startswith("vivo:VIV") for p in plans)
    assert sorted(int(p.data_gb) for p in plans) == [4, 5, 9, 25]


def test_prepaid_validity_days_captured():
    # #18: each Vivo prepaid tier carries its recarga validity ("N dias" in the card). The 30-day tier
    # (R$30 / 25GB) reads validity_days=30; the cheapest 30-day is what the Pre column compares.
    plans = parse_vivo_html(PREPAID_FIXTURE.read_text(encoding="utf-8"), _prepaid_target(), raw_ref="fx")
    by_gb = {int(p.data_gb): p for p in plans}
    assert by_gb[25].validity_days == 30 and by_gb[25].price_brl == 30.0   # the real 30-day plan
    assert by_gb[4].validity_days == 15                                    # a 15-day tier
    assert all(p.validity_days for p in plans)                             # every tier tagged


def test_postpaid_has_no_validity():
    # regression: validity parsing is PREPAID-only — postpaid cards keep validity_days None.
    assert all(p.validity_days is None for p in _plans())


def test_promo_captured_from_struck_price():
    # a struck-through original price (.unique-card__price-old) → regular vs. effective
    html = ('<div class="unique-card"><div class="unique-card__plan">Vivo Pós Teste</div>'
            '<div class="unique-card__header-benefit">50 GB</div>'
            '<div class="unique-card__price-old">R$ 200</div>'
            '<div class="total-card-price-value">150</div>'
            ' oferta VIV202600099999</div>')
    t = Target(carrier="vivo", render="aem", category="postpaid", category_label="Pós-pago",
               state="SP", url="u")
    p = parse_vivo_html(html, t)[0]
    assert p.price_brl == 200.0          # regular (struck-through)
    assert p.price_promo_brl == 150.0    # effective/discounted
    assert p.price_note
