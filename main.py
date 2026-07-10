from __future__ import annotations

import logging
import os
import sys
from typing import List

from env_loader import load_env
from classifier import classify_with_groq
from config import PREFERENCES, Preferences
from filter import stage1_filter
from notifier import format_hackathon_message, load_telegram_config, send_summary, send_telegram_message
from scraper import Hackathon, fetch_open_hackathons
from state import load_seen, save_seen, mark_seen, cleanup_seen

logger = logging.getLogger(__name__)

SEEN_PATH = os.environ.get("SEEN_PATH", "seen.json")


def _should_use_llm() -> bool:
    return (os.environ.get("USE_LLM", "1").strip().lower() not in ("0", "false", "no"))


def run_once(prefs: Preferences | None = None) -> int:
    load_env()
    prefs = prefs or PREFERENCES

    logger.info("Starting Unstop hackathon scan...")
    hacks = fetch_open_hackathons()
    logger.info("Fetched %d hackathons from Unstop", len(hacks))

    state = load_seen(SEEN_PATH)

    # Run cleanup before processing
    removed = cleanup_seen(state)
    if removed:
        logger.info("Cleaned %d stale entries from seen.json", removed)

    tg = load_telegram_config()
    if tg is None:
        logger.warning("Missing TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID; will run but not notify.")

    new_items: List[Hackathon] = []
    for h in hacks:
        if h.url in state.seen_urls:
            continue

        s1 = stage1_filter(h, prefs)
        if s1.decision == "fail":
            # FIX: Mark filtered-out items as seen too, so we don't re-evaluate
            mark_seen(state, h.url)
            logger.debug("Filtered out: %s — %s", h.title[:50], s1.reason)
            continue

        if s1.decision == "pass":
            new_items.append(h)
            continue

        # ambiguous => LLM
        if _should_use_llm():
            dec = classify_with_groq(h)
            if dec.is_relevant:
                if dec.mode_detected and dec.mode_detected != "unknown":
                    h = Hackathon(
                        title=h.title,
                        description=h.description,
                        mode=dec.mode_detected,
                        location=h.location,
                        deadline=h.deadline,
                        url=h.url,
                        status=h.status,
                        fee_type=h.fee_type,
                        tags=h.tags or [],
                        prize_raw=h.prize_raw,
                    )
                new_items.append(h)
            else:
                # LLM said not relevant — mark as seen to skip next time
                mark_seen(state, h.url)
                logger.debug("LLM rejected: %s — %s", h.title[:50], dec.reason)
        else:
            # LLM disabled, treat ambiguous as skip
            mark_seen(state, h.url)
            continue

    # Notify
    if tg is not None:
        send_summary(tg, len(new_items))
        for h in new_items:
            send_telegram_message(tg, format_hackathon_message(h))

    # Mark all new items as seen with timestamps
    for h in new_items:
        mark_seen(state, h.url)

    save_seen(SEEN_PATH, state)
    logger.info("Done. New sent: %d. Total seen: %d", len(new_items), len(state.seen_urls))
    return 0


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    raise SystemExit(run_once())