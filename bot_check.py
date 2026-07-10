from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Optional

import requests
from requests.exceptions import RequestException

from config import Preferences
from env_loader import load_env
from main import SEEN_PATH, run_once
from notifier import send_telegram_message_to
from state import clear_seen
from user_prefs import (
    clear_user_state,
    get_user_preferences,
    get_user_state,
    set_user_preferences,
    set_user_state,
)

logger = logging.getLogger(__name__)


def _get_env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _tg(method: str, token: str, *, params: Optional[dict] = None, timeout_s: int = 40) -> Dict[str, Any]:
    url = f"https://api.telegram.org/bot{token}/{method}"
    r = requests.get(url, params=params or {}, timeout=timeout_s)
    r.raise_for_status()
    return r.json()


def _tg_safe(
    method: str,
    token: str,
    *,
    params: Optional[dict] = None,
    timeout_s: int = 40,
    max_retries: int = 6,
) -> Optional[Dict[str, Any]]:
    backoff_s = 1.0
    for attempt in range(max_retries):
        try:
            return _tg(method, token, params=params, timeout_s=timeout_s)
        except RequestException:
            if attempt == max_retries - 1:
                logger.error("Telegram long-poll failed after %d retries", max_retries)
                return None
            time.sleep(backoff_s)
            backoff_s = min(backoff_s * 2.0, 30.0)
    return None


def _handle_check(token: str, chat_id: str) -> None:
    # Pass chat_id directly instead of mutating os.environ (thread-safe)
    old = os.environ.get("TELEGRAM_CHAT_ID")
    os.environ["TELEGRAM_CHAT_ID"] = str(chat_id)
    try:
        prefs, _ = get_user_preferences(str(chat_id))
        run_once(prefs)
    except Exception as e:
        logger.error("run_once failed for chat %s: %s", chat_id, e)
        raise
    finally:
        if old is None:
            os.environ.pop("TELEGRAM_CHAT_ID", None)
        else:
            os.environ["TELEGRAM_CHAT_ID"] = old


def _handle_seen_clear(token: str, chat_id: str) -> None:
    clear_seen(SEEN_PATH)
    send_telegram_message_to(
        token,
        str(chat_id),
        "Cleared seen list (seen.json). Next `check` will re-send everything as new.",
    )


def _kb(button_rows: list[list[str]], *, one_time: bool = True) -> dict:
    return {
        "keyboard": [[{"text": b} for b in row] for row in button_rows],
        "resize_keyboard": True,
        "one_time_keyboard": one_time,
    }


def _start_filter_wizard(token: str, chat_id: str) -> None:
    set_user_state(str(chat_id), {"awaiting": "mode"})
    send_telegram_message_to(
        token,
        str(chat_id),
        "Choose your preferred mode.",
        reply_markup=_kb([["Online", "Offline", "Both"]]),
    )


def _sanitize_input(text: str, max_len: int = 200) -> str:
    """Basic input sanitization: strip, truncate, remove control chars."""
    text = (text or "").strip()
    text = "".join(c for c in text if c.isprintable())
    return text[:max_len]


def _handle_filter_reply(token: str, chat_id: str, text_raw: str) -> bool:
    """
    Returns True if message was consumed by the filter wizard.
    """
    st = get_user_state(str(chat_id))
    step = (st.get("awaiting") or "").strip()
    if not step:
        return False

    text = _sanitize_input(text_raw).lower()
    prefs, _ = get_user_preferences(str(chat_id))

    if step == "mode":
        if text not in ("online", "offline", "both"):
            send_telegram_message_to(token, str(chat_id), "Please choose: Online / Offline / Both.")
            return True
        prefs = Preferences(
            preferred_mode=text,
            paid_filter=prefs.paid_filter,
            status_filter=prefs.status_filter,
            domain=prefs.domain,
            category=prefs.category,
            include_keywords=prefs.include_keywords,
            exclude_keywords=prefs.exclude_keywords,
            city_must_include=prefs.city_must_include,
            min_prize_inr=prefs.min_prize_inr,
        )
        set_user_preferences(str(chat_id), prefs, setup_complete=False)
        set_user_state(str(chat_id), {"awaiting": "fee"})
        send_telegram_message_to(
            token,
            str(chat_id),
            "Choose paid/free filter.",
            reply_markup=_kb([["Free", "Paid", "Any"]]),
        )
        return True

    if step == "fee":
        if text not in ("free", "paid", "any"):
            send_telegram_message_to(token, str(chat_id), "Please choose: Free / Paid / Any.")
            return True
        prefs = Preferences(
            preferred_mode=prefs.preferred_mode,
            paid_filter=text,
            status_filter=prefs.status_filter,
            domain=prefs.domain,
            category=prefs.category,
            include_keywords=prefs.include_keywords,
            exclude_keywords=prefs.exclude_keywords,
            city_must_include=prefs.city_must_include,
            min_prize_inr=prefs.min_prize_inr,
        )
        set_user_preferences(str(chat_id), prefs, setup_complete=False)
        set_user_state(str(chat_id), {"awaiting": "status"})
        send_telegram_message_to(
            token,
            str(chat_id),
            "Choose event status.",
            reply_markup=_kb([["Live", "Recent", "Expired"], ["Any"]]),
        )
        return True

    if step == "status":
        if text not in ("live", "recent", "expired", "any"):
            send_telegram_message_to(token, str(chat_id), "Pick: Live / Recent / Expired / Any.")
            return True
        prefs = Preferences(
            preferred_mode=prefs.preferred_mode,
            paid_filter=prefs.paid_filter,
            status_filter=text,
            domain=prefs.domain,
            category=prefs.category,
            include_keywords=prefs.include_keywords,
            exclude_keywords=prefs.exclude_keywords,
            city_must_include=prefs.city_must_include,
            min_prize_inr=prefs.min_prize_inr,
        )
        set_user_preferences(str(chat_id), prefs, setup_complete=False)
        set_user_state(str(chat_id), {"awaiting": "domain"})
        send_telegram_message_to(
            token,
            str(chat_id),
            "Choose domain.",
            reply_markup=_kb([["Engineering", "Management"], ["Arts & Science", "Medicine"], ["Law", "Others"]]),
        )
        return True

    if step == "domain":
        allowed = {
            "engineering": "Engineering",
            "management": "Management",
            "arts & science": "Arts & Science",
            "medicine": "Medicine",
            "law": "Law",
            "others": "Others",
        }
        if text not in allowed:
            send_telegram_message_to(token, str(chat_id), "Choose a domain from the buttons.")
            return True
        prefs = Preferences(
            preferred_mode=prefs.preferred_mode,
            paid_filter=prefs.paid_filter,
            status_filter=prefs.status_filter,
            domain=allowed[text],
            category=prefs.category,
            include_keywords=prefs.include_keywords,
            exclude_keywords=prefs.exclude_keywords,
            city_must_include=prefs.city_must_include,
            min_prize_inr=prefs.min_prize_inr,
        )
        set_user_preferences(str(chat_id), prefs, setup_complete=False)
        set_user_state(str(chat_id), {"awaiting": "category"})

        send_telegram_message_to(
            token,
            str(chat_id),
            "Choose a category (or type your own category name).\nCommon options:",
            reply_markup=_kb(
                [
                    ["Software Development", "Data & Analytics"],
                    ["Artificial Intelligence & Machine Learning", "Cybersecurity"],
                    ["Cloud & Infrastructure", "Product Management"],
                    ["Quality Assurance & Testing", "IT & Systems"],
                    ["Any"],
                ],
                one_time=False,
            ),
        )
        return True

    if step == "category":
        cat = _sanitize_input(text_raw, max_len=100)
        if not cat:
            send_telegram_message_to(token, str(chat_id), "Please pick a category or type one.")
            return True
        if cat.lower() == "any":
            cat = "Any"

        prefs = Preferences(
            preferred_mode=prefs.preferred_mode,
            paid_filter=prefs.paid_filter,
            status_filter=prefs.status_filter,
            domain=prefs.domain,
            category=cat,
            include_keywords=prefs.include_keywords,
            exclude_keywords=prefs.exclude_keywords,
            city_must_include=prefs.city_must_include,
            min_prize_inr=prefs.min_prize_inr,
        )
        set_user_preferences(str(chat_id), prefs, setup_complete=True)
        clear_user_state(str(chat_id))
        send_telegram_message_to(
            token,
            str(chat_id),
            "Filter saved:\n"
            f"- Mode: {prefs.preferred_mode}\n"
            f"- Fee: {prefs.paid_filter}\n"
            f"- Status: {prefs.status_filter}\n"
            f"- Domain: {prefs.domain}\n"
            f"- Category: {prefs.category}\n"
            f"- City: {prefs.city_must_include or 'Any'}\n"
            f"- Min Prize: {prefs.min_prize_inr or 'Any'} INR\n\n"
            "Now send: check",
        )
        return True

    return False


def main() -> int:
    load_env()
    token = _get_env("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("Missing TELEGRAM_BOT_TOKEN")

    # FIX: SECURITY — Require TELEGRAM_CHAT_ID. Reject all if not set.
    allowed_chat_id = _get_env("TELEGRAM_CHAT_ID")
    if not allowed_chat_id:
        logger.error(
            "TELEGRAM_CHAT_ID is not set. Bot will NOT start for security. "
            "Set it in env/.env or as an environment variable."
        )
        raise SystemExit(
            "SECURITY: TELEGRAM_CHAT_ID is required. "
            "Without it, anyone who discovers the bot token can control it. "
            "Set TELEGRAM_CHAT_ID in env/.env and try again."
        )

    logger.info("Bot starting — allowed_chat_id=%s", allowed_chat_id)

    offset = int(_get_env("TG_OFFSET") or "0")

    while True:
        data = _tg_safe("getUpdates", token, params={"timeout": 30, "offset": offset + 1}, timeout_s=40)
        if not data:
            time.sleep(2)
            continue
        for upd in data.get("result", []) or []:
            upd_id = int(upd.get("update_id", 0))
            offset = max(offset, upd_id)

            msg = upd.get("message") or upd.get("edited_message") or {}
            text = (msg.get("text") or "").strip().lower()
            chat = msg.get("chat") or {}
            chat_id = str(chat.get("id") or "").strip()
            if not chat_id:
                continue

            # FIX: Always enforce chat_id check (no more "if allowed_chat_id" conditional)
            if chat_id != allowed_chat_id:
                logger.warning("Rejected message from unauthorized chat_id=%s", chat_id)
                continue

            # If user is in the filter wizard, consume their replies first.
            if _handle_filter_reply(token, chat_id, msg.get("text") or ""):
                continue

            if text in ("/start", "start"):
                prefs, setup = get_user_preferences(chat_id)
                if not setup:
                    send_telegram_message_to(token, chat_id, "Welcome! Let's set your filters first.")
                    _start_filter_wizard(token, chat_id)
                else:
                    send_telegram_message_to(
                        token,
                        chat_id,
                        "You're already set.\n"
                        f"- Mode: {prefs.preferred_mode}\n"
                        f"- Fee: {prefs.paid_filter}\n"
                        f"- Status: {prefs.status_filter}\n"
                        f"- Domain: {prefs.domain}\n"
                        f"- Category: {prefs.category}\n"
                        f"- City: {prefs.city_must_include or 'Any'}\n"
                        f"- Min Prize: {prefs.min_prize_inr or 'Any'} INR\n\n"
                        "Send: check\nOr change filters: /filter",
                    )
            elif text == "/filter":
                send_telegram_message_to(token, chat_id, "Let's update your filters.")
                _start_filter_wizard(token, chat_id)
            elif text == "check":
                send_telegram_message_to(token, chat_id, "Checking Unstop now...")
                try:
                    _handle_check(token, chat_id)
                except Exception as e:
                    send_telegram_message_to(token, chat_id, f"Error while checking: {e}")
                    logger.error("Check command failed for chat %s: %s", chat_id, e, exc_info=True)
            elif text in ("seen clear", "/seen_clear"):
                _handle_seen_clear(token, chat_id)
            elif text in ("help", "/help"):
                send_telegram_message_to(
                    token,
                    chat_id,
                    "Commands:\n"
                    "- /start: setup\n"
                    "- /filter: change filters\n"
                    "- check: scan now\n"
                    "- seen clear: reset seen list\n"
                    "- /help: this message",
                )

        time.sleep(1)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    raise SystemExit(main())