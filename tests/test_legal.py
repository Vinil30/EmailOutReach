from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from utils.legal import DOCUMENTS, clean_signature, document_hash, legal_status, require_signed, required_documents, signature_records


def test_each_role_signs_privacy_and_its_own_terms():
    assert required_documents("student") == ["privacy", "terms-student"]
    assert required_documents("campaigner") == ["privacy", "terms-campaigner"]
    assert required_documents(None) == ["privacy", "terms-student"]


def test_signature_must_be_a_real_name():
    assert clean_signature("  Ananya   Rao ") == "Ananya Rao"
    for bad in ("", "ab", "1234", None, "x" * 121):
        with pytest.raises(HTTPException):
            clean_signature(bad)


def test_unsigned_account_is_blocked_until_it_signs():
    user = {"role": "student"}
    assert not legal_status(user)["signed"]
    with pytest.raises(HTTPException) as error:
        require_signed(user)
    assert error.value.status_code == 403

    user["legal"] = signature_records("student", "Ananya Rao", datetime.now(timezone.utc))
    assert legal_status(user)["signed"]
    require_signed(user)


def test_switching_role_or_new_version_needs_a_new_signature():
    records = signature_records("student", "Ananya Rao", datetime.now(timezone.utc))
    assert not legal_status({"role": "campaigner", "legal": records})["signed"]

    stale = {doc_id: {**record, "version": "2000-01-01"} for doc_id, record in records.items()}
    status = legal_status({"role": "student", "legal": stale})
    assert not status["signed"] and all(doc["signed_at"] for doc in status["documents"])


def test_signature_records_fingerprint_the_signed_text():
    records = signature_records("campaigner", "Sam Seller", datetime.now(timezone.utc))
    assert set(records) == {"privacy", "terms-campaigner"}
    assert records["privacy"]["sha256"] == document_hash("privacy")
    assert all(len(record["sha256"]) == 64 for record in records.values())


def test_every_legal_page_mentions_limited_use_or_signing():
    with open(f"templates/{DOCUMENTS['privacy']['template']}", encoding="utf-8") as handle:
        assert "Limited Use" in handle.read()
    for doc_id in ("terms-student", "terms-campaigner"):
        with open(f"templates/{DOCUMENTS[doc_id]['template']}", encoding="utf-8") as handle:
            assert "Electronic signature" in handle.read()
