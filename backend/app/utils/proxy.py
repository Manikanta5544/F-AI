"""
app/utils/proxy.py — Safe optional proxy support.

BUG-2 FIX: The original file had hardcoded fake placeholder URLs
("http://user:pass@proxy1:port") which caused every httpx request to
fail with a ConnectionError. Proxies are now opt-in via environment
variables and gracefully absent when not configured.
"""
from __future__ import annotations

import logging
import os
import random
from typing import Optional

logger = logging.getLogger(__name__)

# Read proxy list from environment. Format (comma-separated):
#   SCRAPER_PROXIES=http://user:pass@host1:port,http://user:pass@host2:port
# Leave unset or empty to disable proxies entirely.
_raw = os.getenv("SCRAPER_PROXIES", "").strip()
_PROXY_LIST: list[str] = [p.strip() for p in _raw.split(",") if p.strip()]

if _PROXY_LIST:
    logger.info(f"proxy.py: {len(_PROXY_LIST)} proxy(ies) configured")
else:
    logger.debug("proxy.py: no proxies configured — direct connections only")


def get_proxy() -> Optional[str]:
    """
    Return a random proxy URL, or None when no proxies are configured.
    Callers must handle None (no proxy needed — use direct connection).
    """
    if not _PROXY_LIST:
        return None
    return random.choice(_PROXY_LIST)


def is_proxy_enabled() -> bool:
    return bool(_PROXY_LIST)