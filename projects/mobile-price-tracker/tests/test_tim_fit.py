"""Offline tests for the REBUILT TIM Controle Fit parser — CODE TASK #36 (P0). No network.

These pin the two bugs that produced this project's only price alert, which was FALSE (#35 audit):
a first-match regex that captured a *different* tier's price, and an exact modal-id lookup that
silently degraded the carrier-native `plan_id` to a name slug.
"""
from pathlib import Path

import pytest

from mobile_tracker.adapters.tim import parse_tim_html, _fit_serves_state
from mobile_tracker.config import Target

FIXTURE = Path(__file__).parent / "fixtures" / "tim_fit_sp.html"
HTML = FIXTURE.read_text(encoding="utf-8")

# the four SP tiers, as the page really serves them (verified against the live capture 2026-08-04)
SP_EXPECTED = {
    "tim:TIM202600000306": ("TIM Controle Fit Anual 1.0", 20.0, 25.0, 12, "credit_card"),
    "tim:TIM202600000271": ("TIM Controle Fit Anual 2.0", 30.0, 35.0, 12, "credit_card"),
    "tim:TIM202600000270": ("TIM Controle Fit Mensal 1.0", 20.0, 20.0, None, None),
    "tim:TIM202600000305": ("TIM Controle Fit Mensal 2.0", 45.0, 35.0, None, None),
}


def _target(state="SP"):
    return Target(carrier="tim", render="html", category="fit", category_label="TIM Fit (digital)",
                  state=state, url="https://www.tim.com.br/sp/para-voce/planos/controle")


def _plans(state="SP"):
    return parse_tim_html(HTML, _target(state), raw_ref="fx")


def test_captures_both_sp_tiers_of_both_plan_types():
    """#36: TIM rebuilt the section into 2 regions x 2 versions x 2 types. All FOUR cards served to SP
    must be captured — the old parser took one phrase per plan type (and the wrong one)."""
    plans = _plans()
    assert len(plans) == 4
    got = {p.plan_id: (p.plan_name, p.price_brl, p.data_gb, p.loyalty_months, p.payment_method)
           for p in plans}
    assert got == SP_EXPECTED
    assert all(p.category == "fit" and p.state == "SP" and p.is_valid() for p in plans)


def test_plan_id_is_the_stable_etiqueta_never_a_name_slug():
    """REGRESSION (#35): the exact `modal-fit-anual` lookup stopped matching when the ids became
    `modal-fit-anual-2.0-sp-sc-rn-ce`, so plan_id degraded to `tim:fit-anual` — and the #29 name
    fallback then manufactured a price move. The id must come from the card's OWN modal etiqueta."""
    ids = {p.plan_id for p in _plans()}
    assert ids == set(SP_EXPECTED)
    assert not any(i.startswith("tim:fit-") for i in ids), f"plan_id degraded to a slug: {ids}"
    assert all(i.startswith("tim:TIM2026") for i in ids)


def test_each_card_gets_its_own_price_not_the_first_on_the_page():
    """REGRESSION (#35, the false alert): the old regex took the FIRST 'Tenha …' phrase in the whole
    section, so the tracked Anual (etiqueta 271, R$30) was recorded with the newly-inserted 1.0 card's
    R$20. Each card is now anchored on its own data-modal-open link."""
    by = {p.plan_id: p for p in _plans()}
    assert by["tim:TIM202600000271"].price_brl == 30.0     # NOT 20.0 (the 1.0 card's price)
    assert by["tim:TIM202600000271"].data_gb == 35.0       # NOT 25.0
    assert by["tim:TIM202600000306"].price_brl == 20.0     # the 1.0 card keeps its own price
    assert len({p.price_brl for p in _plans()}) >= 3       # prices are not all the same value


def test_region_gate_sp_block_only_and_demais_ufs_fallback():
    """The Fit section carries NO field_regioes (that exists only on ofertas JSON nodes); the modal
    id's region list is the real gate. SP must take the `-sp-sc-rn-ce` block; a state named by no
    block falls through to the `demais-ufs` catch-all — never a mix of both."""
    sp = {p.plan_id: p.data_gb for p in _plans("SP")}
    mg = {p.plan_id: p.data_gb for p in _plans("MG")}
    assert sp["tim:TIM202600000306"] == 25.0        # SP block
    assert mg["tim:TIM202600000306"] == 20.0        # demais-ufs block — a DIFFERENT allowance
    assert sp != mg, "the region gate is not selecting distinct blocks"
    assert len(mg) == 4
    # a state explicitly named in the SP block's list gets that block
    assert {p.data_gb for p in _plans("CE")} == set(sp.values())


def test_fit_serves_state_helper():
    assert _fit_serves_state("sp-sc-rn-ce", "SP") and _fit_serves_state("sp-sc-rn-ce", "ce")
    assert not _fit_serves_state("sp-sc-rn-ce", "MG")
    assert not _fit_serves_state("demais-ufs", "SP")


def test_loyalty_and_payment_follow_the_installment_marker():
    """'12x' on the card => the annual, credit-card plan (loyalty modelled as 12m, as Vivo's annual is
    in #26); no '12x' => the no-commitment monthly. The Digital matrix picks the latter."""
    by = {p.plan_id: p for p in _plans()}
    for pid in ("tim:TIM202600000306", "tim:TIM202600000271"):
        assert by[pid].loyalty_months == 12 and by[pid].payment_method == "credit_card"
        assert "12x no cartão" in by[pid].price_note
    for pid in ("tim:TIM202600000270", "tim:TIM202600000305"):
        assert by[pid].loyalty_months is None and by[pid].payment_method is None
        assert "sem prazo de permanência" in by[pid].price_note
    # the carrier's own wording is recorded on every tier, even where we model it differently
    assert all("etiqueta TIM informa 'sem prazo de permanência'" in p.price_note for p in _plans())


def test_card_vs_modal_price_disagreement_is_reported_not_silently_resolved():
    """GOVERNANCE: never invent a number. SP's Mensal 1.0 card reads R$20 while its own modal still
    reads R$35 — we record what the page shows the SP visitor and SAY SO in the note."""
    m = next(p for p in _plans() if p.plan_id == "tim:TIM202600000270")
    assert m.price_brl == 20.0
    assert "ATENÇÃO" in m.price_note and "modal" in m.price_note and "35" in m.price_note
    # tiers whose card and modal agree carry no such warning
    ok = next(p for p in _plans() if p.plan_id == "tim:TIM202600000305")
    assert "ATENÇÃO" not in ok.price_note


def test_missing_or_restructured_section_returns_empty():
    t = _target()
    assert parse_tim_html("<html><body>no fit section</body></html>", t) == []
    assert parse_tim_html('<span id="price-fit"></span><div>no cards</div>', t) == []


def test_other_tim_categories_are_untouched():
    """The fit rewrite must not disturb the ofertas-JSON path."""
    ctl = Target(carrier="tim", render="html", category="control", category_label="Controle",
                 state="SP", url="u")
    fx = Path(__file__).parent / "fixtures" / "tim_control_sp.html"
    plans = parse_tim_html(fx.read_text(encoding="utf-8"), ctl, raw_ref="fx")
    assert plans and all(p.category == "control" for p in plans)
