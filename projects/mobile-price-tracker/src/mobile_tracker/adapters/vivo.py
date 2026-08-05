"""Vivo adapter — live plan scraping via Playwright (AEM blocks plain requests).

RECON (verified 2026-06-19, CONTEXT §3):
A plain ``httpx`` GET returns **403** (anti-bot challenge page, ~6KB, no prices); appending
``.model.json`` is also 403. A **real headless Chromium (Playwright)** loads the page (HTTP 200,
~1MB) and renders the plan grid — no CAPTCHA is presented. There is no clean embedded JSON blob,
so we scrape the rendered DOM. The plan grid is the ``.unique-card`` component; per card:

  * name  → ``.unique-card__plan``            (e.g. "Vivo Pós com Amazon")
  * price → ``.total-card-price-value``       (e.g. "150"; the visible ``{{ total }}`` template
                                               in ``.unique-card__price`` is unrendered — ignore it)
  * data  → ``.unique-card__header-benefit``  (e.g. "60 GB")
  * franquia/bônus → ``.unique-card__switch-list``;  co-branded bundle (Netflix/Disney+/Amazon…)
                     is in the plan name and ``.unique-card__features-cobranded-title``.

FULL DETAIL (§10.2): the rendered card already contains the franquia/bonus + co-branded detail,
so a single page load (no per-card "ver mais" clicking) is enough for the headline fields.
State defaults to São Paulo/SP via geolocation; ``state`` comes from the Target, not the page.
"""
from __future__ import annotations

import random
import re
import time
from pathlib import Path

from selectolax.parser import HTMLParser

from .base import BaseAdapter, slugify, fetch_with_retry
from ..config import Target
from ..models import Plan

_GB = re.compile(r"(\d+)\s*GB", re.I)
_DAYS = re.compile(r"(\d+)\s*dias", re.I)   # prepaid validity in the card text ("30 dias") — #18
# native offer code (the "Baixar condições da oferta VIV…" code, unique per card; SELF… is a fallback)
_VIV = re.compile(r"VIV\d{6,}")
_SELF = re.compile(r"SELF\d{3,}[A-Z0-9]*")
_STREAMING = ("netflix", "disney", "globoplay", "spotify", "premiere", "max", "paramount", "prime video")


def _clean(text: str | None) -> str:
    return " ".join(text.split()) if text else ""


def _price_from(text: str | None) -> float | None:
    """'150' → 150.0 ; '1.329,05' → 1329.05 ; '24,99' → 24.99."""
    if not text:
        return None
    m = re.search(r"\d[\d.]*(?:,\d{2})?", text)
    if not m:
        return None
    raw = m.group(0)
    if "," in raw:
        return float(raw.replace(".", "").replace(",", "."))
    return float(raw.replace(".", ""))


def _addon_gb(card) -> float | None:
    """The DATA the pre-checked add-on contributes, from the switch's own text
    ("+ 10 GB para suas redes sociais e vídeo por R$ 5") — None when it can't be read.

    Needed because `.unique-card__header-benefit` reports the add-on-INCLUSIVE allowance: the same
    card family reads "46 GB" with the switch unchecked and "61 GB" with it checked (51 base + 10).
    Storing the base PRICE next to the inclusive GB would describe a plan that isn't sold."""
    sw = card.css_first('[data-controller="switchUnique"]')
    if sw is None:
        return None
    # PRIMARY: the switch's own machine-readable amount, base64 ("MTA=" -> "10"), alongside
    # data-price-bonus ("NQ==" -> "5"). Preferred over the label because it can't be reworded.
    raw = sw.attributes.get("data-gb-bonus")
    if raw:
        try:
            import base64
            return float(re.sub(r"[^\d.]", "", base64.b64decode(raw).decode("utf-8", "ignore")))
        except Exception:                                 # malformed attr -> fall through to the label
            pass
    m = re.search(r"\+\s*(\d+)\s*GB", sw.text() or "", re.I)
    return float(m.group(1)) if m else None


def _addon_base_price(card, price_el, shown: float | None) -> float | None:
    """The plan's price WITHOUT a pre-selected optional add-on, or None when no such add-on is on
    this card (#37).

    Vivo cards carry an add-on switch (``[data-controller="switchUnique"]``) whose
    ``data-startdisabled`` is ``"checked"`` when the extra is pre-selected. In that state the visible
    ``.total-card-price-value`` text is base+add-on while ``data-original-price`` holds the plan's own
    price. We only trust that attribute when the switch really is pre-checked AND the attribute is
    *lower* than the displayed figure — so a page without the add-on, or any other reason the two
    differ, falls through to the ordinary promo handling instead of silently reinterpreting a price."""
    if price_el is None or shown is None:
        return None
    sw = card.css_first('[data-controller="switchUnique"]')
    pre_checked = sw is not None and str(sw.attributes.get("data-startdisabled", "")).lower() == "checked"
    if not pre_checked:
        pre_checked = any("checked" in (i.attributes or {}) for i in card.css('input[type="checkbox"]'))
    if not pre_checked:
        return None
    base = _price_from(price_el.attributes.get("data-original-price"))
    return base if (base is not None and base < shown) else None


def parse_vivo_html(html: str, target: Target, raw_ref: str | None = None) -> list[Plan]:
    """Pure mapping: rendered Vivo HTML → list[Plan]. selectolax only, no network — unit-testable."""
    tree = HTMLParser(html)
    plans: list[Plan] = []
    seen: set[str] = set()

    for card in tree.css(".unique-card"):
        plan_el = card.css_first(".unique-card__plan")
        name = _clean(plan_el.text()) if plan_el else ""
        price_el = card.css_first(".total-card-price-value")
        price = _price_from(price_el.text()) if price_el is not None else None
        if not name or price is None:
            continue

        ben = card.css_first(".unique-card__header-benefit")
        gb = _GB.search(ben.text()) if ben is not None else None
        data_gb = float(gb.group(1)) if gb else None

        # PREPAID only (#18): the recarga validity ("30 dias") is in the card text. Gated on category
        # so postpaid/control/lite parsing is untouched (their cards may mention "dias" for trials).
        validity_days = None
        if target.category == "prepaid":
            dm = _DAYS.search(card.text(separator=" ", strip=True) or "")
            validity_days = int(dm.group(1)) if dm else None

        # plan_id — STABLE, carrier-native, and free of any parsed GB or price (#37).
        # It used to be `{code}-{data_gb}gb`, which made the id depend on a PARSED, VOLATILE number:
        # Vivo Controle cards carry a pre-checked "+10 GB" add-on whose render varies, so the same
        # offer alternated between `…-61gb` and `…-51gb`, the id-match failed, and the alert emitted
        # ±5 % lines that reversed the next day — 79 % of ALL alert noise (#35 audit).
        # The VIV code is unique PER CARD on control / lite / postpaid (verified 2026-08-05: 8/3/11
        # distinct codes for 8/3/11 cards), so it stands alone. Only PREPAID shares one page-level
        # code across its tiers; there the tier's defining attribute is the recarga VALIDITY (15/17/
        # 22/30 d) — an attribute, not a price and not the add-on-inflated GB.
        code = _VIV.search(card.html or "") or _SELF.search(card.html or "")
        base = code.group(0) if code else slugify(name)
        if target.category == "prepaid":
            tok = f"{int(validity_days)}d" if validity_days else slugify(name)
            plan_id = f"vivo:{base}-{tok}"
        else:
            plan_id = f"vivo:{base}"

        loyalty_months = None
        if target.category == "lite":
            # Vivo Lite (#23): Easy Lite has an annual/monthly toggle. The render clicks "Sem fidelidade"
            # so the displayed price (`.total-card-price-value` text) is the NO-COMMITMENT monthly (~R$45),
            # while `data-original-price` keeps the 12-month LOYALTY price (~R$30). Headline = the no-strings
            # monthly (JPMorgan comparability); loyalty kept as the promo. Cards without the toggle are
            # single-price (text == data-original-price → no promo).
            attrs = price_el.attributes if price_el is not None else {}
            loyalty = _price_from(attrs.get("data-original-price"))
            if loyalty and loyalty != price:
                price_brl, price_promo, loyalty_months = price, loyalty, 12
                note = "preço sem fidelidade; fidelidade 12m no promo"
            else:
                price_brl, price_promo, note = price, None, None
        else:
            # PRE-CHECKED PAID ADD-ON (#37): Vivo Controle cards ship a "+ 10 GB para suas redes
            # sociais … R$ 5" switch that is ALREADY selected, so `.total-card-price-value` shows
            # base+add-on (80 where the plan is 75; also 90/85, 95/90, 110/105) while the plan's own
            # price sits in `data-original-price`. The #35 audit found 7 of 8 Controle headlines were
            # therefore wrong. The HEADLINE is the plan without the optional add-on; the
            # add-on-inclusive figure is kept in the note, never as the price.
            # (This is the mirror image of `lite` above, where the displayed text is the value we want
            # and `data-original-price` is the loyalty price — hence the category split.)
            addon = _addon_base_price(card, price_el, price)
            if addon is not None:
                price_brl, price_promo = addon, None
                note = (f"preço-base do plano; a tela exibia R$ {price:g} com o adicional "
                        f"pré-selecionado (+R$ {price - addon:g}/mês, opcional)")
                # ⚠️ The GB must come off with the price. `.unique-card__header-benefit` reports the
                # add-on-INCLUSIVE allowance (the same card family reads 46 GB unchecked and 61 GB
                # checked = 51 + 10), so keeping 61 next to the base R$75 would describe a plan Vivo
                # does not sell — and would silently corrupt any future R$/GB value lens. Only
                # subtract when both numbers are readable and the result stays positive.
                gb_extra = _addon_gb(card)
                if gb_extra and data_gb and data_gb > gb_extra:
                    note += f"; {data_gb:g} GB na tela incluem +{gb_extra:g} GB do adicional"
                    data_gb = data_gb - gb_extra
            else:
                # promo: a struck-through original price in .unique-card__price-old (hidden when none)
                old_el = card.css_first(".unique-card__price-old")
                old = _price_from(old_el.text()) if old_el is not None else None
                if old and old != price:
                    price_brl, price_promo, note = old, price, "oferta com desconto"
                else:
                    price_brl, price_promo, note = price, None, None

        switch = card.css_first(".unique-card__switch-list")
        data_note = _clean(switch.text()) if switch is not None else None

        bundle = None
        mm = re.search(r"\bcom\s+(.+)$", name, re.I)
        if mm:
            bundle = mm.group(1).strip()
        streaming = bundle if (bundle and any(s in bundle.lower() for s in _STREAMING)) else None
        cob = card.css_first(".unique-card__features-cobranded-title")
        extra = _clean(cob.text()) if cob is not None else (f"Inclui {bundle}" if bundle else None)

        if plan_id in seen:
            continue
        seen.add(plan_id)

        plans.append(BaseAdapter.make_plan(
            target,
            plan_name=name,
            plan_id=plan_id,
            price_brl=price_brl,
            price_promo_brl=price_promo,
            price_note=note,
            data_gb=data_gb,
            data_note=data_note,
            validity_days=validity_days,
            loyalty_months=loyalty_months,
            streaming=streaming,
            extra_benefits=extra,
            raw_ref=raw_ref,
        ))
    return plans


def lite_capture_lost_toggle(plans) -> bool:
    """True when a LITE parse produced plans but NONE carries loyalty_months. On the live page most
    Easy Lite cards have the anual/mensal toggle, so an all-single-price parse almost certainly means
    the "Sem fidelidade" click silently FAILED and the captured headline prices are the LOYALTY
    defaults — which violates the Bridge's standing no-loyalty-headline rule (CONTEXT §10; the
    2026-07-12 snapshot did exactly this). Pure — unit-testable offline. (#30)"""
    return bool(plans) and not any(getattr(p, "loyalty_months", None) for p in plans)


class VivoAdapter(BaseAdapter):
    carrier = "vivo"

    def fetch(self, target: Target) -> list[Plan]:
        time.sleep(random.uniform(self.cfg.get("min_delay_seconds", 2),
                                  self.cfg.get("max_delay_seconds", 6)))
        html = self._render(target.url, target.category)
        raw_ref = self._save_raw(target, html)
        plans = parse_vivo_html(html, target, raw_ref=raw_ref)
        if target.category == "lite" and lite_capture_lost_toggle(plans):
            # No-loyalty-headline rule (#30): a lite parse with zero loyalty_months means the toggle
            # click likely failed and these headlines are LOYALTY prices. Retry the render ONCE
            # (bounded — politeness per GOVERNANCE §3), then record as-is but LOUDLY.
            print("WARNING vivo/lite: no 'Sem fidelidade' price captured (toggle click failed?) - "
                  "retrying the render once")
            html = self._render(target.url, target.category)
            raw_ref = self._save_raw(target, html)
            plans = parse_vivo_html(html, target, raw_ref=raw_ref)
            if lite_capture_lost_toggle(plans):
                print("WARNING vivo/lite: retry STILL lacks a loyalty-toggle capture - headline "
                      "prices may be LOYALTY prices (no-loyalty-headline rule, CONTEXT §10); "
                      "check the page markup")
        return plans

    def _render(self, url: str, category: str | None = None) -> str:
        # Retry a TRANSIENT network blip (ERR_NETWORK_CHANGED / timeout) a couple of times; a real
        # block is NOT transient and is surfaced immediately (no retry-spam — GOVERNANCE §3).
        retries = int(self.settings.sanity.get("fetch_retries", 2))
        return fetch_with_retry(lambda: self._render_once(url, category), retries)

    def _render_once(self, url: str, category: str | None = None) -> str:
        # Imported lazily so the module (and the pure parser) import fine without a browser.
        from playwright.sync_api import sync_playwright

        ua = self.cfg.get("user_agent", "")
        timeout_ms = int(self.cfg.get("request_timeout_seconds", 30)) * 1000
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.cfg.get("headless", True))
            try:
                ctx = browser.new_context(user_agent=ua, locale="pt-BR",
                                          viewport={"width": 1366, "height": 900})
                page = ctx.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                for sel in ('#onetrust-accept-btn-handler', 'button:has-text("Aceitar")',
                            'button:has-text("Concordar")'):
                    try:
                        el = page.query_selector(sel)
                        if el:
                            el.click(timeout=2000)
                            break
                    except Exception:
                        pass
                page.wait_for_timeout(3000)
                try:
                    page.wait_for_selector(".unique-card", timeout=15000)
                except Exception:
                    pass  # parser will report zero plans if the grid never rendered
                if category == "lite":
                    self._toggle_lite_no_commitment(page)   # #23: reveal the no-commitment monthly price
                return page.content()
            finally:
                browser.close()

    @staticmethod
    def _toggle_lite_no_commitment(page) -> None:
        """Vivo Lite (#23): click each Easy Lite card's "Sem fidelidade" (no-commitment) toggle so
        `.total-card-price-value` shows the no-strings monthly price (~R$45); `data-original-price` keeps
        the 12-month loyalty price for the parser to record as the promo. Cards without the toggle stay
        single-price. Best-effort — a card that won't toggle just keeps its default (loyalty) price."""
        clicked = 0
        try:
            for el in page.query_selector_all('text=/Sem fidelidade/i'):
                try:
                    el.click(timeout=2500)
                    clicked += 1
                except Exception:
                    pass
        except Exception:
            pass
        if clicked:
            page.wait_for_timeout(2000)             # let the toggled prices re-render

    def _save_raw(self, target: Target, html: str) -> str:
        d = Path(self.settings.raw_capture_dir)
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"vivo_{target.category}_{target.state}.html"
        path.write_text(html, encoding="utf-8")
        return str(path)

    @classmethod
    def demo_plans(cls, target: Target) -> list[Plan]:
        # Seeded from real recon on the Pós-pago page (2026-06-11).
        if target.category != "postpaid" or target.state != "SP":
            return []
        return [
            Plan(carrier="vivo", category="postpaid", state="SP",
                 plan_name="Vivo Pós 60GB", price_brl=150.00,
                 data_gb=60.0, data_note="bônus de internet",
                 unlimited_apps="WhatsApp + redes sociais",
                 voice="Ligações ilimitadas", streaming=None,
                 extra_benefits="5G", source_url=target.url,
                 price_note="oferta destaque (recon 2026-06-11)"),
        ]
