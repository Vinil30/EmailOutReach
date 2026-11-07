"""Checks that catch undeliverable addresses before Gmail sends to them.

- domain_accepts_mail: free DNS check that the domain exists and accepts email (catches typo and dead domains).
- verify_address: optional paid mailbox check through ZeroBounce (set EMAIL_VERIFY_API_KEY); this is the
  check that catches "Address not found" on a real domain, like careers@company.com that doesn't exist.
"""
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import dns.exception
import dns.resolver
import requests

DNS_TIMEOUT_SECONDS = float(os.environ.get("EMAIL_DNS_TIMEOUT_SECONDS", "5"))
DOMAIN_CACHE_SECONDS = 6 * 60 * 60
VERIFY_API_KEY = os.environ.get("EMAIL_VERIFY_API_KEY", "")
VERIFY_URL = "https://api.zerobounce.net/v2/validate"
# ZeroBounce statuses that mean "don't send"; "catch-all" and "unknown" can't be confirmed either way, so they pass.
UNDELIVERABLE = {"invalid", "spamtrap", "abuse", "do_not_mail"}

_domain_cache: dict[str, tuple[bool | None, float]] = {}
_cache_lock = threading.Lock()


def _resolver() -> dns.resolver.Resolver:
    resolver = dns.resolver.Resolver()
    # Total time per lookup; each nameserver gets a shorter slice so a dead one doesn't use it all up.
    resolver.lifetime = DNS_TIMEOUT_SECONDS
    resolver.timeout = min(1.5, DNS_TIMEOUT_SECONDS)
    return resolver


def _lookup(domain: str) -> bool | None:
    """True: accepts mail. False: definitely doesn't. None: couldn't tell (never blocks a send)."""
    resolver = _resolver()
    try:
        answers = resolver.resolve(domain, "MX")
        # A "null MX" (a single "." record) is the domain saying it accepts no email at all.
        return not all(str(record.exchange) in (".", "") for record in answers)
    except dns.resolver.NXDOMAIN:
        return False
    except dns.resolver.NoAnswer:
        pass
    except (dns.exception.Timeout, dns.resolver.NoNameservers, dns.exception.DNSException):
        return None
    # No MX record: mail falls back to the domain's own address record (RFC 5321).
    for record_type in ("A", "AAAA"):
        try:
            resolver.resolve(domain, record_type)
            return True
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
            continue
        except dns.exception.DNSException:
            return None
    return False


def domain_accepts_mail(address: str) -> bool | None:
    domain = (address or "").rsplit("@", 1)[-1].strip().lower().rstrip(".")
    if not domain or "." not in domain:
        return False
    now = time.monotonic()
    with _cache_lock:
        cached = _domain_cache.get(domain)
        if cached and cached[1] > now:
            return cached[0]
    result = _lookup(domain)
    # Unknown results are cached briefly so a DNS hiccup is retried soon.
    ttl = DOMAIN_CACHE_SECONDS if result is not None else 300
    with _cache_lock:
        _domain_cache[domain] = (result, now + ttl)
    return result


def dead_domains(addresses: list[str], workers: int = 16) -> set[str]:
    """Addresses (lower-cased) whose domain definitely can't receive email, checked in parallel."""
    domains = sorted({address.rsplit("@", 1)[-1].lower() for address in addresses if "@" in address})
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = dict(zip(domains, pool.map(lambda domain: domain_accepts_mail(f"x@{domain}"), domains)))
    return {address.lower() for address in addresses if results.get(address.rsplit("@", 1)[-1].lower()) is False}


def verification_enabled() -> bool:
    return bool(VERIFY_API_KEY)


def verify_address(address: str) -> tuple[bool | None, str]:
    """(deliverable?, provider status). None when the check isn't configured or the provider can't answer."""
    if not VERIFY_API_KEY:
        return None, "not_configured"
    try:
        response = requests.get(VERIFY_URL, params={"api_key": VERIFY_API_KEY, "email": address, "ip_address": ""}, timeout=20)
        data = response.json() if response.ok else {}
    except (requests.RequestException, ValueError):
        return None, "error"
    status = str(data.get("status") or "unknown").lower()
    if status in UNDELIVERABLE:
        return False, status
    return (True if status == "valid" else None), status
