"""Minimal Razorpay client: orders, signature checks and payment lookups (REST API, no SDK needed).

Set RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET and RAZORPAY_WEBHOOK_SECRET. Test-mode keys (rzp_test_...) work the
same way and take fake payments."""
import hashlib
import hmac
import os
from typing import Any

import requests

API = "https://api.razorpay.com/v1"


class PaymentsNotConfigured(Exception):
    pass


class PaymentError(Exception):
    pass


def key_id() -> str:
    return os.environ.get("RAZORPAY_KEY_ID", "")


def _secret() -> str:
    return os.environ.get("RAZORPAY_KEY_SECRET", "")


def enabled() -> bool:
    return bool(key_id() and _secret())


def _call(method: str, path: str, **kwargs) -> dict[str, Any]:
    if not enabled():
        raise PaymentsNotConfigured("Payments aren't set up yet. Please try again later.")
    try:
        response = requests.request(method, f"{API}{path}", auth=(key_id(), _secret()), timeout=20, **kwargs)
    except requests.RequestException as exc:
        raise PaymentError("Couldn't reach the payment provider. Please try again.") from exc
    data = response.json() if response.content else {}
    if not response.ok:
        raise PaymentError((data.get("error") or {}).get("description") or "The payment provider refused the request.")
    return data


def create_order(amount_paise: int, receipt: str, notes: dict[str, str]) -> dict[str, Any]:
    return _call("POST", "/orders", json={"amount": int(amount_paise), "currency": "INR", "receipt": receipt[:40], "notes": notes})


def fetch_payment(payment_id: str) -> dict[str, Any]:
    return _call("GET", f"/payments/{payment_id}")


def capture_payment(payment_id: str, amount_paise: int) -> dict[str, Any]:
    return _call("POST", f"/payments/{payment_id}/capture", json={"amount": int(amount_paise), "currency": "INR"})


def checkout_signature_valid(order_id: str, payment_id: str, signature: str) -> bool:
    """The signature Razorpay Checkout returns: HMAC-SHA256 of "order_id|payment_id" with the key secret."""
    if not _secret() or not signature:
        return False
    expected = hmac.new(_secret().encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def webhook_signature_valid(raw_body: bytes, signature: str) -> bool:
    secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
