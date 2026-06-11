"""Claro adapter.

STRATEGY (from recon, CONTEXT §3): Claro is a Next.js app. The cleanest path is to
fetch the page HTML and parse the embedded `__NEXT_DATA__` <script> JSON, which holds
the plan objects structured — far more robust than scraping rendered cards. City
defaults to São Paulo/SP via geolocation; if a different state is needed, set the
city via the site's mechanism (cookie/param) before reading, or use the headless
browser fallback. Implement `fetch()` here.

Skeleton Code can flesh out:
    1. httpx GET target.url with cfg user_agent/timeout (+ polite delay).
    2. Locate <script id="__NEXT_DATA__" type="application/json"> ... </script>.
    3. json.loads it; walk to the plans list (inspect the structure once, record the
       JSON path in CONTEXT.md so it's documented).
    4. Map each plan object -> Plan via self.make_plan(target, plan_name=..., price_brl=..., ...).
    5. Save the raw JSON to settings.raw_capture_dir for audit (raw_ref).

FULL DETAIL (Bridge decision, CONTEXT §10.2): we want the data behind "ver mais"/detail
modals too, not just headline cards. For Claro this is often a non-issue — `__NEXT_DATA__`
usually already embeds the full plan detail (the modals are just rendered from the same
JSON). Verify that first; only fall back to Playwright interaction if some detail proves
to be fetched lazily and is genuinely absent from the initial JSON.
"""
from __future__ import annotations

from .base import BaseAdapter
from ..config import Target
from ..models import Plan


class ClaroAdapter(BaseAdapter):
    carrier = "claro"

    def fetch(self, target: Target) -> list[Plan]:
        raise NotImplementedError("Implement Claro __NEXT_DATA__ parsing (see module docstring).")

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
