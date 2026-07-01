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


def parse_tim_html(html: str, target: Target, raw_ref: str | None = None) -> list[Plan]:
    """Pure mapping: TIM page HTML → list[Plan] (reads the embedded drupal-settings JSON). No network."""
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
            validity_days=validity_days, raw_ref=raw_ref))
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
        return parse_tim_html(resp.text, target, raw_ref=raw_ref)

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
