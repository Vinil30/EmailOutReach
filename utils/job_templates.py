"""Built-in email templates for job seekers, plus the profile-derived merge fields they use."""
import re
from typing import Any

# Each body line that references an empty field (without a fallback) is dropped when rendered,
# so optional details like a portfolio link simply disappear when the user hasn't set them.
TEMPLATES = [
    {
        "id": "short",
        "name": "Short & direct",
        "description": "Five lines. Who you are, one project, your resume, one ask.",
        "subject": "{{goal_short|Opportunities}} at {{company|your team}}",
        "body": (
            "Hi {{first_name|there}},\n\n"
            "{{my_intro}}\n"
            "I'm reaching out because I'd love to contribute to {{company|your team}}.\n\n"
            "{{project_line}}\n\n"
            "My resume: {{resume_link}}\n"
            "Portfolio: {{portfolio_url}}\n\n"
            "I'm looking for {{goal|internship or entry-level roles}}. Would you be open to a quick chat?\n\n"
            "Best regards,\n{{signature}}"
        ),
    },
    {
        "id": "project",
        "name": "Project spotlight",
        "description": "Leads with your most relevant project, then connects it to their work.",
        "subject": "{{project_name|A project}} that fits {{company|your team}}",
        "body": (
            "Hi {{first_name|there}},\n\n"
            "I recently built {{project_name}}: {{project_summary}}\n\n"
            "It's close to the problems {{company|your team}} works on, and I'd enjoy applying the same approach there.\n\n"
            "{{my_intro}}\n"
            "Skills I'd bring: {{my_skills}}\n"
            "Resume: {{resume_link}}\n\n"
            "I'm looking for {{goal|an internship or entry-level role}}. If there's a fit, could we talk for 15 minutes?\n\n"
            "Thanks for your time,\n{{signature}}"
        ),
    },
    {
        "id": "referral",
        "name": "Ask for a referral",
        "description": "Polite, low-pressure ask for a referral or the right person to talk to.",
        "subject": "Quick question about roles at {{company|your company}}",
        "body": (
            "Hi {{first_name|there}},\n\n"
            "{{my_intro}}\n"
            "I'm looking for {{goal|entry-level roles}}, and {{company|your company}} is at the top of my list.\n\n"
            "{{project_line}}\n\n"
            "If you think I could be a fit, would you be comfortable referring me or pointing me to the right person?\n"
            "My resume is here: {{resume_link}}\n\n"
            "Either way, thank you for reading.\n\n"
            "Best,\n{{signature}}"
        ),
    },
    {
        "id": "internship",
        "name": "Internship request",
        "description": "Warm and specific, for students looking for internships.",
        "subject": "Internship inquiry from {{my_name|a student}}",
        "body": (
            "Hi {{first_name|there}},\n\n"
            "{{my_intro}}\n"
            "I've been following {{company|your team}}'s work and would love to learn from your team as an intern.\n\n"
            "{{project_line}}\n\n"
            "I'm comfortable with {{my_skills}}, and I pick up new tools quickly.\n\n"
            "Resume: {{resume_link}}\n"
            "Work samples: {{portfolio_url}}\n\n"
            "Are there internship openings I could be considered for?\n\n"
            "Warm regards,\n{{signature}}"
        ),
    },
    {
        "id": "ai",
        "name": "AI-personalized",
        "description": "Premium. Researches each company, picks your best-matching project, and drafts a unique email.",
        "ai": True,
        "premium": True,
    },
    {
        "id": "custom",
        "name": "Write my own",
        "description": "Your own subject and body, with any of the merge fields below.",
        "custom": True,
    },
]

TEMPLATE_IDS = {template["id"] for template in TEMPLATES}
DEFAULT_TEMPLATE_ID = "short"

MERGE_FIELD_HELP = {
    "first_name": "Recipient's first name",
    "company": "Recipient's company",
    "role": "Recipient's role",
    "my_name": "Your name",
    "my_intro": "One-line intro built from your profile",
    "my_skills": "Your skills",
    "goal": "What you're looking for",
    "project_name": "Your featured project",
    "project_summary": "That project's description",
    "project_line": "A sentence about that project",
    "resume_link": "Your resume link",
    "portfolio_url": "Your portfolio link",
    "signature": "Your sign-off",
}


def get_template(template_id: str | None) -> dict[str, Any]:
    return next((t for t in TEMPLATES if t["id"] == template_id), next(t for t in TEMPLATES if t["id"] == DEFAULT_TEMPLATE_ID))


def brief_for_profile(profile: dict[str, Any], ai_allowed: bool) -> dict[str, Any]:
    """Turn the template chosen on a profile into a campaign brief the pipeline understands.

    AI writing costs money per email, so it's only honoured for Premium; anyone else gets the default template.
    """
    template = get_template(profile.get("template_id"))
    if template.get("ai") and not ai_allowed:
        template = get_template(DEFAULT_TEMPLATE_ID)
    if template.get("ai"):
        return {"writing_mode": "ai", "research": True, "goal": profile.get("goal", "")}
    if template.get("custom"):
        return {
            "writing_mode": "template",
            "drop_empty_lines": True,
            "subject_template": profile.get("custom_subject") or get_template(DEFAULT_TEMPLATE_ID)["subject"],
            "body_template": profile.get("custom_body") or get_template(DEFAULT_TEMPLATE_ID)["body"],
        }
    return {"writing_mode": "template", "drop_empty_lines": True, "subject_template": template["subject"], "body_template": template["body"]}


def featured_project(catalog: dict[str, str], profile: dict[str, Any]) -> tuple[str, str]:
    """Templates feature one fixed project for every recipient: the one chosen on the profile, else the first."""
    if not catalog:
        return "", ""
    name = profile.get("featured_project")
    if name in catalog:
        return name, catalog[name]
    return next(iter(catalog.items()))


def _sentence(text: str) -> str:
    text = (text or "").strip().rstrip(".")
    return f"{text}." if text else ""


def _clean_summary(summary: str) -> str:
    """Catalog entries read "summary Tech: x. Impact: y. Link: z"; keep only prose for the email."""
    summary = re.sub(r"\s*Link: \S+", "", summary or "")
    impact = re.search(r"Impact:\s*(.+?)\.?\s*$", summary)
    core = re.split(r"\s*(?:Tech|Impact):", summary)[0]
    return " ".join(filter(None, [_sentence(core), _sentence(impact.group(1)) if impact else ""]))


def profile_variables(profile: dict[str, Any], catalog: dict[str, str]) -> dict[str, str]:
    name = (profile.get("full_name") or "").strip()
    headline = (profile.get("headline") or "").strip()
    school = (profile.get("school") or "").strip()
    intro = ""
    if name:
        intro = f"I'm {name}"
        if headline:
            intro += f", {headline}"
        if school:
            intro += f" at {school}" if not headline else f" ({school})"
        intro += "."
    project_name, project_summary = featured_project(catalog, profile)
    project_summary = _clean_summary(project_summary)
    goal = (profile.get("goal") or "").strip()
    return {
        "my_name": name,
        "my_intro": intro,
        "my_headline": headline,
        "my_school": school,
        "my_skills": (profile.get("skills") or "").strip(),
        "goal": goal,
        "goal_short": "Internship" if "intern" in goal.lower() else ("Roles" if goal else ""),
        "project_name": project_name,
        "project_summary": project_summary,
        "project_line": f"Recently I built {project_name}: {project_summary}" if project_name else "",
        "resume_link": (profile.get("resume_url") or "").strip(),
        "portfolio_url": (profile.get("portfolio_url") or "").strip(),
        "signature": (profile.get("signature") or name).strip(),
    }
