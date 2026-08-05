"""TIM adapter — live plan scraping via the embedded Drupal settings JSON.

RECON (verified 2026-06-19, CONTEXT §3): TIM is server-rendered Drupal (Acquia Site Studio).
A plain ``httpx`` GET returns **200** (no anti-bot block). The page DOM is noisy (marketing
components with per-instance UUID classes, plus device sales), and the page has **no clean
plan-card class and no <table>**. BUT the structured plan grid is embedded as JSON in:

    <script data-drupal-selector="drupal-settings-json" type="application/json"> … </script>
        → settings["ofertas"][]   # one object per plan card

Per oferta:
  * price → ``field_preco_card_oferta`` (a clean text value, e.g. "64,99") — **no SVG/OCR needed**.
  * name  → ``title`` (e.g. "1 Card - TIM Controle Plus 45GB - [PROD]"); we strip the "N Card -"
            prefix and the "[PROD]"/"[On Air …]" tags → "TIM Controle Plus 45GB". ``field_nome_da_oferta``
            is the bare name (no GB) and is used only as a fallback.
  * data_gb → parsed from the cleaned title.

SVG note (the recon's "prices in images" concern): the **hero banner** price IS in an SVG ``alt``
(e.g. control "45GB por R$64,99", postpaid "Lê-se: a partir de 169 e 99"), but that's only the
marketing headline — the actual **per-plan prices come from the JSON text above**, so OCR is NOT
required. State is in the URL path (``/sp/…``, templated by config) — no geolocation step.
"""
from __future__ import annotations

import json
import random
import re
import time
from pathlib import Path

import httpx
from selectolax.parser import HTMLParser

from .base import BaseAdapter, slugify
from ..config import Target
from ..models import Plan

_GB = re.compile(r"(\d+)\s*GB", re.I)
# Per-oferta prepaid validity: each oferta's OWN "R$<recarga> … (por | válido[s] por) <N> dias". A shared
# marketing line ("recarga de R$30 válidos por 30 dias") appears in EVERY oferta, so #18's MAX-"N dias"
# wrongly inflated all to 30. We match THIS oferta's recarga amount. Audit #22: R$20→17, R$25→22, R$30→30.
_TIM_TIER = re.compile(r"R\$\s*(\d+)[^\d]{0,45}?(?:por|v[aá]lid[oa]s?\s+por)\s+(\d+)\s*dias", re.I)
# Postpaid billing type (#24): the oferta's `field_preco_principal_7_1_3` PRICE HEADLINE reads
# "R$ <price>/mês no cartão" (recurring CREDIT CARD — TIM's cheaper "Express" line, low adoption) OR
# "R$ <price>/mês na fatura" (paid on the INVOICE/bill). We anchor to the "/mês <phrase>" clause so stray
# marketing/benefits text elsewhere in the (full-HTML) blob — e.g. a "pague no cartão" promo or a "12x no
# cartão" assinatura line — can NOT flip the classification (a bill plan must never be misread as
# credit_card, which would wrongly drop it from the entry-level pick). Verified live (SP, 2026-07): all 7
# plans have exactly one "/mês <phrase>" in the headline. The postpaid matrix pick excludes "credit_card"
# (JPMorgan rule; the bill-payment plan wins). (#24; anchored after adversarial review)
_PAY_HEADLINE = re.compile(r"/\s*m[eê]s\s+(no\s+cart[aã]o|na\s+fatura)", re.I)


def _payment_method(oferta: dict) -> str | None:
    """TIM postpaid billing type from the `field_preco_principal_7_1_3` price headline: "/mês no cartão"
    → "credit_card" (requires a recurring credit card — the cheaper "Express" line), "/mês na fatura" →
    "bill". Anchored to the "/mês" clause so only the price line — not stray card/fatura words in the
    benefits HTML — decides. None if the headline is absent/ambiguous (→ the plan is NOT excluded from the
    entry-level pick, the safe default). (#24)"""
    m = _PAY_HEADLINE.search(_field(oferta, "field_preco_principal_7_1_3") or "")
    if not m:
        return None
    return "credit_card" if "cart" in m.group(1).lower() else "bill"


def _prepaid_validity(oferta_text: str, price: float | None) -> int | None:
    """Validity (days) for THIS prepaid oferta = the "R$<recarga> … por <N> dias" phrase whose recarga
    matches the oferta's own price — NOT the max "N dias" anywhere (the #18 bug: a shared 30-day line
    inflated every oferta to 30). Returns None if no matching phrase (cell stays blank). (#22/#23)"""
    if price is None:
        return None
    pairs: dict[int, int] = {}
    for p, d in _TIM_TIER.findall(oferta_text):
        pairs.setdefault(int(p), int(d))          # first N-dias seen per recarga amount
    return pairs.get(int(price))


def _price_brl(value) -> float | None:
    """'64,99' → 64.99 ; 'R$ 1.234,56' → 1234.56."""
    if not value:
        return None
    m = re.search(r"(\d[\d.]*),(\d{2})", str(value))
    if not m:
        return None
    return float(f"{m.group(1).replace('.', '')}.{m.group(2)}")


def _field(obj: dict, key: str) -> str | None:
    """Drupal serializes fields as ``[{'value': ...}]`` (or sometimes a bare string)."""
    v = obj.get(key)
    if isinstance(v, list) and v and isinstance(v[0], dict):
        return v[0].get("value")
    return v if isinstance(v, str) else None


def _clean_title(title) -> str:
    if isinstance(title, list):
        title = title[0].get("value") if title and isinstance(title[0], dict) else ""
    title = title or ""
    t = re.sub(r"\[[^\]]*\]", "", title)              # drop "[PROD]" / "[On Air - SP, …]" tags
    t = re.sub(r"^\s*\d+\s*Card\s*-\s*", "", t)        # drop leading "N Card -"
    t = re.sub(r"\s*-\s*", " ", t)                     # dashes → spaces ("TIM Black - 70GB" → "TIM Black 70GB")
    return re.sub(r"\s+", " ", t).strip()


def _iter_ofertas(settings: dict) -> list[dict]:
    """All objects carrying ``field_preco_card_oferta`` anywhere in the settings tree."""
    out: list[dict] = []

    def walk(o):
        if isinstance(o, dict):
            if "field_preco_card_oferta" in o:
                out.append(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(settings)
    return out


# --- TIM Controle Fit — TIM's digital line (Digital peer of Vivo Lite / Claro Flex) -------------------
# The Fit plans are NOT in the drupal-settings `ofertas` JSON; they live ON the controle page as a
# server-rendered marketing section (anchor id="price-fit").
#
# ⚠️ REBUILT BY TIM ~2026-08-03 — the #35 audit caught the fallout (see docs/source_audit_2026-08.md).
# The section is now **2 regional blocks × 2 tier-versions × 2 plan types = 8 cards**, each card linked
# to its own benefits modal by `data-modal-open="modal-fit-<anual|mensal>-<version>-<regions>"`, e.g.
# `modal-fit-anual-2.0-sp-sc-rn-ce` and `modal-fit-anual-2.0-demais-ufs`. The old code searched for the
# literal ids `modal-fit-anual` / `modal-fit-mensal` (now absent → the etiqueta plan_id silently
# degraded to a name slug) and took the FIRST "Tenha …" phrase in the whole section (→ it captured a
# different, newly-inserted "1.0" offer). Between them those two bugs produced this project's only
# price alert, which was FALSE. (#36)
#
# The parse is now driven by `data-modal-open`, which is the authoritative card→modal link:
#   * REGION GATE — the modal id's trailing region list. `…-sp-sc-rn-ce` serves SP/SC/RN/CE;
#     `…-demais-ufs` serves every other state. NOTE: the Fit section carries NO `field_regioes` (that
#     field only exists on `ofertas` JSON nodes), so the modal-id region list is the only real gate the
#     page offers — `rel=canonical` is state-less and DOM order is not a gate at all.
#   * plan_id — the etiqueta code inside THAT card's own modal slice (`TIM2026…`), carrier-native and
#     never price-derived. The four SP cards carry four distinct etiquetas.
#   * loyalty — see `_FIT_TIERS` below; the page's own "sem prazo de permanência" wording is recorded
#     in the note because it disagrees with how we model the annual plan (documented, not silently
#     resolved).
_FIT_MODAL = re.compile(r'data-modal-open="(modal-fit-(anual|mensal)-([\d.]+)-([a-z-]+))"', re.I)
_FIT_OFFER = re.compile(
    r"Tenha\s*(\d+)\s*GB\s*por\s*(12x\s*)?R\$\s*(\d+(?:[.,]\d{1,2})?)\s*/\s*m[êe]s", re.I)
_FIT_NAME = re.compile(r"(TIM\s+Controle\s+Fit\s+(?:Anual|Mensal)\s*[\d.]*)", re.I)
_FIT_CODE = re.compile(r"TIM\d{12,}")
_FIT_MODAL_PRICE = re.compile(r"R\$\s*(\d+(?:[.,]\d{1,2})?)\s*(?:por\s*m[êe]s|/\s*m[êe]s)", re.I)
_DEMAIS = "demais-ufs"


def _fit_price(s: str) -> float:
    """'30' → 30.0 ; '34,99' → 34.99 ; '34.99' → 34.99. The regex's ``[.,]\\d{1,2}`` tail is ALWAYS a
    decimal separator (the integer part carries no thousands dots), so a dot is never stripped —
    stripping it would 100x the price ('35.90' → 3590). (#28, adversarial-review fix)"""
    return float(s.replace(",", "."))


def _fit_serves_state(regions: str, state: str) -> bool:
    """Does a Fit modal's region list serve `state`? ``sp-sc-rn-ce`` → {sp, sc, rn, ce}; the catch-all
    ``demais-ufs`` serves any state NOT named by a sibling block. Callers pass the sibling region lists
    so the catch-all can be resolved correctly. (#36)"""
    return state.lower() in {t for t in regions.lower().split("-") if t}


def _fit_code_in(section: str, modal_id: str) -> str | None:
    """The etiqueta code inside THIS card's modal slice, bounded by the next ``id="modal-`` so an
    adjacent modal's code can never bleed in (#28 review; #36 keeps the bound, new id pattern)."""
    start = section.find(f'id="{modal_id}"')
    if start == -1:
        return None
    end = section.find('id="modal-', start + 1)
    m = _FIT_CODE.search(section[start:end if end != -1 else start + 80_000])
    return m.group(0) if m else None


def _fit_modal_price(section: str, modal_id: str) -> float | None:
    """The price stated INSIDE the card's own modal — used only to cross-check the card headline and
    flag a disagreement in the note (never to silently override what the page shows). (#36)"""
    start = section.find(f'id="{modal_id}"')
    if start == -1:
        return None
    end = section.find('id="modal-', start + 1)
    text = " ".join(HTMLParser(section[start:end if end != -1 else start + 80_000])
                    .text(separator=" ", strip=True).split())
    m = _FIT_MODAL_PRICE.search(text)
    return _fit_price(m.group(1)) if m else None


def parse_tim_fit_html(html: str, target: Target, raw_ref: str | None = None) -> list[Plan]:
    """Pure mapping: the controle page's #price-fit SECTION → the TIM Controle Fit plans **for this
    target's state** (#28, rebuilt in #36). Text-parsed, NOT the ofertas JSON — the Fit cards aren't in
    it. Returns [] if the section is absent (site restructure) — never a crash; the FETCH path prints a
    loud warning on an empty fit parse, since main's zero-count guard is per-CARRIER only and TIM's
    other categories would mask the loss.

    Each card is anchored on its own ``data-modal-open`` link, so a card can only ever be paired with
    ITS OWN price, name and etiqueta — the #36 fix for the first-match-wins bug that captured a
    different tier's price. All tier-versions served to the state are captured (SP currently has 4:
    Anual 1.0/2.0 and Mensal 1.0/2.0).

    Entry-level policy: the ANUAL versions are billed **12x on a credit card**, so they carry
    ``loyalty_months=12`` + ``payment_method="credit_card"`` and the Digital matrix pick — no-commitment
    plans only — reads the MENSAL versions. ⚠️ The page itself labels EVERY Fit etiqueta (annual ones
    included) *"sem prazo de permanência"*; we model the 12x annual commitment the same way Vivo's
    "Plano anual 12x no cartão" is modelled (#26) so the two carriers stay comparable, and we record
    the carrier's own wording in the note rather than silently discarding it."""
    start = html.find('id="price-fit"')
    if start == -1:
        return []
    section = html[start:]                                   # through the fit modals at the page tail

    cards = list(_FIT_MODAL.finditer(section))
    if not cards:
        return []
    # REGION GATE: prefer a block that names this state; otherwise the "demais-ufs" catch-all. Never
    # fall back to "all cards" — an ungated parse silently mixes another region's prices into SP.
    state = (target.state or "").lower()
    regions = {m.group(4).lower() for m in cards}
    if any(_fit_serves_state(r, state) for r in regions):
        wanted = {r for r in regions if _fit_serves_state(r, state)}
    elif _DEMAIS in regions:
        wanted = {_DEMAIS}
    else:
        return []

    plans: list[Plan] = []
    seen: set[str] = set()
    for i, m in enumerate(cards):
        modal_id, kind, version, region = m.group(1), m.group(2).lower(), m.group(3), m.group(4).lower()
        if region not in wanted:
            continue
        # The card's own copy is the text immediately BEFORE its modal link, bounded by the previous
        # card's link so a neighbouring card's phrase can never be picked up.
        lo = cards[i - 1].end() if i else 0
        blob = " ".join(HTMLParser(section[lo:m.start()]).text(separator=" ", strip=True).split())
        offer = None
        for offer in _FIT_OFFER.finditer(blob):
            pass                                    # the LAST phrase before the link is this card's
        if offer is None:
            continue
        names = _FIT_NAME.findall(blob)
        label = kind.capitalize()
        name = " ".join(names[-1].split()) if names else f"TIM Controle Fit {label} {version}"

        code = _fit_code_in(section, modal_id)
        plan_id = f"tim:{code}" if code else f"tim:fit-{kind}-{version}-{region}"
        if plan_id in seen:                          # never collide (etiquetas repeat across regions)
            plan_id = f"tim:fit-{kind}-{version}-{region}"
        seen.add(plan_id)

        price = _fit_price(offer.group(3))
        installments = bool(offer.group(2))          # "12x" present → the annual, credit-card plan
        note = ("plano anual 12x no cartão de crédito" if installments
                else "plano mensal, sem prazo de permanência")
        note += "; a etiqueta TIM informa 'sem prazo de permanência'"
        # Cross-check against the card's OWN modal and REPORT a disagreement instead of picking one
        # silently (GOVERNANCE: never invent a number). SP's Mensal 1.0 card reads R$20 while its modal
        # still reads R$35 — the card is what an SP visitor is shown, so the card wins and we say so.
        mp = _fit_modal_price(section, modal_id)
        if mp is not None and abs(mp - price) > 0.005:
            note += (f"; ATENÇÃO: o card exibe R$ {price:g} mas o modal da oferta informa R$ {mp:g} "
                     f"(registrado o valor do card)")

        plans.append(BaseAdapter.make_plan(
            target,
            plan_name=name,
            plan_id=plan_id,
            price_brl=price,
            price_note=note,
            data_gb=float(offer.group(1)),
            loyalty_months=12 if installments else None,
            payment_method="credit_card" if installments else None,
            raw_ref=raw_ref,
        ))
    return plans


def parse_tim_html(html: str, target: Target, raw_ref: str | None = None) -> list[Plan]:
    """Pure mapping: TIM page HTML → list[Plan] (reads the embedded drupal-settings JSON). No network.
    The `fit` category routes to the #price-fit TEXT parser (#28) — those plans aren't in the JSON."""
    if target.category == "fit":
        return parse_tim_fit_html(html, target, raw_ref=raw_ref)
    node = HTMLParser(html).css_first('script[data-drupal-selector="drupal-settings-json"]')
    if node is None:
        return []
    try:
        settings = json.loads(node.text())
    except (json.JSONDecodeError, TypeError):
        return []

    plans: list[Plan] = []
    seen: set[str] = set()
    for o in _iter_ofertas(settings):
        price = _price_brl(_field(o, "field_preco_card_oferta"))
        name = _clean_title(o.get("title")) or _field(o, "field_nome_da_oferta")
        if not name or price is None:
            continue
        gb = _GB.search(name)
        data_gb = float(gb.group(1)) if gb else None
        # PREPAID only: validity has NO clean structured field — it's in the oferta's benefits text
        # ("R$20, válidos por 17 dias"). Parse THIS oferta's own recarga→days (not the max — see
        # _prepaid_validity / #22). Gated on category so postpaid/control parsing is untouched.
        validity_days = None
        if target.category == "prepaid":
            validity_days = _prepaid_validity(json.dumps(o, ensure_ascii=False), price)
        # POSTPAID only (#24): tag the billing type ("credit_card" vs "bill"). Gated on category so
        # control/prepaid parsing is untouched. The matrix Post pick uses it to exclude credit-card-only.
        payment_method = None
        if target.category == "postpaid":
            payment_method = _payment_method(o)
        # native Drupal node id (e.g. "155891"); fall back to the SKU field, then a name slug
        nid = _field(o, "nid")
        if nid and str(nid).strip():
            plan_id = f"tim:{nid}"
        else:
            sku = _field(o, "field_sku")
            plan_id = f"tim:{sku}" if sku else f"tim:{slugify(name)}"
        if plan_id in seen:
            continue
        seen.add(plan_id)
        # promo: field_preco_adicional_tracejado is the struck-through regular price (empty when none)
        regular = _price_brl(_field(o, "field_preco_adicional_tracejado"))
        if regular and regular != price:
            price_brl, price_promo, note = regular, price, "oferta com desconto"
        else:
            price_brl, price_promo, note = price, None, None
        plans.append(BaseAdapter.make_plan(
            target, plan_name=name, plan_id=plan_id, price_brl=price_brl,
            price_promo_brl=price_promo, price_note=note, data_gb=data_gb,
            validity_days=validity_days, payment_method=payment_method, raw_ref=raw_ref))
    return plans


class TimAdapter(BaseAdapter):
    carrier = "tim"

    def fetch(self, target: Target) -> list[Plan]:
        time.sleep(random.uniform(self.cfg.get("min_delay_seconds", 2),
                                  self.cfg.get("max_delay_seconds", 6)))
        headers = {"User-Agent": self.cfg.get("user_agent", "")}
        timeout = self.cfg.get("request_timeout_seconds", 30)

        last_err: Exception | None = None
        for attempt in range(2):  # one retry
            try:
                resp = httpx.get(target.url, headers=headers, timeout=timeout, follow_redirects=True)
                resp.raise_for_status()
                break
            except httpx.HTTPError as e:
                last_err = e
                if attempt == 0:
                    time.sleep(2)
        else:
            raise RuntimeError(f"TIM {target.url}: request failed: {last_err}")

        raw_ref = self._save_raw(target, resp.text)
        plans = parse_tim_html(resp.text, target, raw_ref=raw_ref)
        if target.category == "fit" and not plans:
            # Loud CI-log trace (#28 review): the fit section is text-parsed marketing markup — if TIM
            # restructures it, this target silently parses to 0 while TIM's other categories keep the
            # per-carrier zero-guard in main from firing. Not fatal (collection > notification).
            print(f"WARNING tim/fit: no plans parsed from {target.url} - "
                  f"#price-fit section missing or restructured?")
        return plans

    def _save_raw(self, target: Target, html: str) -> str:
        d = Path(self.settings.raw_capture_dir)
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"tim_{target.category}_{target.state}.html"
        path.write_text(html, encoding="utf-8")
        return str(path)

    @classmethod
    def demo_plans(cls, target: Target) -> list[Plan]:
        if target.category != "prepaid" or target.state != "SP":
            return []
        # Prepaid is priced per top-up (recarga); model the headline recarga as price_brl.
        return [
            Plan(carrier="tim", category="prepaid", state="SP",
                 plan_name="TIM Pré XIP — recarga R$30", price_brl=30.00,
                 data_gb=16.0, data_note="16GB total, 4GB redes sociais; validade 30 dias",
                 unlimited_apps="WhatsApp", voice="Ligações e SMS ilimitadas",
                 source_url=target.url,
                 price_note="recarga mínima p/ benefício (recon 2026-06-11)"),
        ]
