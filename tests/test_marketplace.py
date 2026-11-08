import hashlib
import hmac

import pytest

from utils import contact_finder, razorpay_client
from utils.plans import pack_by_id


@pytest.fixture
def razorpay_keys(monkeypatch):
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_x")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "key-secret")
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "hook-secret")


def test_checkout_signature(razorpay_keys):
    good = hmac.new(b"key-secret", b"order_1|pay_1", hashlib.sha256).hexdigest()
    assert razorpay_client.checkout_signature_valid("order_1", "pay_1", good)
    assert not razorpay_client.checkout_signature_valid("order_2", "pay_1", good)  # signature is tied to the order
    assert not razorpay_client.checkout_signature_valid("order_1", "pay_1", "")
    assert not razorpay_client.checkout_signature_valid("order_1", "pay_1", "0" * 64)


def test_webhook_signature(razorpay_keys):
    body = b'{"event":"payment.captured"}'
    good = hmac.new(b"hook-secret", body, hashlib.sha256).hexdigest()
    assert razorpay_client.webhook_signature_valid(body, good)
    assert not razorpay_client.webhook_signature_valid(body + b" ", good)  # any change to the body breaks it
    assert not razorpay_client.webhook_signature_valid(body, hmac.new(b"key-secret", body, hashlib.sha256).hexdigest())


def test_payments_off_without_keys(monkeypatch):
    for name in ("RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET", "RAZORPAY_WEBHOOK_SECRET"):
        monkeypatch.delenv(name, raising=False)
    assert not razorpay_client.enabled()
    assert not razorpay_client.checkout_signature_valid("o", "p", "anything")
    assert not razorpay_client.webhook_signature_valid(b"{}", "anything")
    with pytest.raises(razorpay_client.PaymentsNotConfigured):
        razorpay_client.create_order(100, "r", {})


def test_unknown_pack():
    assert pack_by_id("p1")["credits"] > 0
    assert pack_by_id("p9") is None
    assert pack_by_id("") is None


def test_emails_in_handles_obfuscation_and_junk():
    text = ("Mail jobs@acme.in or Priya.N [at] acme [dot] co, not noreply@acme.in, logo@2x.png, "
            "you@example.com or JOBS@acme.in.")
    assert contact_finder.emails_in(text) == ["jobs@acme.in", "priya.n@acme.co"]


def test_tags_from_profile_and_cleaning():
    tags = contact_finder.suggest_tags({"goal": "ML internship", "headline": "ML internship", "skills": "Python, SQL"})
    assert tags == ["ML internship", "Python internship", "SQL internship"]
    cleaned = contact_finder.clean_tags(['  Data  "analyst" ', "data analyst", "x", "y" * 100] + [f"t{i}" for i in range(20)])
    assert cleaned[0] == "Data analyst"
    assert len(cleaned[1]) == 60
    assert len(cleaned) == contact_finder.MAX_TAGS


def test_names_and_companies_from_found_addresses():
    assert contact_finder._name_for("anita.rao@acme.in") == "Anita Rao"
    assert contact_finder._name_for("careers@acme.in") == ""
    assert contact_finder._company_for("hr@bright-loop.io", "") == "Bright Loop"
    assert contact_finder._company_for("hiring.team@gmail.com", "Brightloop - Careers") == "Brightloop"


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "10.0.0.5", "169.254.169.254", "192.168.1.1", "[::1]", "0.0.0.0"])
def test_page_fetch_refuses_internal_addresses(host, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("must not fetch an internal address")
    monkeypatch.setattr(contact_finder.requests, "get", boom)
    assert contact_finder.fetch_page_text(f"http://{host}/admin") == ""


def test_page_fetch_only_http(monkeypatch):
    monkeypatch.setattr(contact_finder.requests, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    assert contact_finder.fetch_page_text("file:///etc/passwd") == ""
    assert contact_finder.fetch_page_text("ftp://example.org/x") == ""
