from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from config import Preferences, PREFERENCES

logger = logging.getLogger(__name__)

PREFS_PATH = Path("user_prefs.json")
STATE_PATH = Path("user_state.json")


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else {}
    except Exception as e:
        logger.error("Failed to load %s: %s", path, e)
        return {}


def _save_json(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def get_user_preferences(chat_id: str) -> Tuple[Preferences, bool]:
    data = _load_json(PREFS_PATH)
    u = data.get(str(chat_id), {})
    if not isinstance(u, dict):
        return (PREFERENCES, False)
    prefs_obj = u.get("prefs", {})
    setup_complete = bool(u.get("setup_complete", False))
    if not isinstance(prefs_obj, dict):
        return (PREFERENCES, setup_complete)

    try:
        prefs = Preferences(
            preferred_mode=str(prefs_obj.get("preferred_mode", PREFERENCES.preferred_mode)),
            paid_filter=str(prefs_obj.get("paid_filter", PREFERENCES.paid_filter)),
            status_filter=str(prefs_obj.get("status_filter", PREFERENCES.status_filter)),
            domain=str(prefs_obj.get("domain", PREFERENCES.domain)),
            category=str(prefs_obj.get("category", PREFERENCES.category)),
            include_keywords=list(prefs_obj.get("include_keywords", PREFERENCES.include_keywords)),
            exclude_keywords=list(prefs_obj.get("exclude_keywords", PREFERENCES.exclude_keywords)),
            city_must_include=str(prefs_obj.get("city_must_include", PREFERENCES.city_must_include)),
            min_prize_inr=int(prefs_obj.get("min_prize_inr", PREFERENCES.min_prize_inr)),
        )
        return (prefs, setup_complete)
    except Exception as e:
        logger.error("Failed to parse preferences for chat %s: %s", chat_id, e)
        return (PREFERENCES, setup_complete)


def set_user_preferences(chat_id: str, prefs: Preferences, *, setup_complete: bool = True) -> None:
    data = _load_json(PREFS_PATH)
    data[str(chat_id)] = {"prefs": asdict(prefs), "setup_complete": bool(setup_complete)}
    _save_json(PREFS_PATH, data)


def get_user_state(chat_id: str) -> dict:
    data = _load_json(STATE_PATH)
    st = data.get(str(chat_id), {})
    return st if isinstance(st, dict) else {}


def set_user_state(chat_id: str, state: dict) -> None:
    data = _load_json(STATE_PATH)
    data[str(chat_id)] = state
    _save_json(STATE_PATH, data)


def clear_user_state(chat_id: str) -> None:
    data = _load_json(STATE_PATH)
    data.pop(str(chat_id), None)
    _save_json(STATE_PATH, data)