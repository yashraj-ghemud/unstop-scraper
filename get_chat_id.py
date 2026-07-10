from __future__ import annotations

import logging
import os
from typing import Any, Dict

import requests

from env_loader import load_env

logger = logging.getLogger(__name__)


def main() -> int:
    load_env()
    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        raise SystemExit("Missing TELEGRAM_BOT_TOKEN (set it in env/.env first).")

    r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=30)
    r.raise_for_status()
    data: Dict[str, Any] = r.json()

    for upd in data.get("result", []) or []:
        msg = upd.get("message") or upd.get("edited_message") or {}
        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        username = chat.get("username")
        first_name = chat.get("first_name")
        text = msg.get("text")
        if chat_id is None:
            continue
        logger.info("chat_id=%s username=@%s name=%s last_text=%s", chat_id, username, first_name, text)

    logger.info("Tip: send a message to your bot, then run this again.")
    return 0


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    raise SystemExit(main())