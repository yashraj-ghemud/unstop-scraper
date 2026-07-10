from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Optional

import requests
from requests.exceptions import RequestException

from scraper import Hackathon

logger = logging.getLogger(__name__)

# Rate limit: minimum seconds between consecutive Telegram messages
# Telegram allows ~30 msg/sec for bots, but we throttle to avoid burst spikes
MSG_INTERVAL_S = 0.5
_last_msg_time: float = 0.0


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str
    chat_id: str


def load_telegram_config() -> Optional[TelegramConfig]:
    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat_id:
        return None
    return TelegramConfig(bot_token=token, chat_id=chat_id)


def _escape(s: str) -> str:
    return (s or "").strip()


def _rate_limit() -> None:
    """Sleep if needed to respect MSG_INTERVAL_S between sends."""
    global _last_msg_time
    now = time.time()
    elapsed = now - _last_msg_time
    if elapsed < MSG_INTERVAL_S:
        time.sleep(MSG_INTERVAL_S - elapsed)
    _last_msg_time = time.time()


def format_hackathon_message(h: Hackathon) -> str:
    title = _escape(h.title)
    mode = _escape(h.mode or "unknown")
    status = _escape(h.status or "unknown")
    fee_type = _escape(h.fee_type or "unknown")
    deadline = _escape(h.deadline or "Not mentioned")
    url = _escape(h.url)
    location = _escape(h.location or "Not mentioned")
    prize = _escape(h.prize_raw or "Not mentioned")

    lines = [
        "\U0001f6a8 New Hackathon Alert!",
        f"\U0001f3c6 {title}",
        f"\U0001f9d1\u200d\U0001f4bb Mode: {mode}",
        f"\U0001f4cd Location: {location}",
        f"\U0001f4cc Status: {status}",
        f"\U0001f4b3 Fee: {fee_type}",
        f"\U0001f4b0 Prize: {prize}",
        f"\u23f0 Deadline: {deadline}",
        f"\U0001f517 {url}",
    ]
    return "\n".join(lines)


def send_telegram_message(cfg: TelegramConfig, text: str, *, timeout_s: int = 20) -> None:
    send_telegram_message_to(cfg.bot_token, cfg.chat_id, text, timeout_s=timeout_s)


def send_telegram_message_to(
    bot_token: str,
    chat_id: str,
    text: str,
    *,
    reply_markup: Optional[dict[str, Any]] = None,
    timeout_s: int = 20,
) -> None:
    _rate_limit()
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    backoff_s = 1.0
    max_retries = 6
    for attempt in range(max_retries):
        try:
            r = requests.post(url, json=payload, timeout=timeout_s)
            r.raise_for_status()
            return
        except RequestException as e:
            if attempt == max_retries - 1:
                logger.error("Telegram send failed after %d retries: %s", max_retries, e)
                return
            logger.warning("Telegram send attempt %d failed: %s — retrying in %.1fs", attempt + 1, e, backoff_s)
            time.sleep(backoff_s)
            backoff_s = min(backoff_s * 2.0, 30.0)


def send_summary(cfg: TelegramConfig, new_count: int) -> None:
    send_telegram_message(cfg, f"\u2705 Unstop scan complete. New hackathons found: {new_count}")