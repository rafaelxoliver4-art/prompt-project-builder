"""Load sources.yaml and expand it into concrete scrape targets.

A *target* is one (carrier, category, state) tuple with a resolved URL.
TIM templates the state into the URL path; Vivo/Claro use geolocation, so their
URL is the same regardless of state (the adapter handles the location switch).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import yaml

DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "config" / "sources.yaml"


@dataclass(frozen=True)
class Target:
    carrier: str
    render: str          # aem | nextjs | html
    category: str
    category_label: str
    state: str
    url: str


@dataclass
class Settings:
    raw: dict

    @property
    def output_xlsx(self) -> str:
        return self.raw["project"]["output_xlsx"]

    @property
    def raw_capture_dir(self) -> str:
        return self.raw["project"]["raw_capture_dir"]

    @property
    def scraping(self) -> dict:
        return self.raw.get("scraping", {})

    def active_states(self) -> list[str]:
        return [s["code"] for s in self.raw.get("states", []) if s.get("active")]

    def targets(self) -> Iterator[Target]:
        states = self.active_states()
        for code, c in self.raw.get("carriers", {}).items():
            state_in_url = c.get("state_in_url", False)
            for cat, meta in c.get("categories", {}).items():
                for state in states:
                    url = meta["url"]
                    if state_in_url:
                        url = url.format(state=state.lower())
                    yield Target(
                        carrier=code,
                        render=c.get("render", "html"),
                        category=cat,
                        category_label=meta.get("label", cat),
                        state=state,
                        url=url,
                    )


def load(path: Path | str = DEFAULT_CONFIG) -> Settings:
    with open(path, "r", encoding="utf-8") as fh:
        return Settings(yaml.safe_load(fh))
