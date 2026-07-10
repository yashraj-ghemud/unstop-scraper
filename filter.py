from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from config import Preferences, normalize_keywords
from scraper import Hackathon, parse_prize_inr

logger = logging.getLogger(__name__)

HACKATHON_TITLE_HINTS = [
    "hackathon",
    "hack",
    "ideathon",
    "innovation",
    "challenge",
    "code",
    "build",
]


@dataclass(frozen=True)
class Stage1Result:
    decision: str  # "pass" | "fail" | "ambiguous"
    reason: str


def _contains_any(haystack: str, needles: list[str]) -> bool:
    hs = haystack.lower()
    return any(n in hs for n in needles if n)


def _contains_any_word(haystack: str, words: list[str]) -> bool:
    hs = haystack.lower()
    for w in words:
        w = (w or "").strip().lower()
        if not w:
            continue
        if re.search(rf"(?<!\w){re.escape(w)}(?!\w)", hs):
            return True
    return False


def stage1_filter(h: Hackathon, prefs: Preferences) -> Stage1Result:
    title = (h.title or "").strip()
    desc = (h.description or "").strip()
    mode = (h.mode or "").strip().lower()
    status = (h.status or "").strip().lower()
    fee_type = (h.fee_type or "").strip().lower()
    tags = " ".join([str(t) for t in (h.tags or [])]).lower()
    location = (h.location or "").strip().lower()

    include = normalize_keywords(prefs.include_keywords)
    exclude = normalize_keywords(prefs.exclude_keywords)
    preferred_mode = (prefs.preferred_mode or "both").strip().lower()
    paid_filter = prefs.paid_filter or "any"
    status_filter = prefs.status_filter or "any"
    domain = prefs.domain or ""
    category = prefs.category or ""

    text_blob = f"{title}\n{desc}\n{mode}\n{status}\n{fee_type}\n{tags}\n{location}".lower()

    if exclude and _contains_any(text_blob, exclude):
        return Stage1Result("fail", "Matched exclude keyword")

    # --- NEW: city_must_include filter ---
    city_filter = (prefs.city_must_include or "").strip().lower()
    if city_filter:
        if location and city_filter not in location:
            return Stage1Result("fail", f"City filter mismatch (need '{city_filter}', got '{location}')")
        # If location is empty/unknown, don't block — send to LLM if ambiguous

    # --- NEW: min_prize_inr filter ---
    min_prize = getattr(prefs, "min_prize_inr", 0) or 0
    if min_prize > 0 and h.prize_raw:
        try:
            # Extract number from prize_raw
            import re as _re
            nums = _re.findall(r"(\d[\d,]*)", h.prize_raw)
            if nums:
                max_val = max(int(n.replace(",", "")) for n in nums)
                if max_val < min_prize:
                    return Stage1Result("fail", f"Prize too low ({max_val} < {min_prize} INR)")
        except (ValueError, IndexError):
            pass  # Can't parse prize, don't block

    # Paid/free filter
    if paid_filter in ("free", "paid"):
        if fee_type not in ("", "unknown") and paid_filter != fee_type:
            return Stage1Result("fail", f"Fee type mismatch ({fee_type})")

    # Status filter
    if status_filter in ("live", "expired", "recent"):
        if status and status != "unknown" and status_filter != status:
            return Stage1Result("fail", f"Status mismatch ({status})")

    # Mode must match if preference isn't both.
    if preferred_mode in ("online", "offline"):
        if mode in ("unknown", ""):
            return Stage1Result("ambiguous", "Mode missing")
        if preferred_mode != mode and not (preferred_mode == "online" and mode == "both") and not (
            preferred_mode == "offline" and mode == "both"
        ):
            return Stage1Result("fail", f"Mode mismatch ({mode})")

    # Domain/category (best-effort). Do not block if not detected.
    if h.tags and domain and domain != "any":
        if domain not in tags and domain not in text_blob:
            return Stage1Result("fail", "Domain mismatch")
    if h.tags and category and category != "any":
        if category not in tags and category not in text_blob:
            return Stage1Result("fail", "Category mismatch")

    # Must look like a hackathon: title contains hack words OR include_keywords match.
    if include:
        if not _contains_any(title.lower(), include) and not _contains_any(desc.lower(), include):
            if _contains_any_word(title, HACKATHON_TITLE_HINTS):
                return Stage1Result("ambiguous", "No include keyword match; title looks hackathon-ish")
            return Stage1Result("fail", "No include keyword match")
    else:
        if not _contains_any_word(title, HACKATHON_TITLE_HINTS):
            return Stage1Result("fail", "Title doesn't look like a hackathon")

    # If description is long and location/mode are unknown, send to LLM.
    if len(desc) > 350 and mode in ("unknown", ""):
        return Stage1Result("ambiguous", "Needs LLM classification (long description)")

    return Stage1Result("pass", "Matched stage-1 rules")