from datetime import datetime, timedelta, timezone

from database.fxns import is_premium
from utils.job_templates import TEMPLATES, brief_for_profile, get_template, pick_project, profile_variables
from utils.pacing import random_send_gap
from utils.plans import week_start
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


def test_premium_expires():
    now = datetime.now(timezone.utc)
    assert is_premium({"premium_until": now + timedelta(days=3)})
    assert not is_premium({"premium_until": now - timedelta(seconds=1)})
    assert not is_premium({})
    # Mongo returns naive UTC datetimes.
    assert is_premium({"premium_until": (now + timedelta(days=1)).replace(tzinfo=None)})


def test_lines_with_empty_fields_are_dropped():
    body = "Hi {{first_name|there}},\n\nResume: {{resume_link}}\nPortfolio: {{portfolio_url}}\n\nThanks"
    rendered = render_template(body, {"resume_link": "https://r.example"}, drop_empty_lines=True)
    assert "Portfolio" not in rendered
    assert "Resume: https://r.example" in rendered
    assert rendered.startswith("Hi there,")
    # Without the flag, the unfilled field stays visible so the spam guard can flag it.
    assert "{{portfolio_url}}" in render_template(body, {}, drop_empty_lines=False)


def test_project_matching_prefers_overlap():
    assert pick_project(CATALOG, "Zipline drone delivery uses computer vision")[0] == "InfSec"
    assert pick_project(CATALOG, "Razorpay payments")[0] == "CostIQ"
    assert pick_project({}, "anything") == ("", "")


def test_every_builtin_template_renders_clean():
    variables = {**profile_variables(PROFILE, CATALOG, "payments"), "first_name": "Priya", "company": "Razorpay"}
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
    assert brief_for_profile({"template_id": "ai"})["writing_mode"] == "ai"
    custom = brief_for_profile({"template_id": "custom", "custom_subject": "S", "custom_body": "B"})
    assert custom["subject_template"] == "S" and custom["drop_empty_lines"]
    assert brief_for_profile({})["subject_template"] == get_template("short")["subject"]


def test_random_gap_between_one_and_three_minutes():
    gaps = [random_send_gap() for _ in range(200)]
    assert min(gaps) >= 60 and max(gaps) <= 180


def test_preflight_lists_missing_setup():
    problems = preflight({"profile": {}, "gmail_tokens": {}})
    assert problems[0].startswith("Premium")
    assert any("Gmail" in problem for problem in problems)
    assert any("resume" in problem for problem in problems)
    ready = {
        "premium_until": datetime.now(timezone.utc) + timedelta(days=5),
        "gmail_tokens": {"refresh_token": "x"},
        "profile": PROFILE,
    }
    assert preflight(ready) == []
