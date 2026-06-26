"""Claro adapter — live plan scraping via the Next.js ``__NEXT_DATA__`` JSON.

STRATEGY (verified against the live site 2026-06-19, CONTEXT §3):
Claro's plan pages are a Next.js app whose ``<script id="__NEXT_DATA__">`` carries a
Storyblok-style CMS tree. The plan grid is a component with ``component == "card_360"``
under ``props.pageProps.dynamicComponents.body[]``; each entry in that component's
``data.data`` is one plan card. Per card:

  * price → ``card["actions"][0]["price"]["price"]``  (a string, e.g. ``"R$ 124,90"``)
  * name  → ``card["actions"][0]["link"][0]["modalContent"]["title"]`` (e.g. ``"Pós 100GB"``).
            Some cards leave this empty; we then derive it from the modal's accordion
            slug (``…plano-pos-60gb…`` → ``"Pós 60GB"``) using the Target's category label.
  * features → ``card["detail"][*]["label"]`` (WhatsApp ilimitado, roaming, cloud, etc.)

FULL DETAIL (Bridge decision §10.2): the "ver mais" modal content is **already embedded**
in ``__NEXT_DATA__`` (under ``modalContent``), so a plain ``httpx`` GET is sufficient —
**no Playwright interaction required** for Claro. State defaults to São Paulo/SP via the
site's geolocation; ``state`` is carried from the Target, not re-derived from the page.
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

# "R$ 124,90" / "R$ 1.234,56" / bare "54,90" → 124.90 / 1234.56 / 54.90
# (postpaid prices carry the "R$"; control/flex store a bare "54,90" in price + the regular
# price in a separate `prefix` field, so the R$ is optional.)
_PRICE = re.compile(r"(?:R\$\s*)?([\d.]+),(\d{2})")
_GB = re.compile(r"(\d+)\s*GB", re.I)
# native plan slug, e.g. "plano-controle-30gb-gaming" (distinguishes the two 30GB tiers)
_SLUG = re.compile(r"plano-[a-z]+-\d+gb[a-z0-9-]*", re.I)


def _claro_slug(modal: dict) -> str | None:
    """The card's native plan slug — the stable plan_id source (drops '-mais-detalhes/-informacoes')."""
    try:
        name = modal["drawer_select_list"][0]["accordion_list_relations"]["name"]
    except (KeyError, IndexError, TypeError):
        name = json.dumps(modal, ensure_ascii=False)
    m = _SLUG.search(name or "")
    if not m:
        return None
    s = re.sub(r"-mais-(?:detalhes|informacoes).*$", "", m.group(0), flags=re.I)
    return re.sub(r"-mais$", "", s, flags=re.I)


def _parse_brl(text: str | None) -> float | None:
    if not text:
        return None
    m = _PRICE.search(text)
    if not m:
        return None
    return float(f"{m.group(1).replace('.', '')}.{m.group(2)}")


def _clean(text: str | None) -> str:
    return " ".join(text.split()) if text else ""


# Prezão recarga tiers are described in the prepaid page's rich text as
# "R$ <recarga>/<validity> dias – <gb>GB" (e.g. "R$ 30/30 dias – 12GB"). The separator is an en/em
# dash (literal en/em/hyphen, OR an HTML entity like &#8211;/&ndash; in case the CMS serializes it that
# way); requiring the dash (vs. any gap) avoids matching a GB token from an adjacent sentence. #18
_DASHES = "–—"   # en dash, em dash (literal)
_PREZAO_TIER = re.compile(
    r"R\$\s*(\d+)\s*/\s*(\d+)\s*dias\s*(?:[" + _DASHES + r"\-]|&[#\w]+;)\s*(\d+)\s*GB", re.I)


def parse_next_data(data: dict, target: Target, raw_ref: str | None = None) -> list[Plan]:
    """Pure mapping: ``__NEXT_DATA__`` dict → list[Plan]. No network, no I/O — unit-testable."""
    dc = data.get("props", {}).get("pageProps", {}).get("dynamicComponents", {}) or {}
    body = dc.get("body", []) or []
    plans: list[Plan] = []
    seen: set[str] = set()

    for comp in body:
        if not isinstance(comp, dict) or comp.get("component") != "card_360":
            continue
        cards = (comp.get("data", {}) or {}).get("data", []) or []
        for card in cards:
            if not isinstance(card, dict):
                continue
            actions = card.get("actions") or []
            if not actions or not isinstance(actions[0], dict):
                continue
            act = actions[0]

            price_obj = act.get("price") or {}
            price = _parse_brl(price_obj.get("price"))
            if price is None:  # a card with no headline price is not a usable plan row
                continue
            # Promo: control/flex show a struck-through regular price in `prefix`
            # ("~De R$ 59,90~ Por:") with the effective price in `price`. Postpaid has no prefix.
            regular = _parse_brl(price_obj.get("prefix"))
            note = _clean((price_obj.get("prefix") or "").replace("~", "")) or None
            if regular and regular != price:
                price_brl, price_promo_brl = regular, price   # regular vs. discounted
            else:
                price_brl, price_promo_brl = price, None

            link = act.get("link") or []
            modal = link[0].get("modalContent", {}) if link and isinstance(link[0], dict) else {}
            modal = modal or {}
            slug = _claro_slug(modal)               # native, unique (e.g. "plano-controle-30gb-gaming")
            title = _clean(modal.get("title"))
            if title and _GB.search(title):         # explicit plan name, e.g. "Pós 100GB"
                name = title
            elif slug:                              # generic title ("Mais detalhes") → derive from slug
                gbm = re.search(r"-(\d+)gb", slug)
                name = f"{target.category_label} {gbm.group(1)}GB" if gbm else target.category_label
            else:                                   # can't reliably identify the plan → skip, don't guess
                continue
            plan_id = f"claro:{slug}" if slug else f"claro:{slugify(name)}"

            gb = _GB.search(name)
            data_gb = float(gb.group(1)) if gb else None

            labels = [_clean(d.get("label")) for d in (card.get("detail") or [])
                      if isinstance(d, dict) and _clean(d.get("label"))]
            unlimited_apps = "WhatsApp" if any("whatsapp" in l.lower() for l in labels) else None
            extras = "; ".join(labels) or None

            if plan_id in seen:  # collapse duplicate cards of the same plan (same native id)
                continue
            seen.add(plan_id)

            plans.append(BaseAdapter.make_plan(
                target,
                plan_name=name,
                plan_id=plan_id,
                price_brl=price_brl,
                price_promo_brl=price_promo_brl,
                price_note=note,
                data_gb=data_gb,
                unlimited_apps=unlimited_apps,
                extra_benefits=extras,
                raw_ref=raw_ref,
            ))
    return plans


def parse_claro_prepaid(data: dict, target: Target, raw_ref: str | None = None) -> list[Plan]:
    """Claro prepaid (Prezão): capture the real recarga tiers + validity, NOT the "R$1 por dia"
    headline the old parser grabbed (#18). The page describes each tier in rich text as
    "R$ <recarga>/<validity> dias – <gb>GB" (e.g. "R$ 30/30 dias – 12GB" — the 30-day plan; the
    "R$1 por dia" framing is just R$30 ÷ 30). We extract every tier with its ``validity_days``, keyed
    by (validity, gb) so the plan_id is NEVER price-derived (CONTEXT §4); on a (validity, gb) collision
    (e.g. R$30 vs R$35 both 30d/12GB — com/sem anúncio) we keep the cheaper recarga. The Pre matrix
    column then picks the cheapest 30-day tier (→ R$30/30d/12GB), replacing the R$1 bug. The tiers live
    in rich text rather than a clean ``card_360``/``tab_select`` field, so this is a regex over the
    page content — if Claro restructures it, prepaid yields 0 (caught by validation) and the saved raw
    capture can be re-parsed."""
    blob = json.dumps(data, ensure_ascii=False)
    best: dict[tuple[int, int], float] = {}          # (validity_days, gb) -> cheapest recarga seen
    for recarga, days, gb in _PREZAO_TIER.findall(blob):
        key = (int(days), int(gb))
        price = float(recarga)
        if key not in best or price < best[key]:
            best[key] = price
    plans: list[Plan] = []
    for (days, gb), price in sorted(best.items()):
        plans.append(BaseAdapter.make_plan(
            target,
            plan_name=f"Prezão {gb}GB ({days} dias)",
            plan_id=f"claro:prezao-{days}d-{gb}gb",   # native-free, non-price (validity+gb)
            price_brl=price,
            data_gb=float(gb),
            validity_days=days,
            price_note=f"recarga Prezão R${int(price)} — validade {days} dias",
            raw_ref=raw_ref,
        ))
    return plans


class ClaroAdapter(BaseAdapter):
    carrier = "claro"

    def fetch(self, target: Target) -> list[Plan]:
        # Politeness: random delay before the single request (GOVERNANCE §3).
        lo = self.cfg.get("min_delay_seconds", 2)
        hi = self.cfg.get("max_delay_seconds", 6)
        time.sleep(random.uniform(lo, hi))

        headers = {"User-Agent": self.cfg.get("user_agent", "")}
        timeout = self.cfg.get("request_timeout_seconds", 30)

        last_err: Exception | None = None
        for attempt in range(2):  # one retry max
            try:
                resp = httpx.get(target.url, headers=headers, timeout=timeout, follow_redirects=True)
                resp.raise_for_status()
                break
            except httpx.HTTPError as e:
                last_err = e
                if attempt == 0:
                    time.sleep(2)
        else:
            raise RuntimeError(f"Claro {target.url}: request failed: {last_err}")

        node = HTMLParser(resp.text).css_first("script#__NEXT_DATA__")
        if node is None:
            raise RuntimeError(f"Claro {target.url}: no __NEXT_DATA__ script found "
                               f"(page may be blocked or restructured)")
        raw = node.text()
        raw_ref = self._save_raw(target, raw)
        # prepaid (Prezão) has a different page layout (tab_select, not card_360) → dedicated parser.
        parser = parse_claro_prepaid if target.category == "prepaid" else parse_next_data
        return parser(json.loads(raw), target, raw_ref=raw_ref)

    def _save_raw(self, target: Target, text: str) -> str:
        d = Path(self.settings.raw_capture_dir)
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"claro_{target.category}_{target.state}.json"
        path.write_text(text, encoding="utf-8")
        return str(path)

    @classmethod
    def demo_plans(cls, target: Target) -> list[Plan]:
        if target.category != "control" or target.state != "SP":
            return []
        return [
            Plan(carrier="claro", category="control", state="SP",
                 plan_name="Claro Controle 30GB", price_brl=64.99,
                 data_gb=25.0, data_note="20GB + 5GB bônus",
                 unlimited_apps="WhatsApp", voice="Ligações ilimitadas",
                 streaming=None, source_url=target.url),
        ]
