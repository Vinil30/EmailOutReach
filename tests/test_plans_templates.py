from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from database.fxns import is_paid, is_premium, plan_of
from utils.job_templates import TEMPLATES, brief_for_profile, featured_project, get_template, profile_variables
from utils.pacing import random_send_gap
from utils import plans
from utils.legal import signature_records
from utils.plans import day_start, limit_message, require_ai, week_start
from utils.premium_runner import preflight
from utils.spam_guard import analyze_email_risk
from utils.templating import render_template

PROFILE = {
    "full_name": "Sam Student",
    "headline": "ML engineer building agentic systems",
    "school": "IIIT Kota",
    "skills": "Python, LangGraph, FastAPI",
    "goal": "Summer 2027 ML internship",
    "resume_url": "https://drive.google.com/file/d/abc/view",
    "signature": "Best,\nSam",
}
CATALOG = {
    "InfSec": "Real-time YOLO safety monitor with pose estimation for computer vision.",
    "CostIQ": "Multi-agent cost anomaly detection for ecommerce payments data.",
}


def test_week_starts_monday_midnight_utc():
    wednesday = datetime(2026, 10, 21, 15, 30, tzinfo=timezone.utc)
    assert week_start(wednesday) == datetime(2026, 10, 19, tzinfo=timezone.utc)


def test_plans_expire_back_to_free():
    now = datetime.now(timezone.utc)
    assert plan_of({"plan": "pro", "plan_until": now + timedelta(days=3)}) == "pro"
    assert plan_of({"plan": "premium", "plan_until": now + timedelta(days=3)}) == "premium"
    assert plan_of({"plan": "premium", "plan_until": now - timedelta(seconds=1)}) == "free"
    assert plan_of({}) == "free"
    assert is_paid({"plan": "pro", "plan_until": now + timedelta(days=1)})
    assert not is_premium({"plan": "pro", "plan_until": now + timedelta(days=1)})
    # Mongo returns naive UTC datetimes.
    assert is_premium({"plan": "premium", "plan_until": (now + timedelta(days=1)).replace(tzinfo=None)})


def test_sending_day_rolls_over_at_midnight_india_time():
    # 20:00 UTC is 01:30 the next day in India.
    assert day_start(datetime(2026, 10, 24, 20, 0, tzinfo=timezone.utc)) == datetime(2026, 10, 24, 18, 30, tzinfo=timezone.utc)
    assert day_start(datetime(2026, 10, 24, 10, 0, tzinfo=timezone.utc)) == datetime(2026, 10, 23, 18, 30, tzinfo=timezone.utc)


def test_limit_messages_explain_the_daily_cap():
    assert "Upgrade" in limit_message({"plan": "free", "limit": 20})
    message = limit_message({"plan": "pro", "limit": 100})
    assert "100" in message and "Google" in message


def test_each_purchase_gets_a_fresh_database_allowance(monkeypatch):
    prices = {"pro": {"contacts": 200}, "premium": {"contacts": 500}}
    until = datetime.now(timezone.utc) + timedelta(days=10)
    monkeypatch.setattr(plans, "database_sent", lambda user_id: 260)
    # Bought Pro again after 200 database emails: the earlier sends don't count against this purchase.
    renewed = {"_id": "u1", "plan": "pro", "plan_until": until, "db_base": 200}
    assert plans.database_allowance(renewed, prices) == {"limit": 200, "used": 60, "remaining": 140}
    upgraded = {"_id": "u1", "plan": "premium", "plan_until": until, "db_base": 260}
    assert plans.database_allowance(upgraded, prices) == {"limit": 500, "used": 0, "remaining": 500}
    assert plans.database_allowance({"_id": "u1"}, prices)["remaining"] == 0


def test_lines_with_empty_fields_are_dropped():
    body = "Hi {{first_name|there}},\n\nResume: {{resume_link}}\nPortfolio: {{portfolio_url}}\n\nThanks"
    rendered = render_template(body, {"resume_link": "https://r.example"}, drop_empty_lines=True)
    assert "Portfolio" not in rendered
    assert "Resume: https://r.example" in rendered
    assert rendered.startswith("Hi there,")
    # Without the flag, the unfilled field stays visible so the spam guard can flag it.
    assert "{{portfolio_url}}" in render_template(body, {}, drop_empty_lines=False)


def test_templates_use_one_fixed_featured_project():
    assert featured_project(CATALOG, {})[0] == "InfSec"
    assert featured_project(CATALOG, {"featured_project": "CostIQ"})[0] == "CostIQ"
    assert featured_project(CATALOG, {"featured_project": "Deleted"})[0] == "InfSec"
    assert featured_project({}, {}) == ("", "")


def test_every_builtin_template_renders_clean():
    variables = {**profile_variables(PROFILE, CATALOG), "first_name": "Priya", "company": "Razorpay"}
    for template in TEMPLATES:
        if template.get("ai") or template.get("custom"):
            continue
        subject = render_template(template["subject"], variables, drop_empty_lines=True)
        body = render_template(template["body"], variables, html=True, drop_empty_lines=True)
        risk = analyze_email_risk(subject, body)
        assert "{{" not in subject + body, template["id"]
        assert risk.action == "SEND", (template["id"], risk.reasons)
        assert PROFILE["resume_url"] in body


def test_brief_for_profile_modes():
    assert brief_for_profile({"template_id": "ai"}, ai_allowed=True)["writing_mode"] == "ai"
    custom = brief_for_profile({"template_id": "custom", "custom_subject": "S", "custom_body": "B"}, ai_allowed=False)
    assert custom["subject_template"] == "S" and custom["drop_empty_lines"]
    assert brief_for_profile({}, ai_allowed=False)["subject_template"] == get_template("short")["subject"]


def test_ai_is_premium_only():
    # Without Premium an AI choice silently falls back to the default template.
    fallback = brief_for_profile({"template_id": "ai"}, ai_allowed=False)
    assert fallback["writing_mode"] == "template"
    with pytest.raises(HTTPException) as error:
        require_ai({})
    assert error.value.status_code == 402
    soon = datetime.now(timezone.utc) + timedelta(days=1)
    with pytest.raises(HTTPException):
        require_ai({"plan": "pro", "plan_until": soon})
    require_ai({"plan": "premium", "plan_until": soon})


def test_random_gap_between_one_and_three_minutes():
    gaps = [random_send_gap() for _ in range(200)]
    assert min(gaps) >= 60 and max(gaps) <= 180


def test_preflight_lists_missing_setup():
    problems = preflight({"profile": {}, "gmail_tokens": {}})
    assert problems[0].startswith("Upgrade to Pro or Premium")
    assert any("Gmail" in problem for problem in problems)
    assert any("resume" in problem for problem in problems)
    ready = {
        "plan": "pro",
        "plan_until": datetime.now(timezone.utc) + timedelta(days=5),
        "gmail_tokens": {"refresh_token": "x"},
        "profile": PROFILE,
        "legal": signature_records("student", "Sam Student", datetime.now(timezone.utc)),
    }
    assert preflight(ready) == []
    assert any("Sign the Terms" in problem for problem in preflight({**ready, "legal": {}}))
