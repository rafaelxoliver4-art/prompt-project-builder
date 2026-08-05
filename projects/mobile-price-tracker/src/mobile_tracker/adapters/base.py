"""Base adapter interface.

Each carrier adapter takes the project Settings + a Target (carrier/category/state/url)
and returns a list[Plan]. Live fetching/parsing is implemented by Code on the real machine
(the chat sandbox can't reach the sites). Every adapter also provides `demo_plans()` so the
end-to-end pipeline (config -> adapter -> Excel) is verifiable offline with no network.
"""
from __future__ import annotations

import re
import time
from abc import ABC, abstractmethod

from ..config import Settings, Target
from ..models import Plan


def slugify(text: str | None) -> str:
    """Lowercase ASCII slug for fallback plan_ids — only used when no native id exists."""
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s or "x"


# Transient network errors are retry-worthy; a block / HTTP 4xx / CAPTCHA is NOT (GOVERNANCE §3 —
# never retry-spam a site that's refusing us). Match on the exception type + message.
_TRANSIENT = re.compile(
    r"ERR_NETWORK_CHANGED|ERR_CONNECTION|ERR_TIMED_OUT|ERR_NAME_NOT_RESOLVED|ERR_INTERNET_DISCONNECTED|"
    r"ERR_ABORTED|net::ERR|Timeout|timed out|Connection reset|ConnectError|ReadError|ConnectTimeout|"
    r"ReadTimeout|RemoteProtocolError", re.I)
_BLOCK = re.compile(r"\b4\d\d\b|Forbidden|Access Denied|captcha|\bblocked\b", re.I)


def is_transient_error(err: BaseException) -> bool:
    """True for transient network errors (retry-worthy). A block / 4xx / CAPTCHA → False (no retry)."""
    s = f"{type(err).__name__}: {err}"
    if _BLOCK.search(s):
        return False
    return bool(_TRANSIENT.search(s))


def fetch_with_retry(fetch_fn, retries: int, is_transient=is_transient_error, sleep_fn=time.sleep):
    """Call ``fetch_fn()``; on a TRANSIENT error retry up to ``retries`` more times with a short
    backoff; a non-transient error (block/4xx/CAPTCHA) is raised immediately (no retry-spam)."""
    attempts = 1 + max(0, int(retries))
    for i in range(attempts):
        try:
            return fetch_fn()
        except Exception as e:                    # noqa: BLE001 — re-raised unless transient + budget left
            if is_transient(e) and i < attempts - 1:
                sleep_fn(min(2 * (i + 1), 8))
                continue
            raise


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
