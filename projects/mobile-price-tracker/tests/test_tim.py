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


_FIT_HTML = (
    # trimmed shape of the live controle page's #price-fit section (SP, 2026-07-13): two tab blocks
    # with the marketing price phrases + the two benefits modals carrying the stable etiqueta codes.
    '<span id="price-fit"></span>'
    '<div><p>Conheça as versões anual e mensal do TIM Controle Fit</p>'
    '<tim-tab><h3>Plano anual</h3><p>Perfeito para o seu bolso</p>'
    '<p>Tenha 30GB por 12x R$30/mês, perfeito para o bolso</p>'
    '<button data-modal-open="modal-fit-anual">Conferir todos os benefícios</button></tim-tab>'
    '<tim-tab><h3>Plano mensal</h3><p>Perfeito para o seu bolso</p>'
    '<p>Tenha 20GB por R$35/mês sem comprometer seu limite do cartão</p>'
    '<button data-modal-open="modal-fit-mensal">Conferir todos os benefícios</button></tim-tab></div>'
    '<div id="modal-fit-anual"><p><a href="x.pdf">Etiqueta padrão - TIM202600000271 - '
    'com prazo de permanência</a></p></div>'
    '<div id="modal-fit-mensal"><p><a href="y.pdf">Etiqueta padrão - TIM202600000270 - '
    'sem prazo de permanência</a></p></div>')


def _fit_target() -> Target:
    return Target(carrier="tim", render="html", category="fit", category_label="TIM Fit (digital)",
                  state="SP", url="https://www.tim.com.br/sp/para-voce/planos/controle")


# NOTE (#36): the two #28 tests that pinned the OLD `#price-fit` markup — a single
# `modal-fit-anual` / `modal-fit-mensal` pair with no region or version suffix — were RETIRED here.
# TIM rebuilt the section on ~2026-08-03 into 2 regional blocks x 2 versions x 2 plan types, so that
# shape no longer exists on the page and a test asserting it pins a fiction. Both behaviours they
# guarded (every served tier parsed; an etiqueta code never bleeding in from an adjacent modal) are
# now covered in `tests/test_tim_fit.py` against a fixture derived from the REAL rebuilt capture.
# `_FIT_HTML` below is kept only for the price-helper and no-section tests.


def test_fit_returns_empty_without_section():
    # site restructure → no #price-fit anchor → [] (the fetch path logs a loud warning), never a crash.
    assert parse_tim_html("<html><body>no fit here</body></html>", _fit_target()) == []


def test_fit_price_dot_or_comma_decimal():
    # #28 review fix: the regex tail [.,]\d{1,2} is ALWAYS a decimal separator — a dot must never be
    # stripped as a thousands separator ('35.90' → 3590.0 would corrupt history + fire a false alert).
    from mobile_tracker.adapters.tim import _fit_price
    assert _fit_price("30") == 30.0
    assert _fit_price("34,99") == 34.99
    assert _fit_price("34.99") == 34.99
    assert _fit_price("35.9") == 35.9


def test_fit_category_does_not_disturb_control_parse():
    # the SAME page serves both targets: the control path still reads the ofertas JSON only.
    plans = parse_tim_html(FIXTURE.read_text(encoding="utf-8"), _target(), raw_ref="fixture")
    assert all(p.category == "control" for p in plans) and len(plans) >= 4


def test_prepaid_validity_days_is_per_oferta_not_max():
    # #23 (fixes #18's bug): TIM prepaid validity = THIS oferta's OWN "R$<recarga> … por <N> dias", NOT
    # the max "N dias" anywhere. A shared marketing line ("recarga de R$30 válidos por 30 dias") appears
    # in every oferta and fooled the old max heuristic into 30 for all. Audit #22: R$20 → 17 days.
    import json
    settings = {"ofertas": [{
        "nid": [{"value": "59906"}],
        "title": [{"value": "2 Card - TIM Pré XIP Plus - 6GB - [PROD]"}],
        "field_preco_card_oferta": [{"value": "20,00"}],
        # this oferta's OWN validity (17d) + the shared 30-day marketing line that inflated #18's max
        "field_layout_canvas_segundo": [{"value":
            "6GB por R$20, válidos por 17 dias. Ou faça uma recarga de R$30 válidos por 30 dias."}],
    }]}
    html = ('<script data-drupal-selector="drupal-settings-json" type="application/json">'
            + json.dumps(settings, ensure_ascii=False) + "</script>")
    t = Target(carrier="tim", render="html", category="prepaid", category_label="Pré-pago",
               state="SP", url="https://www.tim.com.br/sp/para-voce/planos/pre-pago")
    p = parse_tim_html(html, t, raw_ref="fx")[0]
    assert p.category == "prepaid"
    assert p.validity_days == 17          # its OWN 17d — NOT the shared 30d (the #18 bug)
    assert p.data_gb == 6.0 and p.price_brl == 20.0 and p.plan_id == "tim:59906"


def _postpaid_html(*ofertas) -> str:
    """Wrap oferta dicts in the drupal-settings-json <script> the parser reads."""
    import json
    settings = {"ofertas": list(ofertas)}
    return ('<script data-drupal-selector="drupal-settings-json" type="application/json">'
            + json.dumps(settings, ensure_ascii=False) + "</script>")


def _oferta(nid, title, price, headline):
    return {"nid": [{"value": nid}], "title": [{"value": title}],
            "field_preco_card_oferta": [{"value": price}],
            "field_preco_principal_7_1_3": [{"value": headline}]}


def test_postpaid_payment_method_credit_card_vs_bill():
    # #24: TIM postpaid billing type = field_preco_principal_7_1_3 headline — "no cartão" (recurring
    # credit card, the cheaper "Express" line) vs "na fatura" (bill/invoice). The two phrases are mutually
    # exclusive in that field (verified live SP 2026-07), so classification is reliable.
    html = _postpaid_html(
        _oferta("55121", "1 Card - TIM Black A Express - 67GB - [On Air]", "119,99",
                '<p style="font-size: 22px;">R$ 119,99/mês no cartão</p>\r\n<p>Incluso:</p>'),
        _oferta("54206", "1 Card - TIM Black - 70GB - [PROD]", "129,99",
                '<p style="font-size: 22px;">R$ 129,99/mês na fatura</p>\r\n<p>Liberdade para escolher '
                'uma assinatura:</p>'),
    )
    t = Target(carrier="tim", render="html", category="postpaid", category_label="Pós",
               state="SP", url="https://www.tim.com.br/sp/para-voce/planos/pos-pago/tim-black")
    plans = {p.plan_id: p for p in parse_tim_html(html, t, raw_ref="fx")}
    assert plans["tim:55121"].payment_method == "credit_card"   # cheaper "no cartão" plan (excluded later)
    assert plans["tim:55121"].price_brl == 119.99
    assert plans["tim:54206"].payment_method == "bill"          # "na fatura" — the entry-level pick
    assert plans["tim:54206"].price_brl == 129.99


def test_payment_method_only_tagged_for_postpaid():
    # #24: gated on category — the SAME field on a control/prepaid target is NOT tagged.
    html = _postpaid_html(
        _oferta("999", "1 Card - TIM Controle Plus - 45GB - [PROD]", "64,99",
                '<p>R$ 64,99/mês no cartão</p>'))
    tc = Target(carrier="tim", render="html", category="control", category_label="Controle",
                state="SP", url="https://www.tim.com.br/sp/para-voce/planos/controle")
    assert all(p.payment_method is None for p in parse_tim_html(html, tc, raw_ref="fx"))


def test_payment_method_helper_none_when_absent_or_ambiguous():
    # #24: no headline field, or one without either phrase → None (plan is NOT excluded).
    from mobile_tracker.adapters.tim import _payment_method
    assert _payment_method({}) is None
    assert _payment_method({"field_preco_principal_7_1_3": [{"value": "<p>R$ 100/mês</p>"}]}) is None


def test_payment_method_anchored_to_price_headline_not_stray_marketing():
    # #24 (hardening after adversarial review): the classifier is anchored to the "/mês <phrase>" price
    # line, so stray "no cartão" marketing/benefits text can NEVER flip a BILL plan to credit_card (which
    # would wrongly drop it from the entry-level pick). A bill headline + a "pague no cartão" promo → bill.
    from mobile_tracker.adapters.tim import _payment_method
    bill_with_card_promo = {"field_preco_principal_7_1_3": [{"value":
        '<p style="font-size: 22px;">R$ 129,99/mês na fatura</p>\r\n'
        '<p>Pague no cartão e ganhe cashback</p>\r\n<p>ou 12x no cartão</p>'}]}
    assert _payment_method(bill_with_card_promo) == "bill"        # headline wins, promo ignored
    card_headline = {"field_preco_principal_7_1_3": [{"value":
        '<p style="font-size: 22px;">R$ 119,99/mês no cartão</p>\r\n<p>Pague também na fatura</p>'}]}
    assert _payment_method(card_headline) == "credit_card"        # symmetric: card headline wins
