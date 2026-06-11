"""Base adapter interface.

Each carrier adapter takes the project Settings + a Target (carrier/category/state/url)
and returns a list[Plan]. Live fetching/parsing is implemented by Code on the real machine
(the chat sandbox can't reach the sites). Every adapter also provides `demo_plans()` so the
end-to-end pipeline (config -> adapter -> Excel) is verifiable offline with no network.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..config import Settings, Target
from ..models import Plan


class BaseAdapter(ABC):
    carrier: str = ""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.cfg = settings.scraping

    @abstractmethod
    def fetch(self, target: Target) -> list[Plan]:
        """Fetch+parse one target into Plans. Implemented per-carrier by Code."""
        raise NotImplementedError

    # --- shared helpers Code can reuse -------------------------------------
    @staticmethod
    def make_plan(target: Target, **kw) -> Plan:
        return Plan(carrier=target.carrier, category=target.category,
                    state=target.state, source_url=target.url, **kw)

    @classmethod
    def demo_plans(cls, target: Target) -> list[Plan]:
        """Override in each carrier with realistic sample rows for offline tests/demo."""
        return []
