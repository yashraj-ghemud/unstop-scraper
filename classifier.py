from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests

from scraper import Hackathon

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLMDecision:
    is_relevant: bool
    mode_detected: str
    reason: str


SYSTEM_PROMPT = """You are a strict classifier for hackathon relevance.
Decide if the opportunity is relevant for a student interested in hackathons.
Consider: online eligibility, student-friendly, not obviously paid-entry.
Return ONLY valid JSON with keys: is_relevant (boolean), mode_detected (string), reason (string).
"""


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    text = (text or "").strip()
    if not text:
        return None
    # If model wraps in code-fences, strip them.
    if text.startswith("```"):
        text = text.strip("`").strip()
        if "\n" in text:
            text = text.split("\n", 1)[1].strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        return None
    return None


def classify_with_groq(
    h: Hackathon,
    *,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    timeout_s: int = 40,
) -> LLMDecision:
    """
    Uses Groq's OpenAI-compatible chat completions.
    Env vars:
      - GROQ_API_KEY (required)
      - GROQ_MODEL (optional; default llama3-70b-8192)
    """
    api_key = api_key or os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        return LLMDecision(False, "unknown", "GROQ_API_KEY not set; skipping LLM")

    model = model or os.environ.get("GROQ_MODEL", "llama3-70b-8192")

    user_prompt = f"""Classify this hackathon:
Title: {h.title}
Mode: {h.mode}
Location: {h.location}
Deadline: {h.deadline}
URL: {h.url}

Description:
{h.description}
"""

    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    }

    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=timeout_s,
        )
        r.raise_for_status()
    except requests.RequestException as e:
        logger.error("Groq API request failed: %s", e)
        return LLMDecision(False, "unknown", f"Groq API error: {e}")

    data = r.json()
    content = (
        (data.get("choices") or [{}])[0]
        .get("message", {})
        .get("content", "")
    )
    obj = _extract_json(content) or {}

    is_rel = bool(obj.get("is_relevant", False))
    mode_detected = str(obj.get("mode_detected", "unknown") or "unknown")
    reason = str(obj.get("reason", "") or "").strip()[:500]
    if not reason:
        reason = "No reason returned"
    logger.info("LLM decision for '%s': relevant=%s, mode=%s, reason=%s", h.title[:40], is_rel, mode_detected, reason)
    return LLMDecision(is_rel, mode_detected, reason)