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

from .base import BaseAdapter, slugify
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

        # plan_id = native offer code + data allowance. Prepaid tiers share ONE page-level code
        # (e.g. VIV…22379), so the data amount (non-price) disambiguates them; for postpaid the code
        # is already unique per card and the suffix is harmless.
        code = _VIV.search(card.html or "") or _SELF.search(card.html or "")
        base = code.group(0) if code else slugify(name)
        gbtok = f"{int(data_gb)}gb" if data_gb else "x"
        plan_id = f"vivo:{base}-{gbtok}"

        # promo: a struck-through original price in .unique-card__price-old (hidden when no promo)
        old_el = card.css_first(".unique-card__price-old")
        old = _price_from(old_el.text()) if old_el is not None else None
        if old and old != price:
            price_brl, price_promo = old, price       # regular vs. effective (discounted)
        else:
            price_brl, price_promo = price, None

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
            price_note=("oferta com desconto" if price_promo else None),
            data_gb=data_gb,
            data_note=data_note,
            validity_days=validity_days,
            streaming=streaming,
            extra_benefits=extra,
            raw_ref=raw_ref,
        ))
    return plans


class VivoAdapter(BaseAdapter):
    carrier = "vivo"

    def fetch(self, target: Target) -> list[Plan]:
        time.sleep(random.uniform(self.cfg.get("min_delay_seconds", 2),
                                  self.cfg.get("max_delay_seconds", 6)))
        html = self._render(target.url)
        raw_ref = self._save_raw(target, html)
        return parse_vivo_html(html, target, raw_ref=raw_ref)

    def _render(self, url: str) -> str:
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
                return page.content()
            finally:
                browser.close()

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
