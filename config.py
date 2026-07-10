from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List


@dataclass(frozen=True)
class Preferences:
    # preferred_mode: "online" | "offline" | "both"
    preferred_mode: str
    # paid_filter: "free" | "paid" | "any"
    paid_filter: str
    # status_filter: "live" | "expired" | "recent" | "any"
    status_filter: str
    domain: str
    category: str
    include_keywords: List[str]
    exclude_keywords: List[str]
    # NEW: city filter — if non-empty, hackathon location must contain this string
    city_must_include: str = ""
    # NEW: minimum prize in INR — 0 means no filter
    min_prize_inr: int = 0


PREFERENCES = Preferences(
    preferred_mode="both",
    paid_filter="any",
    status_filter="any",
    domain="Any",
    category="Any",
    include_keywords=[
        "hackathon",
        "hack",
        "ideathon",
        "innovation",
        "challenge",
        "build",
        "code",
    ],
    exclude_keywords=[
        "paid entry",
        "entry fee",
        "registration fee",
    ],
    city_must_include="",
    min_prize_inr=0,
)


def normalize_keywords(words: Iterable[str]) -> list[str]:
    return [w.strip().lower() for w in words if w and w.strip()]