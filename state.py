from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Set

logger = logging.getLogger(__name__)

# --- TTL / max-size settings for seen.json cleanup ---
# URLs older than this many seconds are eligible for removal.
SEEN_TTL_SECONDS = 30 * 24 * 3600  # 30 days
# If the list grows beyond this, oldest entries are trimmed first.
SEEN_MAX_ENTRIES = 1000


@dataclass
class SeenState:
    seen_urls: Set[str] = field(default_factory=set)
    # NEW: store timestamps so we can do TTL-based cleanup
    seen_with_ts: dict = field(default_factory=dict)  # {url: epoch_seconds}


def load_seen(path: str | Path) -> SeenState:
    p = Path(path)
    if not p.exists():
        return SeenState(seen_urls=set(), seen_with_ts={})
    data = json.loads(p.read_text(encoding="utf-8"))

    urls = data.get("seen_urls", [])
    if not isinstance(urls, list):
        urls = []
    clean_urls = set([u for u in urls if isinstance(u, str) and u.strip()])

    # Load timestamps if available (backward compatible)
    ts = data.get("seen_with_ts", {})
    if not isinstance(ts, dict):
        ts = {}
    clean_ts = {k: v for k, v in ts.items() if isinstance(k, str) and k.strip() and isinstance(v, (int, float))}

    return SeenState(seen_urls=clean_urls, seen_with_ts=clean_ts)


def save_seen(path: str | Path, state: SeenState) -> None:
    p = Path(path)
    out = {
        "seen_urls": sorted(state.seen_urls),
        "seen_with_ts": {k: v for k, v in sorted(state.seen_with_ts.items())},
    }
    p.write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def mark_seen(state: SeenState, url: str) -> None:
    """Mark a URL as seen with current timestamp."""
    state.seen_urls.add(url)
    state.seen_with_ts[url] = time.time()


def clear_seen(path: str | Path) -> None:
    save_seen(path, SeenState(seen_urls=set(), seen_with_ts={}))


def cleanup_seen(state: SeenState) -> int:
    """
    Remove entries older than SEEN_TTL_SECONDS or trim to SEEN_MAX_ENTRIES.
    Returns the number of removed entries.
    """
    removed = 0
    now = time.time()

    # Remove expired entries
    expired = [url for url, ts in state.seen_with_ts.items() if (now - ts) > SEEN_TTL_SECONDS]
    for url in expired:
        state.seen_urls.discard(url)
        state.seen_with_ts.pop(url, None)
        removed += 1

    if expired:
        logger.info("Cleaned %d expired entries from seen.json (TTL=%dd)", len(expired), SEEN_TTL_SECONDS // 86400)

    # Trim to max size if still too large
    if len(state.seen_urls) > SEEN_MAX_ENTRIES:
        # Sort by timestamp, remove oldest
        sorted_urls = sorted(state.seen_with_ts.items(), key=lambda x: x[1])
        trim_count = len(state.seen_urls) - SEEN_MAX_ENTRIES
        for url, _ in sorted_urls[:trim_count]:
            state.seen_urls.discard(url)
            state.seen_with_ts.pop(url, None)
            removed += trim_count
        logger.info("Trimmed %d oldest entries (max=%d)", trim_count, SEEN_MAX_ENTRIES)

    return removed