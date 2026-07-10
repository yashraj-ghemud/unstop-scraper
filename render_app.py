"""
Render deployment entry point.
Runs both:
  1. Interactive Telegram bot (long-polling) — responds to /start, check, /filter
  2. Scheduled scan every 6 hours — same as GitHub Actions cron

Flask provides a /health endpoint so Render + UptimeRobot can keep the service alive.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Optional

from flask import Flask

logger = logging.getLogger(__name__)

app = Flask(__name__)

SCAN_INTERVAL_S = 6 * 3600  # 6 hours


@app.route("/health")
def health():
    return "ok", 200


def _run_bot_listener():
    """Start the interactive Telegram bot (long-polling loop)."""
    try:
        from bot_check import main as bot_main
        logger.info("[Render] Starting interactive bot listener...")
        bot_main()
    except SystemExit:
        logger.info("[Render] Bot listener exited.")
    except Exception as e:
        logger.error("[Render] Bot listener crashed: %s", e, exc_info=True)


def _run_scheduled_scanner():
    """Run main.py scan every SCAN_INTERVAL_S seconds."""
    from env_loader import load_env
    load_env()

    from main import run_once

    logger.info("[Render] Scheduled scanner started (interval: %dh)", SCAN_INTERVAL_S // 3600)

    while True:
        try:
            logger.info("[Render] Running scheduled scan...")
            run_once()
        except Exception as e:
            logger.error("[Render] Scheduled scan failed: %s", e, exc_info=True)
        logger.info("[Render] Next scan in %d hours", SCAN_INTERVAL_S // 3600)
        time.sleep(SCAN_INTERVAL_S)


@app.route("/trigger")
def trigger_scan():
    """Manually trigger a scan via HTTP (for debugging)."""
    threading.Thread(target=_run_single_scan, daemon=True).start()
    return "scan triggered", 200


def _run_single_scan():
    try:
        from env_loader import load_env
        load_env()
        from main import run_once
        run_once()
    except Exception as e:
        logger.error("[Render] Triggered scan failed: %s", e)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    port = int(os.environ.get("PORT", "10000"))

    # Start interactive bot in a background thread
    bot_thread = threading.Thread(target=_run_bot_listener, daemon=True, name="bot-listener")
    bot_thread.start()

    # Start scheduled scanner in a background thread
    scan_thread = threading.Thread(target=_run_scheduled_scanner, daemon=True, name="scheduled-scanner")
    scan_thread.start()

    logger.info("[Render] Flask server starting on port %d", port)
    logger.info("[Render] Endpoints: /health, /trigger")
    logger.info("[Render] Bot listener + Scheduled scanner running in background threads")

    # Run Flask server on the main thread (required by Render)
    app.run(host="0.0.0.0", port=port)