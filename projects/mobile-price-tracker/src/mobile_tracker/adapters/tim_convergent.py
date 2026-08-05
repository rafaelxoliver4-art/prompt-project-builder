"""TIM Ultracombo adapter — CONVERGENT (combo) offers: Ultrafibra + one TIM Black mobile line.

RECON (verified live SP, 2026-08-03 — CONTEXT §14):
``https://www.tim.com.br/sp/internet/tim-ultracombo`` returns **200 via plain httpx** (no browser, no
anti-bot) — the page did NOT exist on 2026-07-17 (three 404 probes; the #26 snapshot had to source the
tiers from a Teletime article). It is the same Drupal/Acquia stack as the mobile pages, so the offers
live in the embedded settings JSON:

    <script data-drupal-selector="drupal-settings-json"> … </script>  →  settings["ofertas"][]

**DISCRETE priced tiers** (3 on 2026-08-03: R$89,99 / R$139,99 / R$169,99) — not a "monte seu combo"
configurator ("monte seu" appears 0× on the page; the only control is a Views filter over the same
fixed list).

Per oferta — NOTE the field names differ from the mobile pages:
  * price → ``field_description`` HTML, as "<strong>Por R$89,99/mês</strong>".
    ``field_preco_card_oferta`` (the mobile price field) is **EMPTY** here.
  * name  → ``field_subtitle`` HTML ("TIM Ultracombo 7"); ``title`` is the long
            "TIM Ultracombo 7 - 500MEGA + 65GB [B2C][SP]" form (fallback).
  * speed + GB → ``field_titulo`` ("500MEGA + 65GB"; "1GIGA" = 1000 Mbps).
  * mobile plan + GB breakdown → ``field_information_text``.
  * payment ladder + ANATEL etiquetas → ``field_layout_canvas_segundo`` (20–29 KB of HTML *inside* the
    JSON string — a second-stage parse).
  * offer_id → ``nid`` (167761 / 167751 / 167756), the same native key the mobile adapter uses.

⚠️ **GHOST PRICE FIELDS — do NOT reuse the mobile promo logic.** ``field_preco_adicional_original``
("Por R$ 129,99/mês") and ``field_preco_adicional_tracejado`` ("De R$ 149,99/mês") are present and
**byte-identical on all three tiers**, contradicting each card's real price. The mobile adapter reads
``field_preco_adicional_tracejado`` as the struck-through regular price — doing that here would invent
a fake "de R$149,99" promo on every combo. They are template leftovers and are deliberately ignored.

⚠️ **Region:** every oferta carries ``langcode: "rj"`` and ``about="/rj/node/…"`` even though the offer
is SP-only — those are NOT region signals. Gate on ``field_regioes`` (``sp`` / ``sp-interior``), which
matches the ``[SP]`` title suffix, ``settings["selectedState"] == "sp"`` and the ``/sp/`` URL path.

PRICE POLICY: the card headline is the **débito-automático** price; the same modal also states a higher
"pagamento por fatura" price and a much larger gross "Valor do Plano". We record the headline (what the
carrier advertises as the offer price, consistent with the mobile Post decision in CONTEXT §10 / #27),
tag it ``payment_method="debit_auto"``, and keep the fatura figure in ``price_note`` as context. This is
a PAYMENT-METHOD ladder, not a loyalty ladder — no fidelity is attached to the headline (CONTEXT §10.5).
"""
from __future__ import annotations

import json
import random
import re
import time
from pathlib import Path

import httpx
from selectolax.parser import HTMLParser

from .base import BaseAdapter, fetch_with_retry
from ..config import Target
from ..convergent import ConvergentOffer

# "Por R$89,99/mês" / "R$ 139,99/mês" — the card headline inside field_description.
_PRICE = re.compile(r"R\$\s*(\d{1,4}(?:\.\d{3})*),(\d{2})")
# fibre speed: "500MEGA" → 500 Mbps ; "1GIGA" → 1000 Mbps (anchored on the unit so "+ 65GB" can't match)
_MEGA = re.compile(r"(\d+)\s*MEGA", re.I)
_GIGA = re.compile(r"(\d+(?:[.,]\d+)?)\s*GIGA", re.I)
_MOBILE_GB = re.compile(r"\+\s*(\d+)\s*GB", re.I)
# the fatura (invoice) price stated in the modal: "R$ 99,99/mês no pagamento por fatura."
_FATURA = re.compile(r"R\$\s*([\d.,]+)\s*/\s*m[êe]s\s*no\s*pagamento\s*por\s*fatura", re.I)
# The bundled streaming apps are ICON MEDIA, not text: field_beneficios_destaque[].name reads
# "Icone Paramount - TIM Ultracombo" (the <img> alts are empty and the modals contain no <img> at all).
# An EMPTY list is a real absence (UC7 bundles no streaming), not a parse failure. "Paramount" is
# normalized to "Paramount+" (the icon file is "Paramount+ Icon.png"; the name field drops the plus).
_ICON_NAME = re.compile(r"^\s*[ÍI]cone\s+(.+?)\s*(?:-\s*TIM.*)?$", re.I)
_STREAMING_FIX = {"paramount": "Paramount+"}


def _text(html_value: str | None) -> str:
    """Strip tags/entities from a Drupal HTML field value → collapsed plain text."""
    if not html_value:
        return ""
    return " ".join(HTMLParser(html_value).text(separator=" ", strip=True).split())


def _field(obj: dict, key: str) -> str | None:
    """Drupal serializes fields as ``[{'value': ...}]`` (or sometimes a bare string)."""
    v = obj.get(key)
    if isinstance(v, list) and v and isinstance(v[0], dict):
        return v[0].get("value")
    return v if isinstance(v, str) else None


def _price_brl(text: str | None) -> float | None:
    m = _PRICE.search(text or "")
    if not m:
        return None
    return float(f"{m.group(1).replace('.', '')}.{m.group(2)}")


def _speed_mbps(titulo: str) -> int | None:
    g = _GIGA.search(titulo)
    if g:
        return int(round(float(g.group(1).replace(",", ".")) * 1000))
    m = _MEGA.search(titulo)
    return int(m.group(1)) if m else None


def _streaming(oferta: dict) -> str | None:
    """Bundled streaming apps from the benefit ICON media names (see _ICON_NAME). None when the
    carrier bundles none — an empty `field_beneficios_destaque` is a real absence."""
    out: list[str] = []
    for media in oferta.get("field_beneficios_destaque") or []:
        if not isinstance(media, dict):
            continue
        raw = media.get("name")
        label = raw[0].get("value") if isinstance(raw, list) and raw and isinstance(raw[0], dict) else raw
        m = _ICON_NAME.match(str(label or "").strip())
        if not m:
            continue
        app = m.group(1).strip()
        app = _STREAMING_FIX.get(app.lower(), app)
        if app and app not in out:
            out.append(app)
    return ", ".join(out) or None


def _regions(oferta: dict) -> set[str]:
    """``field_regioes`` target ids, e.g. {"sp", "sp-interior"} — the authoritative region gate."""
    out = set()
    for r in oferta.get("field_regioes") or []:
        if isinstance(r, dict) and r.get("target_id"):
            out.add(str(r["target_id"]).lower())
    return out


def parse_tim_ultracombo_html(html: str, target: Target, raw_ref: str | None = None) -> list[ConvergentOffer]:
    """Pure mapping: TIM Ultracombo page HTML → list[ConvergentOffer]. No network — unit-testable.
    Returns [] if the settings JSON or the ofertas list is absent (site restructure / page pulled),
    which the caller reports rather than turning into fabricated rows."""
    node = HTMLParser(html).css_first('script[data-drupal-selector="drupal-settings-json"]')
    if node is None:
        return []
    try:
        settings = json.loads(node.text())
    except (json.JSONDecodeError, TypeError):
        return []

    offers: list[ConvergentOffer] = []
    seen: set[str] = set()
    state = (target.state or "").lower()
    for o in settings.get("ofertas") or []:
        if not isinstance(o, dict):
            continue
        # region gate — field_regioes is authoritative (langcode/about lie: they say "rj" for SP offers)
        regions = _regions(o)
        if regions and not any(r == state or r.startswith(f"{state}-") for r in regions):
            continue

        titulo = _text(_field(o, "field_titulo"))                    # "500MEGA + 65GB"
        name = _text(_field(o, "field_subtitle"))                    # "TIM Ultracombo 7"
        if not name:                                                  # fallback: the long node title
            name = re.sub(r"\[[^\]]*\]", "", _text(o.get("title") if isinstance(o.get("title"), str)
                                                   else _field(o, "title")) or "").strip(" -")
        # PRICE: field_description only — never the ghost field_preco_adicional_* fields (see module doc)
        price = _price_brl(_text(_field(o, "field_description")))
        if not name or price is None:
            continue

        nid = _field(o, "nid")
        offer_id = f"tim:{nid}" if nid and str(nid).strip() else None
        if offer_id and offer_id in seen:
            continue
        if offer_id:
            seen.add(offer_id)

        info = _text(_field(o, "field_information_text"))             # mobile plan + GB breakdown
        modal = _text(_field(o, "field_layout_canvas_segundo"))       # payment ladder + etiquetas
        fatura = _FATURA.search(modal)
        note = "preço em débito automático"
        if fatura:
            note += f"; R$ {fatura.group(1)}/mês no pagamento por fatura"
        streaming = _streaming(o)

        offers.append(ConvergentOffer(
            carrier="tim",
            state=target.state,
            offer_name=name,
            offer_id=offer_id,
            price_brl=price,
            price_note=note,
            payment_method="debit_auto",
            has_mobile=True,
            has_broadband=True,
            has_tv=False,          # no TV/landline anywhere on the Ultracombo page (verified 2026-08-03)
            has_landline=False,
            broadband_speed_mbps=_speed_mbps(titulo),
            mobile_gb=float(m.group(1)) if (m := _MOBILE_GB.search(titulo)) else None,
            mobile_lines=1,        # Ultracombo bundles exactly one line (no "linha adicional" on the page)
            streaming=streaming,
            data_note=info or None,
            source_url=target.url,
            raw_ref=raw_ref,
        ))
    return offers


class TimConvergentAdapter(BaseAdapter):
    """Fetches the TIM Ultracombo page (plain httpx — no browser needed)."""
    carrier = "tim"

    def fetch(self, target: Target) -> list[ConvergentOffer]:
        time.sleep(random.uniform(self.cfg.get("min_delay_seconds", 2),
                                  self.cfg.get("max_delay_seconds", 6)))
        headers = {"User-Agent": self.cfg.get("user_agent", "")}
        timeout = self.cfg.get("request_timeout_seconds", 30)

        # Transient blip → retry; a real block is reported, never retried (#37/E).
        def _get():
            resp = httpx.get(target.url, headers=headers, timeout=timeout, follow_redirects=True)
            resp.raise_for_status()
            return resp

        retries = int(self.settings.sanity.get("fetch_retries", 2))
        try:
            resp = fetch_with_retry(_get, retries)
        except httpx.HTTPError as e:
            raise RuntimeError(f"TIM convergent {target.url}: request failed: {e}") from e

        raw_ref = self._save_raw(target, resp.text)
        return parse_tim_ultracombo_html(resp.text, target, raw_ref=raw_ref)

    def _save_raw(self, target: Target, html: str) -> str:
        d = Path(self.settings.raw_capture_dir)
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"tim_convergent_{target.category}_{target.state}.html"
        path.write_text(html, encoding="utf-8")
        return str(path)
