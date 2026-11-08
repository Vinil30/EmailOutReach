"""Finds recruiter contacts for a user from live web search, cheapest steps first.

Order of work for one job (credits reserved up front, charged per contact delivered, the rest refunded):
1. Contacts already in the shared recruiter database that match the user's search tags (cheap: database price).
2. Search results already cached by any user in the last 7 days (no search cost).
3. New searches through Serper (Google results, cheapest per query), only up to the job's budget.
4. Email addresses taken only from what pages actually publish: the search snippet first, then the page itself.
5. Every address is checked (bad-address list, domain accepts mail, optional mailbox verification) before it
   is delivered, and each new contact is added to the shared database so the next user gets it cheaply.

Nothing is ever guessed: an address must appear on a public page."""
import hashlib
import ipaddress
import os
import re
import socket
import threading
from typing import Any
from urllib.parse import urlparse

import requests

from database.fxns import _now, add_bad_address, is_bad_address, leads
from database.marketplace import (
    MarketplaceError,
    add_owned,
    cached_search,
    create_job,
    finish_job,
    owns_or_emailed,
    record_delivery,
    store_search,
    take_database_contacts,
)
from utils.email_check import domain_accepts_mail, verification_enabled, verify_address

SERPER_URL = "https://google.serper.dev/search"
MAX_TARGET = 200
MAX_TAGS = 10
SEARCHES_PER_CONTACT = 3          # search budget: at most this many searches per contact asked for
PAGES_PER_CONTACT = 4             # page-fetch budget per contact asked for
MAX_SEARCHES = 300
PAGE_BYTES = 1_500_000
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}")
OBFUSCATED = [(re.compile(r"\s*[\[(]\s*at\s*[\])]\s*", re.I), "@"), (re.compile(r"\s*[\[(]\s*dot\s*[\])]\s*", re.I), ".")]
SKIP_LOCAL = {"noreply", "no-reply", "donotreply", "do-not-reply", "mailer-daemon", "postmaster", "webmaster", "privacy",
              "abuse", "legal", "press", "media", "sales", "billing", "unsubscribe", "info-noreply", "support", "help",
              "admin", "root", "security", "dmca", "copyright", "example", "test", "user", "username", "email", "name"}
SKIP_DOMAINS = {"example.com", "example.org", "domain.com", "email.com", "yourcompany.com", "company.com", "sentry.io",
                "wixpress.com", "sentry-next.wixpress.com", "godaddy.com", "w3.org"}
FREE_MAIL = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "rediffmail.com", "icloud.com", "proton.me", "protonmail.com"}
QUERY_TEMPLATES = [
    '{tag} hiring "email" resume',
    '"{tag}" "we are hiring" "send your resume"',
    '{tag} internship OR fresher "careers@" OR "hr@" OR "jobs@"',
]

_running: dict[str, threading.Thread] = {}


def search_enabled() -> bool:
    return bool(os.environ.get("SERPER_API_KEY"))


# ---------- Tags ----------

def suggest_tags(profile: dict[str, Any]) -> list[str]:
    """Starting search tags from the user's own profile; they can edit, remove and add their own."""
    tags: list[str] = []
    goal = (profile.get("goal") or "").strip()
    headline = (profile.get("headline") or "").strip()
    skills = [skill.strip() for skill in (profile.get("skills") or "").split(",") if skill.strip()]
    for text in (goal, headline):
        if text:
            tags.append(text[:60])
    level = "internship" if "intern" in f"{goal} {headline}".lower() else "fresher"
    for skill in skills[:4]:
        tags.append(f"{skill} {level}")
    seen, unique = set(), []
    for tag in tags:
        key = tag.lower()
        if key not in seen:
            seen.add(key)
            unique.append(tag)
    return unique[:6]


def clean_tags(tags: list[str]) -> list[str]:
    cleaned, seen = [], set()
    for tag in tags or []:
        text = " ".join(str(tag).replace('"', " ").split())[:60]
        if len(text) >= 2 and text.lower() not in seen:
            seen.add(text.lower())
            cleaned.append(text)
    return cleaned[:MAX_TAGS]


# ---------- Search & pages ----------

def _search(query: str, stats: dict[str, int]) -> list[dict[str, Any]]:
    key = hashlib.sha1(f"in|{query.lower()}".encode()).hexdigest()
    cached = cached_search(key)
    if cached is not None:
        stats["cached_searches"] += 1
        return cached
    response = requests.post(SERPER_URL, json={"q": query, "gl": "in", "num": 10},
                             headers={"X-API-KEY": os.environ.get("SERPER_API_KEY", "")}, timeout=20)
    stats["searches"] += 1
    if response.status_code in (401, 403):
        raise MarketplaceError("The web search key was rejected. The admin needs to check SERPER_API_KEY.", 503)
    if not response.ok:
        return []
    results = [{"title": item.get("title", ""), "link": item.get("link", ""), "snippet": item.get("snippet", "")}
               for item in (response.json().get("organic") or [])]
    store_search(key, query, results)
    return results


def _public_host(host: str) -> bool:
    """Never fetch internal addresses (SSRF): every IP the host resolves to must be public."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved or address.is_multicast:
            return False
    return True


def fetch_page_text(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or not _public_host(parsed.hostname):
        return ""
    try:
        with requests.get(url, timeout=8, stream=True, allow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0 (compatible; MailzenContactFinder/1.0)"}) as response:
            final = urlparse(response.url)
            if not response.ok or not final.hostname or not _public_host(final.hostname):
                return ""
            if "text" not in response.headers.get("Content-Type", "text/html"):
                return ""
            body = b""
            for chunk in response.iter_content(65536):
                body += chunk
                if len(body) > PAGE_BYTES:
                    break
    except requests.RequestException:
        return ""
    text = body.decode(response.encoding or "utf-8", errors="ignore")
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
    return re.sub(r"<[^>]+>", " ", text)


def emails_in(text: str) -> list[str]:
    for pattern, replacement in OBFUSCATED:
        text = pattern.sub(replacement, text or "")
    found = []
    for match in EMAIL_RE.findall(text):
        email = match.strip(".").lower()
        local, _, domain = email.partition("@")
        if local in SKIP_LOCAL or domain in SKIP_DOMAINS or domain.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")):
            continue
        if email not in found:
            found.append(email)
    return found


def _company_for(email: str, title: str) -> str:
    domain = email.split("@", 1)[1]
    if domain not in FREE_MAIL:
        return domain.split(".")[0].replace("-", " ").title()
    return re.split(r"\s[|\-–—:]\s", title or "")[0].strip()[:80]


def _name_for(email: str) -> str:
    local = email.split("@", 1)[0]
    parts = re.split(r"[._]", local)
    if len(parts) == 2 and all(part.isalpha() and len(part) > 1 for part in parts):
        return " ".join(part.title() for part in parts)
    return ""


# ---------- The job ----------

def start_job(user: dict[str, Any], tags: list[str], target: int, prices: dict[str, int]) -> dict[str, Any]:
    tags = clean_tags(tags)
    if not tags:
        raise MarketplaceError("Add at least one search tag.")
    if not 1 <= int(target) <= MAX_TARGET:
        raise MarketplaceError(f"Ask for between 1 and {MAX_TARGET} contacts at a time.")
    target = int(target)
    # Reserve as if every contact were a fresh web find; cheaper database matches are refunded the difference.
    reserved = target * prices["web"]
    job = create_job(str(user["_id"]), "web", target, reserved, {"tags": tags, "prices": dict(prices)})
    thread = threading.Thread(target=_run, args=(job, prices), name=f"finder-{job['_id']}", daemon=True)
    _running[str(job["_id"])] = thread
    thread.start()
    return job


def _run(job: dict[str, Any], prices: dict[str, int]) -> None:
    user_id, job_id, target, tags = job["user_id"], job["_id"], job["target"], job["tags"]
    stats = {"searches": 0, "cached_searches": 0, "pages": 0, "verifications": 0, "checked": 0}
    delivered = 0
    try:
        # 1. Cheapest: matching recruiters already in the shared database.
        from_db = take_database_contacts(user_id, str(job_id), target, prices["database"], keywords=tags)
        for _ in range(from_db):
            record_delivery(job_id, prices["database"], "database")
        delivered += from_db

        if delivered < target and not search_enabled():
            finish_job(job_id, "partial" if delivered else "failed",
                       "Web search isn't set up yet, so only database matches were delivered. Unused credits were returned.", stats)
            return

        # 2-4. Searches (cache first), snippets before pages, all within the budget.
        search_budget = min(MAX_SEARCHES, (target - delivered) * SEARCHES_PER_CONTACT)
        page_budget = (target - delivered) * PAGES_PER_CONTACT
        queries = [template.format(tag=tag) for template in QUERY_TEMPLATES for tag in tags]
        for query in queries:
            if delivered >= target or stats["searches"] >= search_budget:
                break
            for result in _search(query, stats):
                if delivered >= target:
                    break
                candidates = emails_in(f"{result['title']} {result['snippet']}")
                if not candidates and stats["pages"] < page_budget and result.get("link"):
                    stats["pages"] += 1
                    candidates = emails_in(fetch_page_text(result["link"]))
                for email in candidates:
                    if delivered >= target:
                        break
                    outcome = _deliver(user_id, str(job_id), email, result, query, prices, stats)
                    if outcome:
                        record_delivery(job_id, *outcome)
                        delivered += 1

        if delivered >= target:
            finish_job(job_id, "completed", f"Found all {target} contacts.", stats)
        elif delivered:
            finish_job(job_id, "partial", f"Found {delivered} of {target} contacts within the search budget. Unused credits were returned.", stats)
        else:
            finish_job(job_id, "failed", "No new contacts found for these tags. Try broader or different tags; your credits were returned.", stats)
    except MarketplaceError as exc:
        finish_job(job_id, "failed", f"{exc} Unused credits were returned.", stats)
    except Exception as exc:  # never keep credits for a job that crashed
        finish_job(job_id, "failed", f"Search stopped: {str(exc)[:160]}. Unused credits were returned.", stats)
    finally:
        _running.pop(str(job_id), None)


def _deliver(user_id: str, job_id: str, email: str, result: dict[str, Any], query: str, prices: dict[str, int],
             stats: dict[str, int]) -> tuple[int, str] | None:
    """Check one found address and give it to the user. Returns (credits it cost, source), or None if skipped."""
    stats["checked"] += 1
    if owns_or_emailed(user_id, email) or is_bad_address(email):
        return None
    existing = leads.find_one({"email": email})
    if existing and not existing.get("active", True):
        return None  # switched off by the admin or after a bounce
    if not existing:
        if domain_accepts_mail(email) is False:
            return None
        if verification_enabled():
            stats["verifications"] += 1
            deliverable, provider_status = verify_address(email)
            if deliverable is False:
                add_bad_address(email, f"Mailbox check: {provider_status}", "verification")
                return None
    tag = query.split('"')[1] if '"' in query else query.split(" hiring")[0]
    lead = existing or {
        "email": email, "name": _name_for(email), "company": _company_for(email, result.get("title", "")),
        "role": tag[:80], "details": f"{result.get('title', '')}. {result.get('snippet', '')}"[:400], "tags": [tag[:60]],
        "source": "web", "source_url": result.get("link", ""), "active": True,
    }
    if not existing:
        lead["created_at"] = _now()
        upserted = leads.update_one({"email": email}, {"$setOnInsert": lead}, upsert=True)
        if not upserted.upserted_id:
            lead = leads.find_one({"email": email}) or lead
        else:
            lead["_id"] = upserted.upserted_id
    source = "database" if existing else "web"
    price = prices["database"] if existing else prices["web"]
    return (price, source) if add_owned(user_id, job_id, lead, source, price) else None
