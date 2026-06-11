"""Vivo adapter.

STRATEGY (from recon, CONTEXT §3): Vivo runs on Adobe Experience Manager (AEM).
Some offers are already in the server HTML (recon saw "60 GB por R$ 150/mês",
offer code SELF8221B240), but the full plan grid is likely JS-rendered.
Two paths, in order of preference:
    1. Probe for an AEM JSON model endpoint — AEM often serves `<page-path>.model.json`
       (try appending `.model.json` to the page path). If it returns plan data, parse JSON.
    2. Otherwise use the Playwright fallback: load the page, accept the cookie banner,
       confirm SP as location, wait for the plan grid, read the cards.
Record whichever works (and the JSON path / selectors) in CONTEXT.md.

FULL DETAIL (Bridge decision, CONTEXT §10.2): capture the "ver mais"/modal content too.
If the `.model.json` route exposes full detail, prefer it; otherwise the Playwright path
must click each plan's "ver mais"/detail trigger and read the expanded panel before mapping.
"""
from __future__ import annotations

from .base import BaseAdapter
from ..config import Target
from ..models import Plan


class VivoAdapter(BaseAdapter):
    carrier = "vivo"

    def fetch(self, target: Target) -> list[Plan]:
        raise NotImplementedError("Implement Vivo AEM .model.json probe / Playwright (see docstring).")

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
