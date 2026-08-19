"""CODE TASK #37 — the reliability pass. Offline; no network, no browser, no SMTP.

Six independent defects/gaps, each pinned here so a regression is caught before the next live run:

  A. Vivo headline included a pre-checked R$5 add-on (7 of 8 Controle prices were wrong).
  B. Vivo plan_id embedded a PARSED GB, so the same offer changed identity between runs.
  C. `_merge_history` deduped without `category`, silently dropping a real row.
  D. Price alerts covered mobile only, and the #29 name fallback paired too eagerly.
  E. Nothing blocked a degraded scrape; retry policy retried blocks (GOVERNANCE §3).
  F. A job that never ran was completely silent (the lost 2026-08-04 snapshot).
"""
from datetime import date, datetime

import pandas as pd
import pytest

import mobile_tracker.alerts as alerts
from mobile_tracker.adapters.base import fetch_with_retry, is_transient_error
from mobile_tracker.adapters.vivo import parse_vivo_html
from mobile_tracker.alerts import (Alert, check_sanity, check_staleness, compute_convergent_alerts,
                                   compute_price_alerts, format_alert_email, format_staleness_email)
from mobile_tracker.config import Target
from mobile_tracker.convergent import ConvergentOffer
from mobile_tracker.excel_writer import write_workbook
from mobile_tracker.models import Plan


# --------------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------------
def _vivo_target(category="control"):
    return Target(carrier="vivo", render="aem", category=category, category_label=category,
                  state="SP", url="https://vivo.com.br/x")


def _card(name, shown, original, *, benefit="60 GB", switch=True, viv="VIV202600030938"):
    """One `.unique-card` in the live shape. `switch=True` reproduces the PRE-CHECKED add-on
    (`data-startdisabled="checked"`) that made the displayed price base+add-on."""
    sw = ('<div data-controller="switchUnique" data-startdisabled="checked">'
          '<span>+ 10 GB para suas redes sociais R$ 5</span></div>') if switch else ""
    return (f'<div class="unique-card">'
            f'<div class="unique-card__plan">{name}</div>'
            f'<div class="unique-card__header-benefit">{benefit}</div>'
            f'{sw}'
            f'<span class="total-card-price-value" data-original-price="{original}">{shown}</span>'
            f'<a href="/x">Baixar condições da oferta {viv}</a>'
            f'</div>')


def P(carrier, cat, name, pid, price, state="SP"):
    return Plan(carrier=carrier, category=cat, state=state, plan_name=name, plan_id=pid,
                price_brl=price, source_url="x")


def O(carrier, name, oid, price, state="SP"):
    return ConvergentOffer(carrier=carrier, state=state, offer_name=name, offer_id=oid,
                           price_brl=price, has_mobile=True, has_broadband=True, source_url="x")


def _stamp(rows, d):
    for r in rows:
        r.snapshot_date, r.snapshot_ts = d, f"{d}T18:00:00"
    return rows


# --------------------------------------------------------------------------------------------
# PART A — the headline is the plan, not the plan + a pre-selected optional add-on
# --------------------------------------------------------------------------------------------
def test_pre_checked_addon_is_excluded_from_the_headline():
    """Live 2026-08-05: the card SHOWS R$80 because a R$5 "+10 GB" switch ships pre-selected; the
    plan itself is R$75 in `data-original-price`. The tracker compares PLANS, so 75 is the price."""
    plans = parse_vivo_html(_card("Vivo Controle", 80, 75), _vivo_target())
    assert len(plans) == 1
    p = plans[0]
    assert p.price_brl == 75.0
    assert p.price_promo_brl is None                 # an add-on is NOT a promo
    assert "80" in p.price_note and "adicional" in p.price_note   # what the screen said, as context


def test_the_addon_gb_comes_off_with_the_addon_price():
    """Found by the #37 adversarial review. The header benefit reports the add-on-INCLUSIVE
    allowance — the same card family reads 46 GB unchecked and 61 GB checked (51 + 10) — so storing
    the BASE price beside 61 GB describes a plan Vivo does not sell, and would corrupt any R$/GB
    lens. Price and data must be de-bundled together."""
    plans = parse_vivo_html(_card("Vivo Controle", 80, 75, benefit="61 GB"), _vivo_target())
    p = plans[0]
    assert p.price_brl == 75.0 and p.data_gb == 51.0
    assert "61 GB na tela incluem +10 GB do adicional" in p.price_note


def test_addon_gb_subtraction_declines_when_it_cannot_be_trusted():
    """No subtraction when the add-on GB is unreadable, or when it would zero/negate the allowance —
    a wrong number is worse than the on-screen one, which at least matches the page."""
    no_gb_in_switch = (
        '<div class="unique-card"><div class="unique-card__plan">Vivo Controle</div>'
        '<div class="unique-card__header-benefit">61 GB</div>'
        '<div data-controller="switchUnique" data-startdisabled="checked">'
        '<span>adicional de redes sociais por R$ 5</span></div>'
        '<span class="total-card-price-value" data-original-price="75">80</span>'
        '<a href="/x">oferta VIV202600030938</a></div>')
    assert parse_vivo_html(no_gb_in_switch, _vivo_target())[0].data_gb == 61.0   # unreadable → keep
    tiny = _card("Vivo Controle", 80, 75, benefit="10 GB")                       # 10 - 10 = 0 → keep
    assert parse_vivo_html(tiny, _vivo_target())[0].data_gb == 10.0


def test_addon_rule_needs_the_switch_to_be_pre_checked():
    """No switch on the card → `data-original-price` keeps its ordinary meaning; the rule must not
    reinterpret every card that happens to carry the attribute."""
    plans = parse_vivo_html(_card("Vivo Controle", 80, 75, switch=False), _vivo_target())
    assert plans[0].price_brl == 80.0 and plans[0].price_note is None


def test_addon_rule_ignores_an_original_price_above_the_shown_price():
    """`data-original-price` > displayed is a struck-through PROMO, not an add-on — the add-on branch
    must decline it and let the promo path handle it."""
    plans = parse_vivo_html(_card("Vivo Controle", 75, 90), _vivo_target())
    assert plans[0].price_brl == 75.0 and plans[0].price_note is None


def test_lite_loyalty_rule_survives_the_addon_change():
    """Regression guard on the category split: for `lite`, `data-original-price` is the 12-month
    LOYALTY price and the DISPLAYED figure is the no-commitment headline (CONTEXT §10.5) — the
    opposite of `control`. #37 must not have inverted it."""
    plans = parse_vivo_html(_card("Vivo Easy Lite", 45, 30, switch=False), _vivo_target("lite"))
    p = plans[0]
    assert p.price_brl == 45.0 and p.price_promo_brl == 30.0 and p.loyalty_months == 12


# --------------------------------------------------------------------------------------------
# PART B — a stable plan_id: same offer, two captures, one identity
# --------------------------------------------------------------------------------------------
def test_plan_id_is_stable_when_the_rendered_gb_changes():
    """THE root cause of 79% of all alert noise (#35 audit): the id used to embed the PARSED GB, which
    the pre-checked add-on made vary between renders (61 GB one day, 51 GB the next). The same offer
    then looked like remove+add, the name fallback re-paired it, and a ±5% phantom alert went out."""
    # the REAL pair: one render has the add-on applied (61 GB @ R$80 shown, base 75), the other does
    # not (51 GB @ R$75, no switch state) — the same offer, two renders.
    day1 = parse_vivo_html(_card("Vivo Controle", 80, 75, benefit="61 GB"), _vivo_target())
    day2 = parse_vivo_html(_card("Vivo Controle", 75, 75, benefit="51 GB", switch=False),
                           _vivo_target())
    assert day1[0].plan_id == day2[0].plan_id == "vivo:VIV202600030938"
    assert "gb" not in day1[0].plan_id.lower()       # no parsed quantity in the identity
    # de-bundling settles price AND data, so the two renders now agree on all three
    assert day1[0].price_brl == day2[0].price_brl == 75.0
    assert day1[0].data_gb == day2[0].data_gb == 51.0
    assert compute_price_alerts(day1, day2, 3.0) == []            # no phantom move left to report


def test_plan_id_is_not_price_derived():
    """A price change must read as a change to the SAME plan (CONTEXT §4), never as a new plan."""
    cheap = parse_vivo_html(_card("Vivo Controle", 80, 75), _vivo_target())
    dear = parse_vivo_html(_card("Vivo Controle", 95, 90), _vivo_target())
    assert cheap[0].plan_id == dear[0].plan_id
    assert compute_price_alerts(cheap, dear, 3.0)[0].pct == pytest.approx(20.0)


def test_prepaid_id_keeps_the_validity_token():
    """Prepaid is the one category where all tiers share ONE page-level VIV code, so the tier needs a
    discriminator. Validity (an attribute) is used — never the price, never the add-on-skewed GB."""
    html = (_card("Vivo Pré 30 dias", 40, 40, benefit="10 GB", switch=False) +
            _card("Vivo Pré 15 dias", 25, 25, benefit="5 GB", switch=False))
    plans = parse_vivo_html(html, _vivo_target("prepaid"))
    assert {p.plan_id for p in plans} == {"vivo:VIV202600030938-30d", "vivo:VIV202600030938-15d"}


# --------------------------------------------------------------------------------------------
# PART C — the history dedupe key must include `category`
# --------------------------------------------------------------------------------------------
def test_two_categories_sharing_a_plan_id_both_survive(tmp_path):
    """A live Claro Controle 20 GB row (R$44,90) was being SILENTLY DROPPED: the dedupe key was
    (date, carrier, state, _key) and Claro reuses a native id across category pages, so the second
    row overwrote the first. `category` is part of a plan's identity, so it belongs in the key."""
    out = tmp_path / "wb.xlsx"
    rows = _stamp([P("claro", "control", "Controle 20GB", "claro:dup", 44.90),
                   P("claro", "flex", "Flex 20GB", "claro:dup", 59.90)], "2026-08-05")
    write_workbook(rows, out, datetime(2026, 8, 5, 18))
    hist = pd.read_excel(out, sheet_name="history")
    assert len(hist) == 2
    assert set(hist["category"]) == {"control", "flex"}
    assert sorted(hist["price_brl"]) == [44.90, 59.90]


def test_a_reused_native_id_across_categories_is_not_a_price_move():
    """Found by the #37 live replay — Part C and Part D are coupled. Once BOTH Claro rows survive,
    `claro:plano-flex-20gb` exists twice in one snapshot (R$44,90 Controle, R$59,90 Flex), because
    Claro's controle page reuses the flex slug. Keyed on (carrier, state, plan_id) alone the two
    collapse and the R$15 gap is reported as a −25% cut that never happened."""
    prev = [P("claro", "flex", "Flex 20GB", "claro:plano-flex-20gb", 59.90)]
    today = [P("claro", "control", "Controle 20GB", "claro:plano-flex-20gb", 44.90),
             P("claro", "flex", "Flex 20GB", "claro:plano-flex-20gb", 59.90)]
    assert compute_price_alerts(prev, today, 3.0) == []   # flex is unchanged; control is genuinely new


def test_changes_sheet_also_keys_on_category(tmp_path):
    """The `changes` sheet and the alert must agree (they are the same identity) — so the same
    reused-id case must land as ONE `new` row, never as a price_change."""
    out = tmp_path / "wb.xlsx"
    write_workbook(_stamp([P("claro", "flex", "Flex 20GB", "claro:plano-flex-20gb", 59.90)],
                          "2026-08-03"), out, datetime(2026, 8, 3, 18))
    write_workbook(_stamp([P("claro", "control", "Controle 20GB", "claro:plano-flex-20gb", 44.90),
                           P("claro", "flex", "Flex 20GB", "claro:plano-flex-20gb", 59.90)],
                          "2026-08-05"), out, datetime(2026, 8, 5, 18))
    ch = pd.read_excel(out, sheet_name="changes")
    assert list(ch["change_type"]) == ["new"]
    assert ch["category"].iloc[0] == "control" and ch["new_price_brl"].iloc[0] == 44.90


def test_same_plan_twice_in_one_day_still_dedupes(tmp_path):
    """The dedupe still has to WORK: a genuine duplicate (same date/carrier/state/category/id) keeps
    the last row, so re-running the job on the same day cannot inflate history."""
    out = tmp_path / "wb.xlsx"
    write_workbook(_stamp([P("tim", "control", "A", "tim:1", 50.0)], "2026-08-05"),
                   out, datetime(2026, 8, 5, 18))
    write_workbook(_stamp([P("tim", "control", "A", "tim:1", 55.0)], "2026-08-05"),
                   out, datetime(2026, 8, 5, 19))
    hist = pd.read_excel(out, sheet_name="history")
    assert len(hist) == 1 and hist["price_brl"].iloc[0] == 55.0     # keep="last"


# --------------------------------------------------------------------------------------------
# PART D — convergent alerts, a merged digest, and a fallback that refuses to guess
# --------------------------------------------------------------------------------------------
def test_convergent_price_move_is_alerted():
    """Combos were tracked but never watched: a R$129,80 → R$149,80 move produced no e-mail."""
    found = compute_convergent_alerts([O("claro", "Fibra + Móvel", "claro:u1", 129.80)],
                                      [O("claro", "Fibra + Móvel", "claro:u1", 149.80)], 3.0)
    assert len(found) == 1
    a = found[0]
    assert a.domain == "convergent" and a.plan_id == "claro:u1" and a.direction == "▲"
    assert a.pct == pytest.approx(15.4, abs=0.05)


def test_stale_convergent_snapshot_is_not_re_reported(tmp_path):
    """Found by the #37 adversarial review. The convergent pass is guarded and legitimately collects
    nothing, in which case `_merge_convergent` adds no new date. Diffing each sheet's own two latest
    dates would then re-send yesterday's combo moves — stamped today — every single day."""
    out = tmp_path / "wb.xlsx"
    write_workbook(_stamp([P("tim", "control", "A", "tim:1", 100.0)], "2026-08-04"),
                   out, datetime(2026, 8, 4, 18),
                   convergent=_stamp([O("claro", "F+M", "claro:u1", 200.0)], "2026-08-03"))
    write_workbook(_stamp([P("tim", "control", "A", "tim:1", 100.0)], "2026-08-05"),
                   out, datetime(2026, 8, 5, 18), convergent=[])   # combos failed today
    conv = pd.read_excel(out, sheet_name="convergent_history", dtype={"snapshot_date": str})
    assert set(conv["snapshot_date"]) == {"2026-08-03"}            # preserved, not advanced
    found, day = alerts.alerts_from_workbook(out, 3.0)
    assert [a for a in found if a.domain == "convergent"] == []    # nothing stale re-reported


def test_convergent_uses_offer_fields_not_plan_fields():
    """The shared rule is parameterised, so it must read offer_id/offer_name — a silent fallback to
    the (absent) plan_* attributes would key every offer on None and pair unrelated combos."""
    prev = [O("vivo", "Vivo Total 500MB", "vivo:a", 200.0), O("vivo", "Vivo Total 1G", "vivo:b", 300.0)]
    today = [O("vivo", "Vivo Total 500MB", "vivo:a", 260.0), O("vivo", "Vivo Total 1G", "vivo:b", 300.0)]
    found = compute_convergent_alerts(prev, today, 3.0)
    assert [(a.plan_id, a.plan_name) for a in found] == [("vivo:a", "Vivo Total 500MB")]


def test_digest_merges_both_domains_into_labelled_sections():
    mob = compute_price_alerts([P("tim", "control", "Controle 41GB", "tim:1", 100.0)],
                               [P("tim", "control", "Controle 41GB", "tim:1", 110.0)], 3.0)
    con = compute_convergent_alerts([O("claro", "Fibra + Móvel", "claro:u1", 129.80)],
                                    [O("claro", "Fibra + Móvel", "claro:u1", 149.80)], 3.0)
    subject, body = format_alert_email(mob + con, "2026-08-05", 3.0)
    assert "2 price change" in subject
    assert "MOBILE PLANS" in body and "CONVERGENT" in body
    assert body.index("MOBILE PLANS") < body.index("CONVERGENT")     # mobile first
    assert "Controle 41GB" in body and "Fibra + Móvel" in body


def test_digest_omits_a_section_with_no_alerts():
    con = compute_convergent_alerts([O("claro", "F+M", "claro:u1", 100.0)],
                                    [O("claro", "F+M", "claro:u1", 120.0)], 3.0)
    _, body = format_alert_email(con, "2026-08-05", 3.0)
    assert "CONVERGENT" in body and "MOBILE PLANS" not in body


def test_fallback_refuses_when_the_name_repeats_elsewhere_in_the_snapshot():
    """#37 tightening. #29 only checked the UNMATCHED rows for uniqueness, so a name that also exists
    on an id-matched row could still be claimed by the fallback — how Vivo's rotating ids produced
    reversing ±5% alerts. The name must now be unique in the FULL snapshot on BOTH sides."""
    prev = [P("vivo", "control", "Vivo Controle", "vivo:old", 75.0),
            P("vivo", "control", "Vivo Controle", "vivo:keep", 75.0)]   # same name, id survives
    today = [P("vivo", "control", "Vivo Controle", "vivo:new", 80.0),   # rotated id, +6.7%
             P("vivo", "control", "Vivo Controle", "vivo:keep", 75.0)]
    assert compute_price_alerts(prev, today, 3.0) == []                  # ambiguous → refuse


def test_changes_sheet_fallback_is_tightened_in_lockstep_with_the_alert(tmp_path):
    """Found by the #37 adversarial review. CONTEXT §3 promises the `changes` sheet and the e-mail
    use the SAME identity rule, but #37 first tightened only alerts.py — leaving `_rotation_pairs`
    on the #29 rule, so the sheet would claim a price_change the e-mail refused to send. Same input
    as the alert test above; both must now decline."""
    out = tmp_path / "wb.xlsx"
    write_workbook(_stamp([P("vivo", "control", "Vivo Controle", "vivo:old", 75.0),
                           P("vivo", "control", "Vivo Controle", "vivo:keep", 75.0)], "2026-08-04"),
                   out, datetime(2026, 8, 4, 18))
    write_workbook(_stamp([P("vivo", "control", "Vivo Controle", "vivo:new", 80.0),
                           P("vivo", "control", "Vivo Controle", "vivo:keep", 75.0)], "2026-08-05"),
                   out, datetime(2026, 8, 5, 18))
    ch = pd.read_excel(out, sheet_name="changes")
    assert "price_change" not in set(ch["change_type"])          # ambiguous name → refuse, like the alert
    assert set(ch["change_type"]) == {"new", "removed"}
    assert alerts.alerts_from_workbook(out, 3.0)[0] == []        # and the two agree


def test_fallback_still_fires_for_a_genuinely_unique_name():
    """The tightening must not disable #29: TIM's real nid rotation still has to be caught."""
    prev = [P("tim", "control", "TIM Controle 41GB", "tim:162901", 58.99)]
    today = [P("tim", "control", "TIM Controle 41GB", "tim:167036", 49.99)]
    found = compute_price_alerts(prev, today, 3.0)
    assert len(found) == 1 and found[0].rekeyed_from == "tim:162901"
    _, body = format_alert_email(found, "2026-08-05", 3.0)
    assert "re-keyed" in body and "tim:162901" in body and "tim:167036" in body


def test_workbook_digest_covers_both_sheets(tmp_path):
    out = tmp_path / "wb.xlsx"
    write_workbook(_stamp([P("tim", "control", "A", "tim:1", 100.0)], "2026-08-04"),
                   out, datetime(2026, 8, 4, 18),
                   convergent=_stamp([O("claro", "F+M", "claro:u1", 200.0)], "2026-08-04"))
    write_workbook(_stamp([P("tim", "control", "A", "tim:1", 120.0)], "2026-08-05"),
                   out, datetime(2026, 8, 5, 18),
                   convergent=_stamp([O("claro", "F+M", "claro:u1", 240.0)], "2026-08-05"))
    found, day = alerts.alerts_from_workbook(out, 3.0)
    assert day == "2026-08-05"
    assert {(a.domain, a.plan_id) for a in found} == {("mobile", "tim:1"), ("convergent", "claro:u1")}
    assert found[0].domain == "mobile"                                   # mobile section first


# --------------------------------------------------------------------------------------------
# PART E — sanity BLOCKS; retries never spam a block
# --------------------------------------------------------------------------------------------
_CFG = {"price_min_brl": 5, "price_max_brl": 2000,
        "carriers": {"claro": {"min_plans": 12, "max_plans": 32}},
        "convergent": {"claro": {"min_offers": 5, "max_offers": 20}}}


def test_sanity_passes_on_a_healthy_run():
    assert check_sanity({"claro": 20}, [P("claro", "control", "A", "claro:1", 44.90)], _CFG,
                        per_carrier_convergent={"claro": 10},
                        convergent=[O("claro", "F+M", "claro:u1", 129.80)]) == []


@pytest.mark.parametrize("count,kind", [(3, "count_low"), (99, "count_high")])
def test_sanity_flags_a_count_outside_the_band(count, kind):
    issues = check_sanity({"claro": count}, [], _CFG)
    assert [i.kind for i in issues] == [kind]


def test_sanity_flags_an_absurd_price_in_either_domain():
    kinds = [i.kind for i in check_sanity(
        {"claro": 20}, [P("claro", "control", "Cheap", "claro:1", 0.99)], _CFG,
        per_carrier_convergent={"claro": 10},
        convergent=[O("claro", "Huge", "claro:u1", 5000.0)])]
    assert kinds == ["price_out_of_range", "price_out_of_range"]


def test_sanity_allows_the_real_r1200_vivo_combo():
    """The cap is 2000, not 1000, on purpose: Vivo Total "V 1 Giga" genuinely costs R$1.200/mo. A
    tighter cap would band out real data every single day."""
    assert check_sanity({}, [], _CFG, convergent=[O("vivo", "V 1 Giga", "vivo:v1", 1200.0)]) == []


def test_sanity_only_judges_carriers_that_were_scraped():
    """`--only tim` must not fail because claro/vivo were never attempted."""
    assert check_sanity({}, [], _CFG) == []


def test_sanity_failure_blocks_the_commit(tmp_path, monkeypatch):
    """The whole point of the guardrail: a degraded scrape must NOT be written or committed. main.py
    signals that with a non-zero exit, which is what skips the workflow's commit step."""
    import mobile_tracker.main as main_mod

    calls = {"write": 0, "email": []}
    monkeypatch.setattr(main_mod, "write_workbook",
                        lambda *a, **k: calls.__setitem__("write", calls["write"] + 1))
    monkeypatch.setattr(alerts, "check_staleness", lambda *a, **k: None)
    monkeypatch.setattr(alerts, "send_alert_email",
                        lambda cfg, s, b: calls["email"].append(s) or True)

    class _Stub:
        def __init__(self, settings): pass
        def fetch(self, target):
            return [P(target.carrier, target.category, "Only one", f"{target.carrier}:1", 50.0)]

    class _NoOffers:
        def __init__(self, settings): pass
        def fetch(self, target): return []

    monkeypatch.setattr(main_mod, "ADAPTERS", {c: _Stub for c in ("claro", "vivo", "tim")})
    # Stub the convergent registry too — these tests are OFFLINE; an unstubbed run would hit all
    # three live combo pages (and be slow, flaky, and impolite).
    registry = __import__("mobile_tracker.adapters", fromlist=["x"]).CONVERGENT_ADAPTERS
    for name in list(registry):
        monkeypatch.setitem(registry, name, _NoOffers)
    rc = main_mod.run(demo=False)
    assert rc != 0                          # non-zero → the workflow's commit step never runs
    assert calls["write"] == 0              # and nothing was written over the good history
    assert any("SANITY" in s for s in calls["email"])


def test_retry_retries_a_transient_blip():
    seen = []

    def flaky():
        seen.append(1)
        if len(seen) < 2:
            raise RuntimeError("net::ERR_NETWORK_CHANGED")
        return "ok"

    assert fetch_with_retry(flaky, 2, sleep_fn=lambda s: None) == "ok"
    assert len(seen) == 2


def test_retry_never_spams_a_block():
    """GOVERNANCE §3: a 403/CAPTCHA is a REFUSAL, not a blip. Hammering it is exactly the behaviour
    the politeness rules forbid — and the old per-adapter loops did it on every HTTPError."""
    seen = []

    def blocked():
        seen.append(1)
        raise RuntimeError("Client error '403 Forbidden' for url 'https://x'")

    with pytest.raises(RuntimeError):
        fetch_with_retry(blocked, 5, sleep_fn=lambda s: None)
    assert len(seen) == 1                    # one attempt, then surfaced
    assert is_transient_error(RuntimeError("403 Forbidden")) is False
    assert is_transient_error(RuntimeError("ReadTimeout")) is True


def test_retry_gives_up_after_the_budget():
    seen = []

    def always():
        seen.append(1)
        raise RuntimeError("ConnectTimeout")

    with pytest.raises(RuntimeError):
        fetch_with_retry(always, 2, sleep_fn=lambda s: None)
    assert len(seen) == 3                    # 1 + 2 retries, bounded


# --------------------------------------------------------------------------------------------
# PART F — a run that never happened has to be noticed
# --------------------------------------------------------------------------------------------
def _hist(tmp_path, days):
    out = tmp_path / "wb.xlsx"
    for d in days:
        write_workbook(_stamp([P("tim", "control", "A", "tim:1", 50.0)], d),
                       out, datetime(*[int(x) for x in d.split("-")], 18))
    return out


def test_staleness_silent_while_the_history_is_current(tmp_path):
    out = _hist(tmp_path, ["2026-08-04", "2026-08-05"])
    assert check_staleness(out, 2, today=date(2026, 8, 6)) is None


def test_staleness_reports_the_age_and_every_missing_date(tmp_path):
    out = _hist(tmp_path, ["2026-08-01", "2026-08-02"])
    msg = check_staleness(out, 2, today=date(2026, 8, 6))
    assert "2026-08-02" in msg and "4 days old" in msg
    for missing in ("2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06"):
        assert missing in msg
    subject, body = format_staleness_email(msg, "2026-08-06")
    assert "STALE DATA" in subject and msg in body


def test_staleness_never_raises_on_a_missing_workbook(tmp_path):
    """It runs BEFORE the scrape — it must never be the reason a run dies."""
    assert check_staleness(tmp_path / "nope.xlsx", 2, today=date(2026, 8, 6)) is None


def test_watchdog_is_quiet_when_today_is_present(tmp_path, monkeypatch):
    from mobile_tracker import watchdog
    out = _hist(tmp_path, ["2026-08-05"])
    sent = []
    monkeypatch.setattr(watchdog.alerts_mod, "send_alert_email",
                        lambda cfg, s, b: sent.append(s) or True)
    monkeypatch.setattr(watchdog.config, "load", lambda: _FakeSettings(out))
    assert watchdog.run(today=date(2026, 8, 5)) == 0
    assert sent == []


def test_watchdog_emails_when_today_is_missing(tmp_path, monkeypatch):
    """The 2026-08-04 case: the job died in the pre-scrape test step, no snapshot was written, and
    nobody was told. This is the notification that would have caught it."""
    from mobile_tracker import watchdog
    out = _hist(tmp_path, ["2026-08-03"])
    sent = []
    monkeypatch.setattr(watchdog.alerts_mod, "send_alert_email",
                        lambda cfg, s, b: sent.append((s, b)) or True)
    monkeypatch.setattr(watchdog.config, "load", lambda: _FakeSettings(out))
    rc = watchdog.run(today=date(2026, 8, 4))
    assert rc == 0                                   # reports; never fails its own workflow
    assert len(sent) == 1
    subject, body = sent[0]
    assert "NO SNAPSHOT TODAY" in subject and "2026-08-04" in subject
    assert "2026-08-03" in body                      # newest on file, so the gap is obvious


def test_watchdog_survives_an_unreadable_workbook(tmp_path, monkeypatch):
    from mobile_tracker import watchdog
    sent = []
    monkeypatch.setattr(watchdog.alerts_mod, "send_alert_email",
                        lambda cfg, s, b: sent.append(s) or True)
    monkeypatch.setattr(watchdog.config, "load", lambda: _FakeSettings(tmp_path / "gone.xlsx"))
    assert watchdog.run(today=date(2026, 8, 5)) == 0
    assert len(sent) == 1                            # a missing workbook is itself worth an e-mail


def test_watchdog_email_failure_is_not_fatal(tmp_path, monkeypatch):
    from mobile_tracker import watchdog

    def boom(*a, **k):
        raise OSError("smtp unreachable")

    monkeypatch.setattr(watchdog.alerts_mod, "send_alert_email", boom)
    monkeypatch.setattr(watchdog.config, "load", lambda: _FakeSettings(tmp_path / "gone.xlsx"))
    assert watchdog.run(today=date(2026, 8, 5)) == 0


def test_snapshot_date_is_the_sao_paulo_day_not_the_runners_utc_day(monkeypatch):
    """#38 follow-up. These are Brazilian prices, so a snapshot belongs to the São Paulo calendar
    day. CI runs on a UTC machine and the 21:00 UTC cron (18:00 BRT) lands on the same date in both
    zones — which hid this for 44 snapshots. A manual run at 21:18 BRT on 2026-08-05 was 00:18 UTC on
    the 6th, and got filed as `2026-08-06`: tomorrow's date, on prices that were already gone by
    then."""
    import mobile_tracker.main as main_mod

    class _S:
        timezone = "America/Sao_Paulo"

    ts = main_mod.project_now(_S())
    assert ts.tzinfo is None, "snapshot_ts must stay naive — every stored row uses that format"
    # BRT is UTC-3 year-round (Brazil dropped DST in 2019)
    from datetime import timezone as _tz
    delta = (datetime.now(_tz.utc).replace(tzinfo=None) - ts).total_seconds()
    assert 3 * 3600 - 120 < delta < 3 * 3600 + 120, f"expected ~UTC-3, got {delta/3600:.2f}h"


def test_project_now_falls_back_instead_of_failing_the_scrape(capsys):
    """A clock detail must never be the reason a day's prices are lost."""
    import mobile_tracker.main as main_mod

    class _Bad:
        timezone = "Mars/Olympus_Mons"

    ts = main_mod.project_now(_Bad())
    assert ts.tzinfo is None and abs((datetime.now() - ts).total_seconds()) < 5


class _FakeSettings:
    """Minimal stand-in for Settings — the watchdog only needs the workbook path and alert config."""
    def __init__(self, path):
        self.output_xlsx = path
        self.alerts = {"enabled": True, "from_email": "a@b.com", "to_email": "c@d.com",
                       "smtp_host": "smtp.x", "smtp_port": 587}


# --------------------------------------------------------------------------------------------
# cross-cutting: notification must never break collection
# --------------------------------------------------------------------------------------------
def test_alerts_still_degrade_gracefully_without_a_password(monkeypatch):
    monkeypatch.delenv("EMAIL_APP_PASSWORD", raising=False)
    cfg = {"from_email": "a@b.com", "to_email": "c@d.com", "smtp_host": "smtp.x", "smtp_port": 587}
    assert alerts.send_alert_email(cfg, "s", "b") is False
    assert format_alert_email([Alert("tim", "control", "A", "tim:1", 1.0, 2.0, 100.0)],
                              "2026-08-05", 3.0)[0]


# --------------------------------------------------------------------------------------------
# #40 — a carrier that REFUSES us must not cost the carriers that answered
# --------------------------------------------------------------------------------------------
def test_a_refused_carrier_does_not_block_the_ones_that_answered():
    """THE 2026-08-18 LOSS. TIM 403'd the GitHub runner, `tim: 0` tripped count_low, and Claro's 19
    + Vivo's 26 perfectly good plans were discarded with it — the day is unrecoverable. A carrier
    that never answered is a GAP; only a carrier that answered with junk is degraded data."""
    cfg = {"price_min_brl": 5, "price_max_brl": 2000,
           "carriers": {"claro": {"min_plans": 12, "max_plans": 32},
                        "vivo": {"min_plans": 16, "max_plans": 38},
                        "tim": {"min_plans": 12, "max_plans": 30}}}
    counts = {"claro": 19, "vivo": 26, "tim": 0}
    assert [i.kind for i in check_sanity(counts, [], cfg)] == ["count_low"]      # old behaviour
    assert check_sanity(counts, [], cfg, unavailable={"tim"}) == []              # #40: gap, not junk


def test_a_carrier_that_answered_with_junk_still_blocks():
    """The guardrail must not be weakened: 3 plans from a REACHABLE carrier means our parser or
    their page broke, and that must still stop the commit."""
    cfg = {"carriers": {"tim": {"min_plans": 12, "max_plans": 30}}}
    issues = check_sanity({"tim": 3}, [], cfg, unavailable=set())
    assert [i.kind for i in issues] == ["count_low"]


def test_unavailable_email_names_the_carrier_and_the_gap():
    subject, body = alerts.format_unavailable_email(
        ["tim"], ["tim/control/SP: RuntimeError: 403 Forbidden"], "2026-08-18")
    assert "CARRIER UNAVAILABLE" in subject and "TIM" in subject
    assert "403" in body and "never carried forward" in body


def test_catch_up_does_nothing_when_the_day_is_complete(tmp_path):
    """Politeness: the second daily pass must not re-scrape a source that already answered."""
    from mobile_tracker.main import snapshot_gaps
    out = tmp_path / "wb.xlsx"
    write_workbook(_stamp([P("tim", "control", "A", "tim:1", 50.0),
                           P("claro", "control", "B", "claro:1", 60.0),
                           P("vivo", "control", "C", "vivo:1", 70.0)], "2026-08-19"),
                   out, datetime(2026, 8, 19, 18))
    assert snapshot_gaps(out, "2026-08-19", {"tim", "claro", "vivo"}) == set()


def test_catch_up_targets_only_the_missing_carrier(tmp_path):
    from mobile_tracker.main import snapshot_gaps
    out = tmp_path / "wb.xlsx"
    write_workbook(_stamp([P("claro", "control", "B", "claro:1", 60.0),
                           P("vivo", "control", "C", "vivo:1", 70.0)], "2026-08-18"),
                   out, datetime(2026, 8, 18, 18))
    assert snapshot_gaps(out, "2026-08-18", {"tim", "claro", "vivo"}) == {"tim"}
    # a workbook we cannot read must not be mistaken for "all good"
    assert snapshot_gaps(tmp_path / "nope.xlsx", "2026-08-18", {"tim"}) == {"tim"}


def test_2026_08_18_replayed_end_to_end_now_commits(monkeypatch):
    """The whole point of #40, end to end through main.run(): TIM refuses every request (403), Claro
    and Vivo answer normally. Before: exit 4, nothing written, the day lost. After: the snapshot is
    written with the two carriers that answered, exit 0 so the workflow commits it."""
    import mobile_tracker.main as main_mod

    calls = {"written": None, "emails": []}

    class _Blocked:
        def __init__(self, settings): pass
        def fetch(self, target):
            raise RuntimeError("Client error '403 Forbidden' for url "
                               f"'https://www.tim.com.br/sp/...{target.category}'")

    class _Healthy:
        def __init__(self, settings): pass
        def fetch(self, target):
            n = {"claro": 5, "vivo": 7}[target.carrier]      # x4 categories -> 20 / 28, inside bands
            return [P(target.carrier, target.category, f"{target.carrier} {i}",
                      f"{target.carrier}:{target.category}:{i}", 50.0 + i) for i in range(n)]

    class _NoOffers:
        def __init__(self, settings): pass
        def fetch(self, target): return []

    monkeypatch.setattr(main_mod, "ADAPTERS",
                        {"tim": _Blocked, "claro": _Healthy, "vivo": _Healthy})
    registry = __import__("mobile_tracker.adapters", fromlist=["x"]).CONVERGENT_ADAPTERS
    for name in list(registry):
        monkeypatch.setitem(registry, name, _NoOffers)
    monkeypatch.setattr(alerts, "check_staleness", lambda *a, **k: None)
    monkeypatch.setattr(alerts, "send_alert_email",
                        lambda cfg, s, b: calls["emails"].append(s) or True)
    monkeypatch.setattr(main_mod, "write_workbook",
                        lambda plans, path, ts, convergent=None: calls.__setitem__("written", plans)
                        or {"path": str(path), "snapshot_date": "d", "plans_in_latest": len(plans),
                            "snapshots_in_history": 1, "changes": 0,
                            "convergent_rows": 0, "convergent_snapshots": 0})

    rc = main_mod.run(demo=False)

    assert rc == 0, "a refused carrier must not fail the run"
    assert calls["written"], "the carriers that answered must still be written"
    carriers = {p.carrier for p in calls["written"]}
    assert carriers == {"claro", "vivo"}          # TIM absent — an honest gap, not invented
    assert any("CARRIER UNAVAILABLE" in s for s in calls["emails"])
    assert not any("SANITY" in s for s in calls["emails"]), "this is a gap, not degraded data"


def test_catch_up_rescues_a_partial_day_into_the_same_date(tmp_path, monkeypatch):
    """#41 end to end: the 18:00 pass loses TIM to a 403 and commits claro+vivo. A later pass the
    same São Paulo evening finds TIM missing, scrapes ONLY TIM, and its rows land on the SAME
    snapshot_date — the day ends complete instead of permanently short a carrier."""
    import mobile_tracker.main as main_mod
    out = tmp_path / "wb.xlsx"

    # 18:00 pass: TIM refused, the others committed (the #40 behaviour)
    write_workbook(_stamp([P("claro", "control", "C", "claro:1", 60.0),
                           P("vivo", "control", "V", "vivo:1", 70.0)], "2026-08-19"),
                   out, datetime(2026, 8, 19, 18))
    assert main_mod.snapshot_gaps(out, "2026-08-19", {"tim", "claro", "vivo"}) == {"tim"}

    # 22:00 BRT catch-up: TIM answers this time
    class _Tim:
        def __init__(self, settings): pass
        def fetch(self, target):
            return [P("tim", target.category, f"T{i}", f"tim:{target.category}:{i}", 40.0 + i)
                    for i in range(5)]

    class _NeverCalled:
        def __init__(self, settings): pass
        def fetch(self, target):
            raise AssertionError("a carrier already present today must NOT be scraped again")

    monkeypatch.setattr(main_mod, "ADAPTERS",
                        {"tim": _Tim, "claro": _NeverCalled, "vivo": _NeverCalled})
    registry = __import__("mobile_tracker.adapters", fromlist=["x"]).CONVERGENT_ADAPTERS
    for name in list(registry):
        monkeypatch.setitem(registry, name, type("_N", (), {"__init__": lambda s, x: None,
                                                            "fetch": lambda s, t: []}))
    monkeypatch.setattr(alerts, "check_staleness", lambda *a, **k: None)
    monkeypatch.setattr(alerts, "send_alert_email", lambda *a, **k: True)
    monkeypatch.setattr(alerts, "check_sanity", lambda *a, **k: [])      # bands are not the subject
    monkeypatch.setattr(main_mod, "project_now",
                        lambda s: datetime(2026, 8, 19, 22, 0))          # 22:00 BRT, same SP day

    class _S:
        pass
    real_load = main_mod.config.load

    def _load():
        s = real_load()
        s.raw["project"] = dict(s.raw.get("project", {}), output_xlsx=str(out))
        object.__setattr__(s, "_out", str(out))
        return s
    monkeypatch.setattr(main_mod.config, "load", _load)
    monkeypatch.setattr(type(real_load()), "output_xlsx", property(lambda self: str(out)))

    rc = main_mod.run(demo=False, only_if_incomplete=True)
    assert rc == 0

    hist = pd.read_excel(out, sheet_name="history", dtype={"snapshot_date": str})
    day = hist[hist.snapshot_date == "2026-08-19"]
    assert set(day.carrier) == {"claro", "vivo", "tim"}, "the day must end complete"
    assert set(hist.snapshot_date) == {"2026-08-19"}, "the rescue must not create a second date"
    assert main_mod.snapshot_gaps(out, "2026-08-19", {"tim", "claro", "vivo"}) == set()


def _catchup_env(monkeypatch, out, mobile_adapters, conv_adapters, when):
    """Wire main.run() for a catch-up pass against `out`, with the given adapters."""
    import mobile_tracker.main as main_mod
    monkeypatch.setattr(main_mod, "ADAPTERS", mobile_adapters)
    registry = __import__("mobile_tracker.adapters", fromlist=["x"]).CONVERGENT_ADAPTERS
    for name in list(registry):
        monkeypatch.setitem(registry, name, conv_adapters.get(name, type(
            "_N", (), {"__init__": lambda s, x: None, "fetch": lambda s, t: []})))
    monkeypatch.setattr(alerts, "check_staleness", lambda *a, **k: None)
    monkeypatch.setattr(alerts, "send_alert_email", lambda *a, **k: True)
    monkeypatch.setattr(alerts, "check_sanity", lambda *a, **k: [])
    monkeypatch.setattr(main_mod, "project_now", lambda s: when)
    from mobile_tracker.config import Settings
    monkeypatch.setattr(Settings, "output_xlsx", property(lambda self: str(out)))
    return main_mod


def test_catch_up_does_not_wipe_todays_combo_rows(tmp_path, monkeypatch):
    """The convergent twin of the merge trap. `_merge_convergent` also replaces a date's rows, so a
    catch-up that re-scraped only the missing combo source would delete the ones already collected
    today."""
    out = tmp_path / "wb.xlsx"
    write_workbook(_stamp([P("claro", "control", "C", "claro:1", 60.0)], "2026-08-19"),
                   out, datetime(2026, 8, 19, 18),
                   convergent=_stamp([O("vivo", "V Total", "vivo:t1", 160.0),
                                      O("claro", "Multi", "claro:m1", 129.8)], "2026-08-19"))

    class _Tim:
        def __init__(self, settings): pass
        def fetch(self, target):
            return [P("tim", target.category, "T", f"tim:{target.category}", 45.0)]

    class _TimConv:
        def __init__(self, settings): pass
        def fetch(self, target):
            return [O("tim", "Ultracombo", "tim:u1", 89.99)]

    main_mod = _catchup_env(monkeypatch, out, {"tim": _Tim, "claro": _Tim, "vivo": _Tim},
                            {"tim_ultracombo": _TimConv}, datetime(2026, 8, 19, 22))
    assert main_mod.run(demo=False, only_if_incomplete=True) == 0

    conv = pd.read_excel(out, sheet_name="convergent_history", dtype={"snapshot_date": str})
    day = conv[conv.snapshot_date == "2026-08-19"]
    assert set(day.carrier) == {"vivo", "claro", "tim"}, "existing combo rows must survive the rescue"


def test_catch_up_does_not_rescrape_combo_sources_that_already_answered(tmp_path, monkeypatch):
    """Politeness: with all three combo sources already collected today, a catch-up must not touch
    them — otherwise the three extra nightly passes mean 4 scrapes a day per source."""
    out = tmp_path / "wb.xlsx"
    write_workbook(_stamp([P("claro", "control", "C", "claro:1", 60.0)], "2026-08-19"),
                   out, datetime(2026, 8, 19, 18),
                   convergent=_stamp([O("vivo", "V", "vivo:1", 160.0),
                                      O("claro", "C", "claro:1", 129.8),
                                      O("tim", "T", "tim:1", 89.99)], "2026-08-19"))

    class _Mobile:
        def __init__(self, settings): pass
        def fetch(self, target):
            return [P("tim", target.category, "T", f"tim:{target.category}", 45.0)]

    # NOTE: raising here would prove nothing — the convergent loop catches every per-source
    # exception by design (§14), so an AssertionError would be swallowed and logged and the test
    # would pass even with the guard removed. Record the calls instead. (Found by mutation testing.)
    touched = []

    class _Recorder:
        def __init__(self, settings): pass
        def fetch(self, target):
            touched.append(target.carrier)
            return []

    main_mod = _catchup_env(monkeypatch, out, {"tim": _Mobile, "claro": _Mobile, "vivo": _Mobile},
                            {n: _Recorder for n in ("tim_ultracombo", "vivo_total", "claro_multi")},
                            datetime(2026, 8, 19, 22))
    assert main_mod.run(demo=False, only_if_incomplete=True) == 0
    assert touched == [], f"combo sources already collected today were re-scraped: {touched}"


def test_catch_up_is_not_a_failure_when_the_carrier_is_still_blocked(tmp_path, monkeypatch):
    """A retry that finds the carrier still refusing must exit 0 — the day keeps what it has, and a
    red X three times a night would be noise, not information."""
    out = tmp_path / "wb.xlsx"
    write_workbook(_stamp([P("claro", "control", "C", "claro:1", 60.0),
                           P("vivo", "control", "V", "vivo:1", 70.0)], "2026-08-19"),
                   out, datetime(2026, 8, 19, 18))

    class _StillBlocked:
        def __init__(self, settings): pass
        def fetch(self, target):
            raise RuntimeError("Client error '403 Forbidden' for url '...'")

    main_mod = _catchup_env(monkeypatch, out,
                            {"tim": _StillBlocked, "claro": _StillBlocked, "vivo": _StillBlocked},
                            {}, datetime(2026, 8, 19, 23, 30))
    assert main_mod.run(demo=False, only_if_incomplete=True) == 0
    hist = pd.read_excel(out, sheet_name="history", dtype={"snapshot_date": str})
    assert set(hist[hist.snapshot_date == "2026-08-19"].carrier) == {"claro", "vivo"}
