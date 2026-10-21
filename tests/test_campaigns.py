from io import StringIO

import pandas as pd
import pytest
from fastapi import HTTPException

from Graph import EmailDetails, compliance_footer, email_writer, pre_send_risk_analyzer, project_selector
from utils.contacts import normalize_contacts
from utils.spam_guard import analyze_email_risk
from utils.templating import merge_fields, render_template, with_compliance_footer

CLEAN_BODY = (
    "<p>Hi Priya,</p><p>I read your team's write-up on cutting pick times at the Pune warehouse and the "
    "batching approach stood out, especially how late orders were handled without slowing the morning wave.</p>"
    "<p>I built a small routing simulator that tests batching rules against real order logs and reduced walking "
    "distance by about eighteen percent on a public dataset. Happy to share it if useful.</p>"
    "<p>Would a short chat in the next couple of weeks work for you?</p><p>Thanks,<br>Aarav</p>"
)


def test_campaign_requires_opt_out_line():
    outreach = analyze_email_risk("Routing idea for your team", CLEAN_BODY)
    campaign = analyze_email_risk("Routing idea for your team", CLEAN_BODY, campaign_type="campaign")
    assert "missing opt-out line" not in outreach.reasons
    assert "missing opt-out line" in campaign.reasons

    footer_body = with_compliance_footer(CLEAN_BODY, {"organization": "Brightloop", "physical_address": "12 MG Road"})
    with_footer = analyze_email_risk("Routing idea for your team", footer_body, campaign_type="campaign")
    assert "missing opt-out line" not in with_footer.reasons
    assert with_footer.action == "SEND"


def test_unfilled_placeholders_and_fake_reply_prefix_are_flagged():
    risk = analyze_email_risk("RE: following up", CLEAN_BODY.replace("Aarav", "[Your Name]") + "{{company}}")
    assert "unfilled placeholders" in risk.reasons
    assert "subject line issues" in risk.reasons
    assert risk.suggestions


def test_high_level_for_extreme_scores_and_checks_listed():
    risk = analyze_email_risk(
        "URGENT FREE OFFER!!!",
        "<p>ACT NOW!!! CLICK HERE. Guaranteed winner. Book a call. Sign up. Reach out. https://bit.ly/x https://1.2.3.4/a https://e.com</p>",
    )
    assert risk.level == "HIGH"
    assert risk.action == "REGENERATE"
    failed = {check["key"] for check in risk.checks if not check["passed"]}
    assert set(risk.reasons) == failed


def test_render_template_fills_fields_fallbacks_and_paragraphs():
    variables = {"first_name": "Mei", "company": "Harbor <Analytics>"}
    body = render_template("Hi {{ first_name }},\n\nLove what {{company}} does. {{city|Your city}} too.", variables, html=True)
    assert body == "<p>Hi Mei,</p><p>Love what Harbor &lt;Analytics&gt; does. Your city too.</p>"
    assert render_template("Hello {{missing}}", {}) == "Hello {{missing}}"
    assert merge_fields("{{a}} {{ B|x }}") == ["a", "b"]


def test_compliance_footer_is_idempotent():
    once = with_compliance_footer("<p>Hi</p>", {"unsubscribe_text": "Reply STOP to opt out."})
    assert "Reply STOP to opt out." in once
    assert with_compliance_footer(once, {}) == once


def test_normalize_contacts_aliases_dedupes_and_suppresses():
    frame = pd.read_csv(
        StringIO(
            "Email,First Name,Company,Role\n"
            "a@example.com,Ann,Acme,CTO\n"
            "A@example.com,Ann,Acme,CTO\n"
            "bad-address,Bob,Beta,CEO\n"
            "c@example.com,Cy,Gamma,VP\n"
        ),
        dtype=str,
    )
    result = normalize_contacts(frame, {"c@example.com"})
    assert [contact["recipient_email"] for contact in result["contacts"]] == ["a@example.com"]
    contact = result["contacts"][0]
    assert contact["company_name"] == "Acme"
    assert contact["variables"]["first_name"] == "Ann"
    assert contact["variables"]["role"] == "CTO"
    assert {item["reason"] for item in result["skipped"]} == {
        "duplicate in this list",
        "invalid email address",
        "on your suppression list",
    }


def test_normalize_contacts_requires_email_column():
    with pytest.raises(HTTPException):
        normalize_contacts(pd.DataFrame({"name": ["x"]}))


def test_template_campaign_pipeline_skips_ai_and_holds_risky_mail():
    state = {
        "role": "campaigner",
        "brief": {"writing_mode": "template", "subject_template": "FREE {{company}} OFFER!!!", "body_template": "Act now!!! Click here {{missing}}"},
        "variables": {"company": "Acme"},
        "profile": {"organization": "Brightloop"},
        "email_from": "me@example.com",
        "recipient_email": "you@example.com",
    }
    state = project_selector(state)
    state = email_writer(state)
    state = compliance_footer(state)
    state = pre_send_risk_analyzer(state)
    assert state["written_email_details"].email_subject == "FREE Acme OFFER!!!"
    assert "data-compliance-footer" in state["written_email_details"].email_body
    assert state["outreach_status"] == "REGENERATE"
    assert len(state["deliverability_history"]) == 1


def test_student_with_few_projects_uses_all_without_llm():
    state = project_selector({"role": "student", "project_catalog": {"A": "one", "B": "two"}})
    assert state["projects"] == ["A", "B"]


def test_campaigner_rewrite_keeps_footer(monkeypatch):
    class FakeWriter:
        def RewriteForDeliverability(self, *args):
            return EmailDetails(email_subject="Calm subject", email_body=CLEAN_BODY)

    monkeypatch.setattr("utils.EmailWriter.EmailWriter", FakeWriter)
    state = {
        "role": "campaigner",
        "brief": {"writing_mode": "ai"},
        "profile": {"organization": "Brightloop"},
        "written_email_details": EmailDetails(email_subject="URGENT FREE OFFER!!!", email_body="<p>CLICK HERE now!!! Act now. https://bit.ly/x</p>"),
        "email_from": "me@example.com",
        "recipient_email": "you@example.com",
    }
    updated = pre_send_risk_analyzer(state)
    assert "data-compliance-footer" in updated["written_email_details"].email_body
    assert updated["deliverability_risk"]["action"] == "SEND"
    assert len(updated["deliverability_history"]) == 2


def test_stricter_checks_catch_phishing_tricks():
    phishing = analyze_email_risk(
        "Account check",
        CLEAN_BODY.replace("Hi Priya,", "Dear Sir/Madam,")
        + '<p>Please verify your account and share your bank details.</p><p><a href="https://evil.example">www.google.com</a></p>',
    )
    assert {"generic greeting", "requests for sensitive information", "misleading link text"} <= set(phishing.reasons)
    assert phishing.action == "REGENERATE"


def test_stricter_checks_catch_obfuscation_and_hidden_text():
    risk = analyze_email_risk(
        "Your fr33 internship!",
        CLEAN_BODY + '<p style="color:#ffffff">keywords</p><p>Get a F R E E review.</p>',
    )
    assert {"obfuscated words", "hidden or invisible text", "subject line issues"} <= set(risk.reasons)


def test_compliance_footer_and_polite_phrases_stay_clean():
    body = with_compliance_footer(CLEAN_BODY.replace("Happy to share it if useful.", "Feel free to ask for it."), {"organization": "Brightloop"})
    risk = analyze_email_risk("Routing idea for your team", body, campaign_type="campaign")
    assert risk.action == "SEND"
    assert "heavy formatting" not in risk.reasons
    assert "excessive promotional or urgent language" not in risk.reasons
    assert len(risk.checks) == 22
