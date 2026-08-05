"""Vivo Total adapter — CONVERGENT (combo) offers: Vivo Fibra + Vivo Pós (+ Vivo TV).

RECON (verified live SP, 2026-08-03 — CONTEXT §14):
A plain ``httpx`` GET of the Vivo Total page returns **403** behind **Cloudflare** (the block moved
from Akamai; the interstitial is "Just a moment…"), so — exactly like the mobile Vivo pages — a real
headless Chromium renders it (HTTP 200, no CAPTCHA) and we scrape the DOM. The combo grid is the
**same ``.unique-card`` component** the mobile adapter already knows:

  * name    → ``.unique-card__plan``              ("Vivo Total Ultra")
  * price   → ``.total-card-price-value``         (text "170"; also ``data-original-price``)
  * fibre   → ``.unique-card__header-benefit``    ("700 Mega de Vivo Fibra" / "1Giga de Vivo Fibra")
  * mobile  → ``.unique-card__benefit``           ("70 GB de Vivo Pós")
  * TV      → ``.unique-card__benefit``           ("80 canais de Vivo Estendido") **or** a
                                                   ``.unique-card__switch-list`` item ("Vivo TV Completo …")
  * lines   → ``.unique-card__switch-list``       ("1 linha adicional inclusa" → 1 base + 1)
  * code    → ``a[data-code-rgc]``                ("VIV202604028853")
  * products→ ``[data-external-link-url]``        ("…?productsIds=313,336,426,…")

⚠️ **THE ``VIV`` CODE IS NOT UNIQUE.** On 2026-08-03, 11 cards carried only 9 distinct codes: the
Ultra (R$170) and Ultra + TV online (R$190) both use ``VIV202604028853``, and Total Família 2 (R$270)
and Família 2 (R$290) both use ``VIV202604028085``. So ``offer_id`` is the code **plus the card's own
product composition** — the ``productsIds`` list from ``data-external-link-url``, **sorted** so a
re-ordering of the same bundle keeps the id stable. That is carrier-native, **never price-derived**,
and unique across every observed card. (A defensive uniqueness pass adds the name slug, then the DOM
position, if a collision ever survives — a card is never silently dropped.) Note ``data-external-link-url``
is authoritative: some cards' visible CTA ``href`` carries stale/copy-pasted productsIds.

⚠️ **The visible ``.unique-card__price`` contains an unrendered Vue mustache** ("Valor R$ {{ total }}
170 /mês"), so the price must come from ``.total-card-price-value`` (or its ``data-original-price``).

⚠️ **An optional PAID add-on can hide the price element.** Each card has a "Adicione 6 apps por
R$55/mês" toggle; when selected, Vue swaps the element (``v-show="!totalPackagesSelected"``) and the
displayed number becomes base+add-on. We never click it, and if the text is missing/unusable we fall
back to ``data-original-price`` rather than dropping the offer. The add-on is NOT part of the price.

⚠️ **Session-dependent variants.** Different renders have returned different price sets (a capture on
2026-07-17 saw "Total Essencial R$130 (de 160)" where 2026-08-03 saw "Total Pro R$160" flat, and no
``Essencial`` card at all). We therefore record what actually renders, treat a struck-through
``.unique-card__price-old`` as the regular price (headline) with the displayed one as the promo, and
never hard-code the card count.

Loyalty: the cards' "Instalação grátis mediante fidelização" applies to the free INSTALL, not to the
monthly price, so ``loyalty_months`` stays None and the condition is kept in ``data_note`` — the
headline stays a no-commitment monthly price (CONTEXT §10.5).
"""
from __future__ import annotations

import random
import re
import time
from pathlib import Path

from selectolax.parser import HTMLParser

from .base import BaseAdapter, slugify, fetch_with_retry
from ..config import Target
from ..convergent import ConvergentOffer

_MEGA = re.compile(r"(\d+)\s*Mega", re.I)
_GIGA = re.compile(r"(\d+(?:[.,]\d+)?)\s*Giga", re.I)
_GB = re.compile(r"(\d+)\s*GB", re.I)
_CANAIS = re.compile(r"(\d+)\s*canais", re.I)
_EXTRA_LINES = re.compile(r"(\d+)\s*linhas?\s+(?:adicion\w*|dependent\w*)", re.I)
_PRODUCTS = re.compile(r"productsIds=([\d,]+)")
_VIV = re.compile(r"VIV\d{6,}")
_SP_LABEL = ".new-compass-top-bar__text-container"


def _clean(text: str | None) -> str:
    return " ".join(text.split()) if text else ""


def _price_from(text: str | None) -> float | None:
    """Parse a BRL price, deciding the separator roles BY PATTERN rather than by assumption (#36).

    The old version stripped every ``.`` as a thousands separator, so a **dot-decimal** value —
    which this page really can serve, e.g. ``data-original-price="160.00"`` — became **16000**: a
    silent 100× error on a price that feeds the convergent matrix. (#35 audit, blocker.)

    The rule, applied to the last separator present:
      * ``1.200,00`` / ``24,99``  → comma is the decimal mark, dots are thousands  → 1200.0 / 24.99
      * ``1,200.00`` / ``160.00`` → dot is the decimal mark, commas are thousands  → 1200.0 / 160.0
      * a LONE separator followed by exactly 3 digits and nothing else (``1.200``, ``1,200``) is a
        thousands group, not a decimal → 1200.0  (BRL is quoted with 2 decimals, never 3)
      * ``170`` → 170.0
    Returns None when no digits are present."""
    if not text:
        return None
    m = re.search(r"\d[\d.,]*", str(text))
    if not m:
        return None
    raw = m.group(0).rstrip(".,")
    if not raw:
        return None
    last_dot, last_comma = raw.rfind("."), raw.rfind(",")
    if last_dot == -1 and last_comma == -1:
        return float(raw)
    sep, pos = (".", last_dot) if last_dot > last_comma else (",", last_comma)
    tail = raw[pos + 1:]
    if len(tail) == 3 and raw.count(sep) == 1 and (last_dot == -1 or last_comma == -1):
        return float(raw.replace(sep, ""))            # "1.200" / "1,200" → a thousands group
    other = "," if sep == "." else "."
    return float(raw.replace(other, "").replace(sep, "."))


def _speed_mbps(text: str) -> int | None:
    g = _GIGA.search(text or "")
    if g:
        return int(round(float(g.group(1).replace(",", ".")) * 1000))
    m = _MEGA.search(text or "")
    return int(m.group(1)) if m else None


def page_is_sao_paulo(html: str) -> bool:
    """The page's own location bar says "Ofertas para São Paulo (SP)" — a positive SP assertion for
    a geolocated page (we never enter a CEP). Returns False if the bar is absent/another city."""
    el = HTMLParser(html).css_first(_SP_LABEL)
    return "são paulo (sp)" in _clean(el.text()).lower() if el is not None else False


def _offer_id(card, name: str) -> str:
    """Carrier-native, non-price-derived id: the VIV offer code + the card's own product composition
    (sorted `productsIds`), because the VIV code alone COLLIDES across cards (see module docstring)."""
    code = _VIV.search(card.html or "")
    ext = card.css_first("[data-external-link-url]")
    pids = _PRODUCTS.search(ext.attributes.get("data-external-link-url") or "") if ext is not None else None
    parts = [code.group(0) if code else slugify(name)]
    if pids:
        # sorted numerically → the same bundle keeps one id even if the carrier reorders the list
        parts += sorted((t for t in pids.group(1).split(",") if t), key=lambda t: int(t))
    return "vivo:" + "-".join(parts)


def parse_vivo_total_html(html: str, target: Target, raw_ref: str | None = None) -> list[ConvergentOffer]:
    """Pure mapping: rendered Vivo Total HTML → list[ConvergentOffer]. selectolax only, no network."""
    tree = HTMLParser(html)
    offers: list[ConvergentOffer] = []
    seen: set[str] = set()

    for pos, card in enumerate(tree.css(".unique-card")):
        plan_el = card.css_first(".unique-card__plan")
        name = _clean(plan_el.text()) if plan_el is not None else ""
        if not name:
            continue

        price_el = card.css_first(".total-card-price-value")
        shown = _price_from(_clean(price_el.text())) if price_el is not None else None
        # the add-on toggle can v-show the element away → fall back to the attribute (never drop)
        attr_price = _price_from(price_el.attributes.get("data-original-price")) if price_el is not None else None
        price = shown if shown is not None else attr_price
        if price is None:
            continue
        note_bits: list[str] = []
        if shown is not None and attr_price is not None and shown != attr_price:
            # displayed != base → the paid apps add-on is selected in this render; the offer's own
            # price is the base one, and we say so instead of silently recording base+add-on.
            price = attr_price
            note_bits.append(f"preço-base R$ {attr_price:g} (a tela exibia R$ {shown:g} com pacote de apps)")

        # promo: a struck-through regular price (empty on all cards in the 2026-08-03 render)
        old_el = card.css_first(".unique-card__price-old")
        old = _price_from(_clean(old_el.text())) if old_el is not None else None
        if old and old != price:
            price_brl, price_promo = old, price          # regular vs. effective (mirrors the mobile rule)
            note_bits.append("oferta com desconto")
        else:
            price_brl, price_promo = price, None

        ben_el = card.css_first(".unique-card__header-benefit")
        speed = _speed_mbps(_clean(ben_el.text()) if ben_el is not None else "")

        mobile_gb = None
        tv_tier = None
        for b in card.css(".unique-card__benefit"):
            t = _clean(b.text())
            if mobile_gb is None and "GB" in t and ("pós" in t.lower() or "pos" in t.lower()):
                m = _GB.search(t)
                mobile_gb = float(m.group(1)) if m else None
            elif tv_tier is None and _CANAIS.search(t):
                tv_tier = t
        if mobile_gb is None:                                  # fallback: first "N GB" anywhere
            bb = card.css_first(".unique-card__benefit-benefit")
            m = _GB.search(_clean(bb.text())) if bb is not None else None
            mobile_gb = float(m.group(1)) if m else None

        switch = [_clean(li.text()) for li in card.css(".unique-card__switch-list li")]
        lines = 1
        for s in switch:                                        # "1 linha adicional inclusa" → 1 + 1
            m = _EXTRA_LINES.search(s)
            if m:
                lines = 1 + int(m.group(1))
                break
        if tv_tier is None:                                     # top tier states TV in the switch list
            tv_tier = next((s for s in switch if re.search(r"\bVivo\s+TV\b", s, re.I)), None)

        card_text = _clean(card.text())
        has_tv = tv_tier is not None
        oid = _offer_id(card, name)
        if oid in seen:                                         # defensive: never silently drop a card
            oid = f"{oid}-{slugify(name)}"
            if oid in seen:
                oid = f"{oid}-{pos}"
        seen.add(oid)

        if re.search(r"mediante fidelizaç", card_text, re.I):
            note_bits.append("instalação grátis mediante fidelização (não afeta a mensalidade)")

        offers.append(ConvergentOffer(
            carrier="vivo",
            state=target.state,
            offer_name=name,
            offer_id=oid,
            price_brl=price_brl,
            price_promo_brl=price_promo,
            loyalty_months=None,        # the monthly price carries no commitment (CONTEXT §10.5)
            price_note="; ".join(note_bits) or None,
            has_mobile=mobile_gb is not None,
            has_broadband=speed is not None,
            has_tv=has_tv,
            has_landline=False,         # no landline in any Vivo Total combo (verified 2026-08-03)
            broadband_speed_mbps=speed,
            mobile_gb=mobile_gb,
            mobile_lines=lines,
            tv_tier=tv_tier,
            extra_benefits="; ".join(switch[:3]) or None,
            data_note=_clean(ben_el.text()) if ben_el is not None else None,
            source_url=target.url,
            raw_ref=raw_ref,
        ))
    return offers


class VivoConvergentAdapter(BaseAdapter):
    """Renders the Vivo Total page with Playwright (httpx is 403) and parses the combo grid."""
    carrier = "vivo"

    def fetch(self, target: Target) -> list[ConvergentOffer]:
        time.sleep(random.uniform(self.cfg.get("min_delay_seconds", 2),
                                  self.cfg.get("max_delay_seconds", 6)))
        html = self._render(target.url)
        raw_ref = self._save_raw(target, html)
        if not page_is_sao_paulo(html):
            # Positive SP assertion — the page is geolocated, so a datacenter IP could in principle be
            # served another city. Report loudly; the rows still carry the configured state.
            print("WARNING vivo/convergent: the page's location bar does not say 'São Paulo (SP)' - "
                  "the captured combos may not be the SP set")
        return parse_vivo_total_html(html, target, raw_ref=raw_ref)

    def _render(self, url: str) -> str:
        # Retry a TRANSIENT browser/network blip; a real block is surfaced at once (#37/E, GOVERNANCE §3).
        retries = int(self.settings.sanity.get("fetch_retries", 2))
        return fetch_with_retry(lambda: self._render_once(url), retries)

    def _render_once(self, url: str) -> str:
        from playwright.sync_api import sync_playwright     # lazy: the parser imports without a browser

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
                    pass            # the parser reports zero offers if the grid never rendered
                # LAZY RENDER: cards below the fold are not in the DOM until scrolled into view — a
                # no-scroll capture silently yields a SHORT list. Scroll to the bottom, then settle.
                self._scroll_all(page)
                return page.content()
            finally:
                browser.close()

    @staticmethod
    def _scroll_all(page, max_steps: int = 12) -> None:
        """Wheel down until the card count stops growing (bounded), then let the last cards settle."""
        last = -1
        for _ in range(max_steps):
            count = len(page.query_selector_all(".unique-card"))
            if count == last:
                break
            last = count
            page.mouse.wheel(0, 1200)
            page.wait_for_timeout(600)
        page.wait_for_timeout(1500)

    def _save_raw(self, target: Target, html: str) -> str:
        d = Path(self.settings.raw_capture_dir)
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"vivo_convergent_{target.category}_{target.state}.html"
        path.write_text(html, encoding="utf-8")
        return str(path)
