from dataclasses import dataclass
from unittest.mock import Mock

import pytest
from bson import ObjectId
from fastapi import HTTPException

import database.fxns as db_fxns
from Graph import EmailDetails, pre_send_risk_analyzer
from utils.DeliverabilityAnalyzer import RspamdAnalyzer
from utils.EmailerAgent import EmailerAgent


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.ok = 200 <= status_code < 300

    def json(self):
        return self._payload

    def raise_for_status(self):
        if not self.ok:
            raise Exception(f"HTTP {self.status_code}")


def test_low_risk_email_analyzes_and_sends(monkeypatch):
    monkeypatch.setattr(
        "utils.DeliverabilityAnalyzer.requests.post",
        lambda *args, **kwargs: FakeResponse(payload={"score": 2.1, "symbols": {}}),
    )
    risk = RspamdAnalyzer().analyze("Hello", "<p>Hi</p>", "me@example.com", "you@example.com")
    assert risk.level == "LOW"
    assert risk.action == "SEND"

    monkeypatch.setattr(
        "utils.EmailerAgent.requests.post",
        lambda *args, **kwargs: FakeResponse(payload={"id": "gmail-message-id"}),
    )
    result = EmailerAgent(
        EmailDetails(email_subject="Hello", email_body="<p>Hi</p>"),
        "you@example.com",
        "me@example.com",
        {"access_token": "token"},
    ).send_with_retries(base_delay_seconds=0)
    assert result["status"] == "SENT"
    assert result["response"]["id"] == "gmail-message-id"


def test_medium_risk_email_rewrites_and_rechecks(monkeypatch):
    calls = []

    class FakeAnalyzer:
        def analyze(self, *args):
            calls.append(args)
            if len(calls) == 1:
                return Mock(level="MEDIUM", action="REWRITE_REQUIRED", reasons=["excessive promotional language"], model_dump=lambda: {"level": "MEDIUM", "action": "REWRITE_REQUIRED", "reasons": ["excessive promotional language"]})
            return Mock(level="LOW", action="SEND", reasons=[], model_dump=lambda: {"level": "LOW", "action": "SEND", "reasons": [], "score": 1.0})

    class FakeWriter:
        def RewriteForDeliverability(self, *args):
            return EmailDetails(email_subject="Rewritten", email_body="<p>Calmer email.</p>")

    monkeypatch.setattr("utils.DeliverabilityAnalyzer.RspamdAnalyzer", FakeAnalyzer)
    monkeypatch.setattr("utils.EmailWriter.EmailWriter", FakeWriter)
    state = {
        "written_email_details": EmailDetails(email_subject="Buy now", email_body="<p>Huge opportunity!!!</p>"),
        "email_from": "me@example.com",
        "recipient_email": "you@example.com",
    }
    updated = pre_send_risk_analyzer(state)
    assert updated["written_email_details"].email_subject == "Rewritten"
    assert updated["deliverability_risk"]["level"] == "LOW"
    assert len(updated["deliverability_history"]) == 2


def test_high_risk_email_blocks_for_review(monkeypatch):
    class FakeAnalyzer:
        def analyze(self, *args):
            return Mock(level="HIGH", action="BLOCK_REVIEW", reasons=["suspicious URL"], model_dump=lambda: {"level": "HIGH", "action": "BLOCK_REVIEW", "reasons": ["suspicious URL"], "score": 7.4})

    monkeypatch.setattr("utils.DeliverabilityAnalyzer.RspamdAnalyzer", FakeAnalyzer)
    state = {
        "written_email_details": EmailDetails(email_subject="Hello", email_body="<p>Click</p>"),
        "email_from": "me@example.com",
        "recipient_email": "you@example.com",
    }
    updated = pre_send_risk_analyzer(state)
    assert updated["outreach_status"] == "BLOCK_REVIEW"
    assert updated["deliverability_risk"]["score"] == 7.4


def test_rspamd_unavailable_raises_service_unavailable(monkeypatch):
    monkeypatch.setattr(
        "utils.DeliverabilityAnalyzer.requests.post",
        Mock(side_effect=__import__("requests").RequestException("offline")),
    )
    with pytest.raises(HTTPException) as exc:
        RspamdAnalyzer().analyze("Hello", "<p>Hi</p>", "me@example.com", "you@example.com")
    assert exc.value.status_code == 503


def test_gmail_429_retries(monkeypatch):
    responses = [FakeResponse(429), FakeResponse(200, {"id": "ok"})]
    monkeypatch.setattr("utils.EmailerAgent.requests.post", lambda *args, **kwargs: responses.pop(0))
    result = EmailerAgent(
        EmailDetails(email_subject="Hello", email_body="<p>Hi</p>"),
        "you@example.com",
        "me@example.com",
        {"access_token": "token"},
    ).send_with_retries(base_delay_seconds=0)
    assert result["status"] == "SENT"
    assert result["attempt"] == 2
    assert result["history"][0]["reason"] == "Gmail rate limit"


def test_gmail_5xx_retries(monkeypatch):
    responses = [FakeResponse(503), FakeResponse(200, {"id": "ok"})]
    monkeypatch.setattr("utils.EmailerAgent.requests.post", lambda *args, **kwargs: responses.pop(0))
    result = EmailerAgent(
        EmailDetails(email_subject="Hello", email_body="<p>Hi</p>"),
        "you@example.com",
        "me@example.com",
        {"access_token": "token"},
    ).send_with_retries(base_delay_seconds=0)
    assert result["status"] == "SENT"
    assert result["history"][0]["reason"] == "Gmail server error"


def test_permanent_failure_does_not_retry(monkeypatch):
    post = Mock(return_value=FakeResponse(400))
    monkeypatch.setattr("utils.EmailerAgent.requests.post", post)
    result = EmailerAgent(
        EmailDetails(email_subject="Hello", email_body="<p>Hi</p>"),
        "bad-recipient",
        "me@example.com",
        {"access_token": "token"},
    ).send_with_retries(base_delay_seconds=0)
    assert result["status"] == "FAILED_PERMANENT"
    assert post.call_count == 1


def test_oauth_failure_is_permanent_without_llm_decision():
    result = EmailerAgent(
        EmailDetails(email_subject="Hello", email_body="<p>Hi</p>"),
        "you@example.com",
        "me@example.com",
        {},
    ).send_with_retries(base_delay_seconds=0)
    assert result["status"] == "FAILED_PERMANENT"
    assert result["reason"] == "Gmail authorization required"


@dataclass
class InsertResult:
    inserted_id: ObjectId


class FakeGeneratedCollection:
    def __init__(self, doc):
        self.doc = doc
        self.updated = None

    def find_one(self, query):
        if self.doc and self.doc["_id"] == query["_id"]:
            return dict(self.doc)
        return None

    def update_one(self, query, update):
        self.updated = update["$set"]

    def delete_one(self, query):
        self.doc = None


class FakeSentCollection:
    def __init__(self, duplicate=None):
        self.duplicate = duplicate

    def find_one(self, query):
        return self.duplicate

    def insert_one(self, doc):
        return InsertResult(ObjectId())


def test_duplicate_retry_protection(monkeypatch):
    mail_id = ObjectId()
    doc = {
        "_id": mail_id,
        "user_id": "user-1",
        "email_status": False,
        "recipient_email": "you@example.com",
        "written_email_details": {"email_subject": "Hello", "email_body": "<p>Hi</p>"},
    }
    fake_generated = FakeGeneratedCollection(doc)
    fake_sent = FakeSentCollection(duplicate={"_id": ObjectId(), "user_id": "user-1"})
    monkeypatch.setattr(db_fxns, "emailsGenerated", fake_generated)
    monkeypatch.setattr(db_fxns, "emailsSent", fake_sent)

    result = db_fxns.record_generated_send_result(str(mail_id), "user-1", {"status": "SENT"})
    assert result["outreach_status"] == "DUPLICATE_SUPPRESSED"
    assert fake_generated.updated["email_response"]["status"] == "DUPLICATE_SUPPRESSED"
