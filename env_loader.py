from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)


def load_env() -> None:
    """
    Loads secrets from `env/.env` if present.
    Environment variables already set (e.g. GitHub Actions Secrets) take precedence.
    """
    p = Path("env") / ".env"
    if p.exists():
        load_dotenv(p, override=False)
        logger.info("Loaded env from %s", p)
    else:
        logger.debug("No env/.env file found; relying on system env vars")

    # Robustness: users sometimes paste `TELEGRAM_BOT_TOKEN=...` into the value by mistake.
    # If that happens, normalize it at runtime.
    tok = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if tok.lower().startswith("telegram_bot_token="):
        os.environ["TELEGRAM_BOT_TOKEN"] = tok.split("=", 1)[1].strip()
        logger.warning("Normalized TELEGRAM_BOT_TOKEN (user had pasted key=value)")