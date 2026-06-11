"""TIM adapter.

STRATEGY (from recon, CONTEXT §3): TIM is server-rendered Drupal — parse the HTML
directly (httpx GET, then selectolax/bs4). Two wrinkles:
    1. The page dumps MANY offer names; isolate the actual plan cards (find the plan
       container, not the global offer list). Record the container selector in CONTEXT.md.
    2. SOME PRICES ARE IN SVG IMAGES (e.g. the price encoded in an SVG filename/alt text).
       Handle image-embedded prices: read the <img alt>/filename, or OCR if needed.
State is in the URL path already (config templated `/sp/...`), so no geolocation step.

FULL DETAIL (Bridge decision, CONTEXT §10.2): capture "ver mais"/detail content too.
TIM is server-rendered, so the detail is often already in the HTML (hidden panels) — parse
those nodes directly rather than only the visible card. Use Playwright only if some detail
is injected by JS on click and is absent from the initial HTML.
"""
from __future__ import annotations

from .base import BaseAdapter
from ..config import Target
from ..models import Plan


class TimAdapter(BaseAdapter):
    carrier = "tim"

    def fetch(self, target: Target) -> list[Plan]:
        raise NotImplementedError("Implement TIM Drupal HTML parsing + SVG price handling (see docstring).")

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
