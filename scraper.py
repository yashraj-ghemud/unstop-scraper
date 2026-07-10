from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

import requests
from bs4 import BeautifulSoup

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None
    PlaywrightTimeoutError = Exception

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Hackathon:
    title: str
    description: str
    mode: str
    location: str
    deadline: str
    url: str
    status: str  # live|expired|recent|unknown
    fee_type: str  # free|paid|any|unknown
    tags: List[str]
    prize_raw: str = ""


_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0.0.0 Safari/537.36"
)

# The REAL Unstop public API (discovered from network traffic)
_UNSTOP_API = "https://unstop.com/api/public/opportunity/search-result"


def _as_text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    return str(v)


def _pick(d: Dict[str, Any], keys: Iterable[str]) -> Any:
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None


def parse_prize_inr(obj: Dict[str, Any]) -> int:
    """Extract the largest numeric prize amount in INR from a hackathon dict."""
    # Check the prizes list first (Unstop API format)
    prizes = obj.get("prizes")
    if isinstance(prizes, list):
        for p in prizes:
            cash = p.get("cash") if isinstance(p, dict) else None
            if cash is not None:
                nums = re.findall(r"(\d[\d,]*)", str(cash))
                for n in nums:
                    try:
                        return int(n.replace(",", ""))
                    except ValueError:
                        pass

    # Fallback: check raw prize fields
    raw = _pick(obj, ["prize", "prize_money", "prizeMoney", "total_prize", "totalPrize", "prize_amount"])
    s = _as_text(raw).lower()
    if not s:
        return 0
    nums = re.findall(r"(\d[\d,]*)", s)
    if not nums:
        return 0
    vals = []
    for n in nums:
        try:
            vals.append(int(n.replace(",", "")))
        except ValueError:
            pass
    return max(vals) if vals else 0


def _prize_raw_from_obj(obj: Dict[str, Any]) -> str:
    """Build a human-readable prize string."""
    prizes = obj.get("prizes")
    if isinstance(prizes, list) and prizes:
        parts = []
        for p in prizes:
            if not isinstance(p, dict):
                continue
            rank = p.get("rank", "")
            cash = p.get("cash")
            currency_sym = p.get("currency", "")
            if cash and str(cash).strip():
                parts.append(f"{rank}: {currency_sym}{cash}")
        if parts:
            return " | ".join(parts[:3])

    # Fallback
    return _as_text(
        _pick(obj, ["prize", "prize_money", "prizeMoney", "total_prize", "totalPrize", "prize_amount"])
    )


def _normalize_mode(mode: str) -> str:
    m = mode.strip().lower()
    if not m:
        return "unknown"
    if "online" in m or "virtual" in m:
        return "online"
    if "offline" in m or "in-person" in m or "in person" in m:
        return "offline"
    if "hybrid" in m:
        return "both"
    return m


def _location_from_obj(obj: Dict[str, Any]) -> str:
    """Extract location from Unstop API response."""
    # address_with_country_logo.city
    addr = obj.get("address_with_country_logo")
    if isinstance(addr, dict):
        city = addr.get("city", "")
        state = addr.get("state", "")
        parts = [p for p in [city, state] if p]
        if parts:
            return ", ".join(parts)

    # Fallback: check locations list or simple fields
    locs = obj.get("locations")
    if isinstance(locs, list) and locs:
        return _as_text(locs[0])

    return _as_text(_pick(obj, ["location", "city", "venue", "address", "event_city"]))


def _tags_from_obj(obj: Dict[str, Any]) -> List[str]:
    """Extract tags/skills from Unstop API response."""
    tags = []
    # required_skills
    skills = obj.get("required_skills")
    if isinstance(skills, list):
        for s in skills:
            if isinstance(s, dict):
                skill_name = s.get("skill") or s.get("skill_name", "")
                if skill_name:
                    tags.append(str(skill_name))

    # workfunction
    wf = obj.get("workfunction")
    if isinstance(wf, list):
        for w in wf:
            if isinstance(w, dict):
                name = w.get("name", "")
                if name:
                    tags.append(str(name))

    return tags


def _hackathon_from_unstop_api(obj: Dict[str, Any]) -> Optional[Hackathon]:
    """Parse a single hackathon from the Unstop public API format."""
    title = _as_text(obj.get("title", "")).strip()
    if not title:
        return None

    # Description — strip HTML tags
    details = _as_text(obj.get("details", ""))
    description = re.sub(r"<[^>]+>", " ", details).strip()
    description = re.sub(r"\s+", " ", description).strip()

    # URL
    url = _as_text(obj.get("seo_url", "")).strip()
    if not url:
        url = _as_text(obj.get("public_url", "")).strip()
    if url and url.startswith("/"):
        url = "https://unstop.com" + url

    # Mode — from "region" field
    region = _as_text(obj.get("region", ""))
    mode = _normalize_mode(region)

    # Status — from "status" field
    raw_status = _as_text(obj.get("status", ""))
    if raw_status.upper() == "LIVE":
        status = "live"
    elif raw_status.upper() in ("EXPIRED", "CLOSED", "ENDED"):
        status = "expired"
    else:
        status = "live" if obj.get("regn_open") else "unknown"

    # Fee
    is_paid = obj.get("isPaid")
    if is_paid is True:
        fee_type = "paid"
    elif is_paid is False:
        fee_type = "free"
    else:
        fee_type = "unknown"

    # Deadline — from regnRequirements or end_date
    deadline = ""
    regn = obj.get("regnRequirements")
    if isinstance(regn, dict):
        deadline = _as_text(regn.get("end_regn_dt", ""))
    if not deadline:
        deadline = _as_text(obj.get("end_date", ""))
    # Clean up ISO format
    deadline = deadline.replace("T", " ").split("+")[0].strip()

    location = _location_from_obj(obj)
    tags = _tags_from_obj(obj)
    prize_raw = _prize_raw_from_obj(obj)

    return Hackathon(
        title=title,
        description=description[:500],  # Cap description length
        mode=mode,
        location=location,
        deadline=deadline,
        url=url,
        status=status,
        fee_type=fee_type,
        tags=tags,
        prize_raw=prize_raw,
    )


# ---- Legacy parsers for fallback methods ----

def _hackathon_from_obj(obj: Dict[str, Any]) -> Optional[Hackathon]:
    title = _as_text(_pick(obj, ["title", "name", "event_name", "opportunityTitle"])).strip()
    if not title:
        return None
    description = _as_text(_pick(obj, ["description", "desc", "about", "detail", "summary"]))
    url = _as_text(_pick(obj, ["url", "link", "permalink", "opportunityUrl", "public_url"])).strip()
    if url and url.startswith("/"):
        url = "https://unstop.com" + url

    mode = _normalize_mode(_as_text(_pick(obj, ["mode", "event_mode", "eventMode", "event_type"])))
    location = _as_text(_pick(obj, ["location", "city", "venue", "address", "event_city"]))
    deadline = _as_text(
        _pick(obj, ["deadline", "registration_deadline", "reg_deadline", "registrationDeadline", "end_date", "endDate"])
    )
    return Hackathon(
        title=title,
        description=description.strip(),
        mode=mode,
        location=location.strip(),
        deadline=deadline.strip(),
        url=url,
        status="unknown",
        fee_type="unknown",
        tags=[],
        prize_raw=_prize_raw_from_obj(obj),
    )


def _extract_items_from_json(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if not isinstance(data, dict):
        return []
    for key in ("data", "items", "results", "hackathons", "opportunities", "list"):
        v = data.get(key)
        if isinstance(v, list):
            return [x for x in v if isinstance(x, dict)]
        if isinstance(v, dict):
            for subkey in ("items", "results", "data", "list"):
                sv = v.get(subkey)
                if isinstance(sv, list):
                    return [x for x in sv if isinstance(x, dict)]
    return []


def _effective_max_pages(max_pages: Optional[int]) -> int:
    if isinstance(max_pages, int) and max_pages > 0:
        return max_pages
    env_val = (os.environ.get("SCRAPE_MAX_PAGES") or "").strip()
    if env_val.isdigit() and int(env_val) > 0:
        return int(env_val)
    return 10  # Reduced default — API gives 18 per page, 10 pages = 180


# =============================================================================
#  PRIMARY: Unstop Public API (works without Playwright, no browser needed)
# =============================================================================

def _fetch_from_unstop_public_api(max_pages: int, timeout_s: int) -> List[Hackathon]:
    """
    Uses the Unstop public API endpoint that the website itself calls.
    This is the most reliable method and requires only `requests`.
    """
    session = requests.Session()
    session.headers.update({
        "User-Agent": _UA,
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://unstop.com",
        "Referer": "https://unstop.com/hackathons?oppstatus=open",
    })

    hacks: Dict[str, Hackathon] = {}
    last_page = None

    for page_num in range(1, max_pages + 1):
        params = {
            "opportunity": "hackathons",
            "page": page_num,
            "per_page": 18,
            "oppstatus": "open",
            "sortBy": "",
            "orderBy": "",
            "filter_condition": "",
        }

        try:
            r = session.get(_UNSTOP_API, params=params, timeout=timeout_s)
            r.raise_for_status()
        except requests.RequestException as e:
            logger.error("Unstop public API request failed on page %d: %s", page_num, e)
            break

        try:
            data = r.json()
        except (ValueError, TypeError):
            logger.error("Unstop public API returned non-JSON on page %d", page_num)
            break

        # Navigate: response.data.data = list of hackathons
        outer_data = data.get("data") if isinstance(data, dict) else None
        if not isinstance(outer_data, dict):
            logger.warning("Unstop API unexpected structure on page %d", page_num)
            break

        items = outer_data.get("data")
        if not isinstance(items, list) or not items:
            logger.info("Unstop API: no more items after page %d", page_num)
            break

        # Detect last page for logging
        if last_page is None:
            last_page = outer_data.get("last_page", "?")
            logger.info("Unstop API: total pages=%s, per_page=18", last_page)

        page_count = 0
        for obj in items:
            if not isinstance(obj, dict):
                continue
            h = _hackathon_from_unstop_api(obj)
            if h is None or not h.url:
                continue
            hacks[h.url] = h
            page_count += 1

        logger.debug("Unstop API page %d: parsed %d hackathons (total: %d)", page_num, page_count, len(hacks))

        # Stop if we've reached the last page
        if isinstance(last_page, int) and page_num >= last_page:
            break

    result = list(hacks.values())
    logger.info("Unstop public API: fetched %d hackathons", len(result))
    return result


# =============================================================================
#  FALLBACK 1: Playwright rendered scraping
# =============================================================================

def _fetch_from_unstop_rendered(max_pages: int, timeout_s: int) -> List[Hackathon]:
    """Rendered scraper via Playwright. Falls back silently when unavailable."""
    if sync_playwright is None:
        logger.debug("Playwright not installed; skipping rendered scraper")
        return []

    hacks: dict[str, Hackathon] = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto("https://unstop.com/hackathons?oppstatus=open", wait_until="domcontentloaded", timeout=timeout_s * 1000)
            try:
                page.wait_for_selector("a[href*='/hackathons/']", timeout=timeout_s * 1000)
            except PlaywrightTimeoutError:
                logger.warning("Playwright: timed out waiting for hackathon links")
                browser.close()
                return []

            links = page.eval_on_selector_all(
                "a[href*='/hackathons/']",
                """els => els.map(e => ({
                    href: e.href || '',
                    text: (e.innerText || e.textContent || '').trim()
                }))""",
            )
            for row in links or []:
                href = str((row or {}).get("href") or "").strip()
                text = str((row or {}).get("text") or "").strip()
                if not href or "/hackathons/" not in href:
                    continue
                if href.rstrip("/").endswith("/hackathons"):
                    continue
                title = " ".join(text.split())[:220] if text else href.rsplit("/", 1)[-1].replace("-", " ")
                hacks[href] = Hackathon(
                    title=title, description="", mode="unknown", location="",
                    deadline="", url=href, status=_infer_status(text),
                    fee_type=_infer_fee_type(text), tags=[],
                )

            browser.close()
            logger.info("Playwright: scraped %d hackathons", len(hacks))
    except Exception as e:
        logger.error("Playwright scraper failed: %s — falling back", e)
        return []

    return list(hacks.values())


# =============================================================================
#  FALLBACK 2: HTML scraping of api.unstop.com
# =============================================================================

def _fetch_from_api_site(session: requests.Session, timeout_s: int, max_pages: int = 20) -> List[Hackathon]:
    hacks: dict[str, Hackathon] = {}
    stable_no_new_pages = 0
    for page in range(1, max_pages + 1):
        try:
            r = session.get("https://api.unstop.com/hackathons/", params={"page": page}, timeout=timeout_s)
            r.raise_for_status()
        except requests.RequestException as e:
            logger.error("API site scraper failed on page %d: %s", page, e)
            break

        soup = BeautifulSoup(r.text or "", "html.parser")
        before = len(hacks)
        for a in soup.find_all("a", href=True):
            href = str(a.get("href") or "")
            if not href:
                continue
            if href.startswith("/"):
                href = "https://api.unstop.com" + href
            if not href.startswith("https://api.unstop.com/hackathons/"):
                continue
            if href.rstrip("/").endswith("/hackathons"):
                continue

            title = (a.get_text(" ", strip=True) or "").strip()
            if not title:
                prev_h = a.find_previous(["h1", "h2", "h3"])
                if prev_h:
                    title = (prev_h.get_text(" ", strip=True) or "").strip()
            if not title:
                title = href.rsplit("/", 1)[-1].replace("-", " ").strip()

            context = ""
            parent = a.parent
            if parent:
                context = parent.get_text(" ", strip=True)

            hacks[href] = Hackathon(
                title=title, description="", mode="unknown", location="",
                deadline="", url=href.replace("https://api.unstop.com", "https://unstop.com"),
                status=_infer_status(context), fee_type=_infer_fee_type(context), tags=[],
            )

        if len(hacks) == before:
            stable_no_new_pages += 1
            if stable_no_new_pages >= 3:
                break
        else:
            stable_no_new_pages = 0

    logger.info("API site scraper: found %d hackathons", len(hacks))
    return list(hacks.values())


# =============================================================================
#  Fallback 3: Old api.unstop.com JSON endpoint
# =============================================================================

def _fetch_from_old_api(max_pages: int, timeout_s: int) -> List[Hackathon]:
    session = requests.Session()
    session.headers.update({"User-Agent": _UA, "Accept": "application/json, text/html;q=0.9,*/*;q=0.8"})

    out: List[Hackathon] = []
    for page in range(1, max_pages + 1):
        try:
            r = session.get("https://api.unstop.com/hackathons/", params={"page": page}, timeout=timeout_s)
        except requests.RequestException:
            break

        content_type = (r.headers.get("content-type") or "").lower()
        data: Any = None
        if "application/json" in content_type:
            try:
                data = r.json()
            except Exception:
                data = None

        if data is None:
            break

        items = _extract_items_from_json(data)
        if not items:
            break

        for obj in items:
            h = _hackathon_from_obj(obj)
            if h and h.url:
                out.append(h)

    dedup: Dict[str, Hackathon] = {h.url: h for h in out}
    return list(dedup.values())


# =============================================================================
#  Helpers
# =============================================================================

def _infer_status(text: str) -> str:
    t = (text or "").lower()
    if "days left" in t or "day left" in t or "hours left" in t:
        return "live"
    if "expired" in t or "ended" in t or "closed" in t:
        return "expired"
    if "posted" in t:
        return "recent"
    return "unknown"


def _infer_fee_type(text: str) -> str:
    t = (text or "").lower()
    if "free" in t and "fee" not in t:
        return "free"
    if "paid" in t or "entry fee" in t or "registration fee" in t:
        return "paid"
    return "unknown"


# =============================================================================
#  MAIN ENTRY POINT — tries methods in order of reliability
# =============================================================================

def fetch_open_hackathons(max_pages: Optional[int] = None, timeout_s: int = 30) -> List[Hackathon]:
    """
    Best-effort fetcher — tries multiple strategies in order:
    1. Unstop public API (most reliable, full data, no browser needed)
    2. Playwright rendered scraping (needs browser)
    3. HTML scraping of api.unstop.com (limited data)
    4. Old api.unstop.com JSON endpoint (legacy)
    """
    max_pages = _effective_max_pages(max_pages)

    # STRATEGY 1: Unstop public API (best — works everywhere, full data)
    logger.info("Trying Unstop public API...")
    try:
        result = _fetch_from_unstop_public_api(max_pages=max_pages, timeout_s=timeout_s)
        if result:
            return result
    except Exception as e:
        logger.warning("Unstop public API failed: %s — trying fallbacks", e)

    # STRATEGY 2: Playwright (needs browser installed)
    logger.info("Trying Playwright scraper...")
    try:
        rendered = _fetch_from_unstop_rendered(max_pages=max_pages, timeout_s=timeout_s)
        if rendered:
            return rendered
    except Exception as e:
        logger.warning("Playwright failed: %s — trying fallbacks", e)

    # STRATEGY 3: HTML scraping
    logger.info("Trying HTML scraping of api.unstop.com...")
    try:
        session = requests.Session()
        session.headers.update({"User-Agent": _UA})
        html_result = _fetch_from_api_site(session=session, timeout_s=timeout_s, max_pages=max_pages)
        if html_result:
            return html_result
    except Exception as e:
        logger.warning("HTML scraping failed: %s", e)

    # STRATEGY 4: Old API JSON
    logger.info("Trying old API JSON endpoint...")
    try:
        old_result = _fetch_from_old_api(max_pages=max_pages, timeout_s=timeout_s)
        if old_result:
            return old_result
    except Exception as e:
        logger.warning("Old API failed: %s", e)

    logger.error("ALL scraping strategies failed — returning empty list")
    return []