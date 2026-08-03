"""Claro Multi adapter — CONVERGENT (combo) offers: Claro fibra + móvel (+ Claro tv+).

RECON (verified live SP, 2026-08-03 — CONTEXT §14). **This supersedes §13's "Playwright required".**
A plain ``httpx`` GET of ``/multi`` returns **200** and the page is Next.js, so the combo grid comes
from ``<script id="__NEXT_DATA__">``; prices are hydrated client-side but come from **one public,
unauthenticated JSON endpoint** — so the whole carrier needs **no browser**, in exactly two GETs:

  1. ``GET /multi`` → ``props.pageProps.dynamicComponents.body[k]`` where ``component == "tab_select"``
     (find it BY NAME — never by index; ``card_360`` on the same page is a different product line).
     ``…data.data[i]``            = a tab ("Fibra + Móvel" / "Fibra + TV" / "Fibra + Móvel + TV")
     ``…content[0].data.data[j]`` = a combo card, whose ``_uid`` (Storyblok UUID) is the offer id.
  2. ``GET /api/catalog?state=SP&city=sao_paulo&environment=public&component=card_360&uuids=<csv>``
     → ``{"data": [ … ]}``, each entry gaining a hydrated ``catalog`` with per-slot
     ``internet`` / ``celular`` / ``tv`` / … objects. **All uuids go in ONE request** (the page itself
     only asks for the active tab's; batching keeps us to a single polite call per run).

**Price = Σ over slots of (``precoCombo`` if the key is PRESENT else ``preco``), in integer centavos**
(``7990`` == R$ 79,90). ⚠️ ``precoCombo`` can be **absent, not null** — it is missing on ``internet``
for every "Fibra + TV" card — so a naive ``v.get("precoCombo") or v["preco"]``-style read would drop
the whole fibre component and under-price those combos by R$ 99–180. Verified against the rendered
DOM on the "Fibra + Móvel" tab (79,90 + 49,90 = R$ 129,80 ✓).

⚠️ **GHOSTS.** The CMS lists combos that SP does not render: their catalog entry comes back as
``{"notFound": true}`` (5 of 15 on 2026-08-03). They are excluded — the rendered/priced set is the
truth, and a ghost has no price to record anyway.

⚠️ **CMS names are stale** ("Controle 41GB" where the priced product is 40GB): all product naming
comes from ``catalog.<slot>.nomeAutomatico`` (the CMS card titles are Handlebars placeholders).

SP is an **explicit input** here (``state=SP&city=sao_paulo``), which is stronger than the geolocated
default the mobile Claro adapter relies on — the segmentation cannot drift with the egress IP.

Payment: ``acrescimoNaoDCC`` is a surcharge for NOT paying by débito em conta (R$5 on the Controle
40GB entry tier, 0 elsewhere) — so where it is non-zero the headline assumes auto-debit; we tag
``payment_method`` and keep the surcharge in ``price_note``. That is a billing rail, not a loyalty
commitment (CONTEXT §10.5).
"""
from __future__ import annotations

import json
import random
import re
import time
from pathlib import Path

import httpx
from selectolax.parser import HTMLParser

from ..config import Target
from ..convergent import ConvergentOffer
from .base import BaseAdapter

CATALOG_URL = "https://www.claro.com.br/api/catalog"
_GB = re.compile(r"(\d+)\s*GB", re.I)
_MBPS = re.compile(r"(\d+(?:[.,]\d+)?)\s*(Mbps|Mega|Giga|Gbps)", re.I)
# "1 linha adicional inclusa" / "2 linhas dependentes inclusas" — the stems cover singular AND plural
# ("adicional" is NOT "adicionais", so a naive `adicionais?` misses every single-extra-line combo).
_EXTRA_LINES = re.compile(r"(\d+)\s*linhas?\s+(?:adicion\w*|dependent\w*)", re.I)
_SPEED_RECURSO = "602"          # recursosDescritivos id for "VELOCIDADE DE DOWNLOAD"
_PRICED_SLOTS = ("internet", "celular", "tv", "fone", "tvAdicional", "adicional")


def _clean(s: str | None) -> str:
    return " ".join(str(s).split()) if s else ""


def next_data(html: str) -> dict:
    """The page's ``__NEXT_DATA__`` payload ({} when absent — a restructured page reports, not crashes)."""
    node = HTMLParser(html).css_first("script#__NEXT_DATA__")
    if node is None:
        return {}
    try:
        return json.loads(node.text())
    except (json.JSONDecodeError, TypeError):
        return {}


def parse_claro_multi_grid(data: dict) -> list[dict]:
    """Pure: ``__NEXT_DATA__`` → the combo grid as ``[{uid, tab, items, text}]`` (every tab).
    Locates ``tab_select`` BY COMPONENT NAME — the page also carries a ``card_360`` of a different
    product line, and component order is not stable."""
    body = (((data.get("props") or {}).get("pageProps") or {})
            .get("dynamicComponents") or {}).get("body") or []
    ts = next((b for b in body if isinstance(b, dict) and b.get("component") == "tab_select"), None)
    if ts is None:
        return []
    out: list[dict] = []
    for tab in ((ts.get("data") or {}).get("data") or []):
        title = _clean(tab.get("title"))
        for content in (tab.get("content") or []):
            for card in (((content.get("data") or {}).get("data")) or []):
                uid = card.get("_uid")
                if not uid:
                    continue
                items = [{"category": it.get("category"), "id": it.get("id"), "name": it.get("name")}
                         for it in ((card.get("products_filter") or {}).get("items") or [])]
                out.append({"uid": uid, "tab": title, "items": items,
                            "text": json.dumps(card, ensure_ascii=False)})
    return out


def catalog_url(uuids, state: str = "SP", city: str = "sao_paulo") -> str:
    """The single batched price call. SP is an explicit parameter (not a geolocated guess)."""
    return (f"{CATALOG_URL}?state={state}&city={city}&environment=public&component=card_360"
            f"&uuids={','.join(uuids)}&editMode=false")


def _slot_price_centavos(slot: dict) -> int | None:
    """``precoCombo`` when the KEY IS PRESENT, else ``preco``. Written as an explicit ``in`` test:
    ``precoCombo`` is *absent* (not null) on internet for the Fibra+TV cards, and a falsy-default read
    would silently drop that component from the total."""
    if not isinstance(slot, dict):
        return None
    raw = slot["precoCombo"] if "precoCombo" in slot else slot.get("preco")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _speed_mbps(internet: dict) -> int | None:
    rd = internet.get("recursosDescritivos") or {}
    desc = ""
    for key in (_SPEED_RECURSO, int(_SPEED_RECURSO)):
        item = rd.get(key)
        if isinstance(item, dict):
            desc = _clean(item.get("description"))
            break
    if not desc:
        desc = _clean(internet.get("nomeAutomatico") or internet.get("nome"))
    m = _MBPS.search(desc)
    if not m:
        return None
    value = float(m.group(1).replace(".", "").replace(",", "."))
    unit = m.group(2).lower()
    return int(round(value * 1000)) if unit in ("giga", "gbps") else int(round(value))


def build_claro_offers(grid: list[dict], catalog: dict | list, target: Target,
                       raw_ref: str | None = None) -> list[ConvergentOffer]:
    """Pure: grid + catalog payload → ConvergentOffer list. Ghosts (``catalog.notFound``, or a card
    with no priced slot at all) are EXCLUDED — SP does not render them."""
    entries = catalog.get("data") if isinstance(catalog, dict) else catalog
    by_uid = {e.get("_uid"): e for e in (entries or []) if isinstance(e, dict)}
    meta = {g["uid"]: g for g in grid}

    offers: list[ConvergentOffer] = []
    for uid, g in meta.items():
        entry = by_uid.get(uid)
        cat = (entry or {}).get("catalog")
        if not isinstance(cat, dict) or cat.get("notFound"):
            continue                                    # GHOST: listed in the CMS, not sold in SP
        total = 0
        present: dict[str, dict] = {}
        for name in _PRICED_SLOTS:
            slot = cat.get(name)
            cents = _slot_price_centavos(slot)
            if cents is None:
                continue
            total += cents
            present[name] = slot
        if not present or total <= 0:
            continue                                    # nothing priced → not a sellable combo

        internet = present.get("internet") or {}
        celular = present.get("celular") or {}
        tv = present.get("tv") or {}
        mob_name = _clean(celular.get("nomeAutomatico") or celular.get("nome"))
        gbm = _GB.search(mob_name)
        lines = None
        if celular:
            extra = _EXTRA_LINES.search(g.get("text") or "")
            lines = 1 + int(extra.group(1)) if extra else 1

        surcharge = max((int(s.get("acrescimoNaoDCC") or 0) for s in present.values()), default=0)
        bits = [f"tab: {g['tab']}"] if g.get("tab") else []
        if surcharge:
            bits.append(f"preço em débito em conta; +R$ {surcharge / 100:.2f} sem débito automático")
        parts = " + ".join(_clean(s.get("nomeAutomatico") or s.get("nome")) for s in present.values()
                           if _clean(s.get("nomeAutomatico") or s.get("nome")))

        offers.append(ConvergentOffer(
            carrier="claro",
            state=target.state,
            offer_name=parts or _clean(g.get("tab")) or "Claro Multi",
            offer_id=f"claro:{uid}",                    # Storyblok _uid — native, never price-derived
            price_brl=round(total / 100.0, 2),          # integer centavos → BRL
            price_promo_brl=None,                       # no de/por promo in this payload (precoDe == preco)
            loyalty_months=None,
            payment_method="debit_auto" if surcharge else None,
            price_note="; ".join(bits) or None,
            has_mobile=bool(celular),
            has_broadband=bool(internet),
            has_tv=bool(tv),
            has_landline=bool(present.get("fone")),
            broadband_speed_mbps=_speed_mbps(internet) if internet else None,
            mobile_gb=float(gbm.group(1)) if gbm else None,
            mobile_lines=lines,
            tv_tier=_clean(tv.get("nomeAutomatico") or tv.get("nome")) or None,
            data_note=mob_name or None,
            source_url=target.url,
            raw_ref=raw_ref,
        ))
    return offers


class ClaroConvergentAdapter(BaseAdapter):
    """Two plain public GETs — the page (grid) and one batched catalog call (prices). No browser."""
    carrier = "claro"

    def fetch(self, target: Target) -> list[ConvergentOffer]:
        time.sleep(random.uniform(self.cfg.get("min_delay_seconds", 2),
                                  self.cfg.get("max_delay_seconds", 6)))
        headers = {"User-Agent": self.cfg.get("user_agent", "")}
        timeout = self.cfg.get("request_timeout_seconds", 30)

        html = self._get(target.url, headers, timeout)
        raw_ref = self._save_raw(target, html, suffix="html")
        grid = parse_claro_multi_grid(next_data(html))
        if not grid:
            print("WARNING claro/convergent: no tab_select grid in __NEXT_DATA__ - page restructured?")
            return []

        # config over code (INSTRUCTIONS §2.6): `convergent.claro.api_city` wins, else the state map.
        # NOTE self.cfg is the *scraping* block — the per-source knobs live under `convergent:`.
        source_cfg = (self.settings.raw.get("convergent") or {}).get(target.carrier) or {}
        city = str(source_cfg.get("api_city") or _CITY_BY_STATE.get(target.state.upper(), ""))
        if not city:
            print(f"WARNING claro/convergent: no catalog city mapped for state {target.state} - skipping")
            return []
        time.sleep(1.5)                                   # a beat between the two calls (politeness)
        url = catalog_url([g["uid"] for g in grid], state=target.state.upper(), city=city)
        payload = json.loads(self._get(url, headers, timeout))
        self._save_raw(target, json.dumps(payload, ensure_ascii=False), suffix="catalog.json")

        offers = build_claro_offers(grid, payload, target, raw_ref=raw_ref)
        ghosts = len(grid) - len(offers)
        print(f"  claro/convergent: {len(offers)} live combo(s), {ghosts} not sold in "
              f"{target.state} (ghosts, excluded)")
        return offers

    @staticmethod
    def _get(url: str, headers: dict, timeout) -> str:
        last_err: Exception | None = None
        for attempt in range(2):       # one retry on a transient blip; a real block is reported as-is
            try:
                resp = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)
                resp.raise_for_status()
                return resp.text
            except httpx.HTTPError as e:
                last_err = e
                if attempt == 0:
                    time.sleep(2)
        raise RuntimeError(f"Claro convergent {url}: request failed: {last_err}")

    def _save_raw(self, target: Target, body: str, suffix: str) -> str:
        d = Path(self.settings.raw_capture_dir)
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"claro_convergent_{target.category}_{target.state}.{suffix}"
        path.write_text(body, encoding="utf-8")
        return str(path)


# The catalog call takes the city as an explicit slug. Only SP is active; add entries as states open
# (config `api_city:` overrides this for a one-off).
_CITY_BY_STATE = {"SP": "sao_paulo", "RJ": "rio_de_janeiro", "MG": "belo_horizonte"}
