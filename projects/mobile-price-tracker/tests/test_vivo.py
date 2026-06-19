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
