import re
from collections import Counter
from dataclasses import dataclass, field
from html import unescape
from typing import Any


PROMOTIONAL_PHRASES = (
    "100% free",
    "act now",
    "apply now",
    "best price",
    "buy now",
    "cash bonus",
    "click here",
    "congratulations",
    "dear friend",
    "don't miss",
    "double your",
    "earn extra",
    "free trial",
    "guaranteed",
    "limited time",
    "lowest price",
    "make money",
    "no cost",
    "no obligation",
    "once in a lifetime",
    "order now",
    "risk free",
    "special offer",
    "urgent",
    "winner",
    "you have been selected",
)

CTA_PHRASES = (
    "book a call",
    "schedule a call",
    "let me know",
    "reply back",
    "click here",
    "apply now",
    "sign up",
    "get started",
    "contact me",
    "reach out",
)

SUSPICIOUS_URL_PATTERNS = (
    r"https?://\d{1,3}(?:\.\d{1,3}){3}",
    r"https?://[^\s<>\"]*(?:bit\.ly|tinyurl\.com|t\.co|goo\.gl|ow\.ly|is\.gd|buff\.ly)",
    r"https?://[^\s<>\"]*@",
    r"https?://[^\s<>\"]*(?:login|verify|secure|account)[^\s<>\"]*",
)

PLACEHOLDER_PATTERN = re.compile(
    r"\{\{[^}]*\}\}|\[(?:your |recipient |candidate |company |first |last )?(?:name|company|title|role|link|email)[^\]]*\]",
    re.IGNORECASE,
)

OPT_OUT_PATTERN = re.compile(r"unsubscribe|opt[\s-]?out|stop receiving|no longer wish", re.IGNORECASE)

# Plain-language fixes shown next to each failing check in the UI.
SUGGESTIONS = {
    "excessive capitalization": "Write in sentence case; avoid words in ALL CAPS.",
    "excessive punctuation": "Use at most one exclamation mark and keep questions focused.",
    "too many links": "Keep it to one or two links that the reader actually needs.",
    "suspicious URLs": "Use full, readable links on your own domain instead of shorteners or raw IPs.",
    "common spam or promotional phrases": "Replace sales clichés with a specific, factual reason for writing.",
    "excessive promotional or urgent language": "Drop pressure words like 'urgent', 'free' or 'now'.",
    "unusually short email": "Add a sentence of context: who you are and why this person specifically.",
    "unusually long email": "Trim to the essentials; aim for roughly 80-200 words.",
    "repeated phrases": "Vary your wording; repeated phrases look templated.",
    "too many calls to action": "Ask for one clear next step instead of several.",
    "subject line issues": "Keep the subject short, specific and honest (no fake RE:/FWD:).",
    "unfilled placeholders": "Replace every [placeholder] or {{merge_field}} before sending.",
    "missing opt-out line": "Bulk campaigns should tell recipients how to unsubscribe.",
    "heavy money language": "Mention pricing once, plainly, if at all.",
}


@dataclass
class SpamRisk:
    score: float
    level: str
    action: str
    decision: str
    reasons: list[str] = field(default_factory=list)
    signals: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)
    checks: list[dict[str, Any]] = field(default_factory=list)

    @property
    def suggestions(self) -> list[str]:
        return [SUGGESTIONS[reason] for reason in self.reasons if reason in SUGGESTIONS]

    def model_dump(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "level": self.level,
            "action": self.action,
            "decision": self.decision,
            "reasons": self.reasons,
            "suggestions": self.suggestions,
            "checks": self.checks,
            "signals": self.signals,
            "raw": self.raw,
        }


class _Scorer:
    def __init__(self):
        self.score = 0.0
        self.reasons: list[str] = []
        self.checks: list[dict[str, Any]] = []

    def check(self, key: str, label: str, failed: bool, weight: float, detail: str = "") -> None:
        if failed:
            self.score += weight
            self.reasons.append(key)
        self.checks.append(
            {
                "key": key,
                "label": label,
                "passed": not failed,
                "weight": round(weight, 2) if failed else 0,
                "detail": detail,
            }
        )


def analyze_email_risk(
    email_subject: str,
    email_body: str,
    email_from: str = "",
    recipient_email: str = "",
    campaign_type: str = "outreach",
) -> SpamRisk:
    """Score an email for spam/deliverability risk before it is sent.

    campaign_type is "outreach" for one-to-one student emails and "campaign" for
    bulk marketing sends, which are additionally expected to carry an opt-out line.
    """
    subject = email_subject or ""
    body_text = _strip_html(email_body)
    text = _normalize_text(f"{subject}\n{body_text}")
    signals: dict[str, Any] = {}
    scorer = _Scorer()

    words = re.findall(r"[A-Za-z][A-Za-z']+", text)
    alpha_chars = re.findall(r"[A-Za-z]", text)
    upper_chars = re.findall(r"[A-Z]", text)
    caps_ratio = len(upper_chars) / max(1, len(alpha_chars))
    all_caps_words = [word for word in words if len(word) >= 4 and word.isupper()]
    signals["caps_ratio"] = round(caps_ratio, 3)
    signals["all_caps_words"] = len(all_caps_words)
    scorer.check(
        "excessive capitalization",
        "Capitalization",
        caps_ratio > 0.35 or len(all_caps_words) >= 4,
        2.0,
        f"{round(caps_ratio * 100)}% capitals, {len(all_caps_words)} all-caps words",
    )

    exclamation_count = text.count("!")
    question_count = text.count("?")
    signals["exclamation_count"] = exclamation_count
    signals["question_count"] = question_count
    scorer.check(
        "excessive punctuation",
        "Punctuation",
        exclamation_count >= 4 or question_count >= 4 or exclamation_count + question_count >= 6,
        1.5,
        f"{exclamation_count} '!' and {question_count} '?'",
    )

    urls = re.findall(r"https?://[^\s<>\"]+", email_body or "")
    suspicious_urls = [url for url in urls if _is_suspicious_url(url)]
    signals["link_count"] = len(urls)
    signals["suspicious_url_count"] = len(suspicious_urls)
    scorer.check("too many links", "Link count", len(urls) > 2, 1.5, f"{len(urls)} links")
    scorer.check(
        "suspicious URLs",
        "Link safety",
        bool(suspicious_urls),
        2.5,
        ", ".join(suspicious_urls[:3]) or "no shorteners, raw IPs or login-style links",
    )

    lower_text = text.lower()
    phrase_hits = sorted({phrase for phrase in PROMOTIONAL_PHRASES if phrase in lower_text})
    signals["promotional_phrase_hits"] = phrase_hits
    scorer.check(
        "common spam or promotional phrases",
        "Spam phrases",
        bool(phrase_hits),
        min(2.5, 0.7 * len(phrase_hits)),
        ", ".join(phrase_hits) or "none found",
    )

    urgent_hits = re.findall(r"\b(?:urgent|immediately|asap|limited|exclusive|guaranteed|free|now)\b", lower_text)
    signals["urgent_language_count"] = len(urgent_hits)
    scorer.check(
        "excessive promotional or urgent language",
        "Urgency words",
        len(urgent_hits) >= 3,
        1.5,
        f"{len(urgent_hits)} pressure words",
    )

    word_count = len(words)
    signals["word_count"] = word_count
    scorer.check("unusually short email", "Minimum length", word_count < 45, 1.0, f"{word_count} words")
    scorer.check("unusually long email", "Maximum length", word_count > 260, 1.0, f"{word_count} words")

    repeated = _repeated_phrases(lower_text)
    signals["repeated_phrases"] = repeated[:5]
    scorer.check("repeated phrases", "Repetition", bool(repeated), 1.5, ", ".join(repeated[:3]) or "none")

    cta_hits = [phrase for phrase in CTA_PHRASES if phrase in lower_text]
    signals["cta_count"] = len(cta_hits)
    scorer.check("too many calls to action", "Calls to action", len(cta_hits) > 2, 1.5, f"{len(cta_hits)} asks")

    subject_problems = _subject_problems(subject)
    signals["subject_length"] = len(subject.strip())
    scorer.check(
        "subject line issues",
        "Subject line",
        bool(subject_problems),
        1.0,
        "; ".join(subject_problems) or f"{len(subject.strip())} characters",
    )

    placeholders = sorted(set(PLACEHOLDER_PATTERN.findall(f"{subject}\n{body_text}")))
    signals["placeholders"] = placeholders[:5]
    scorer.check(
        "unfilled placeholders",
        "Placeholders",
        bool(placeholders),
        2.0,
        ", ".join(placeholders[:3]) or "all merge fields filled",
    )

    money_hits = re.findall(r"[$€£₹]\s?\d|\b\d+\s?%\s?off\b|\$\$+", text, re.IGNORECASE)
    signals["money_mentions"] = len(money_hits)
    scorer.check("heavy money language", "Money talk", len(money_hits) >= 3, 1.0, f"{len(money_hits)} mentions")

    if campaign_type == "campaign":
        has_opt_out = bool(OPT_OUT_PATTERN.search(body_text))
        signals["has_opt_out"] = has_opt_out
        scorer.check(
            "missing opt-out line",
            "Unsubscribe line",
            not has_opt_out,
            1.0,
            "present" if has_opt_out else "no unsubscribe instructions found",
        )

    score = round(min(scorer.score, 10.0), 2)
    if score >= 7:
        level, action, decision = "HIGH", "REGENERATE", "REGENERATE"
    elif score >= 4:
        level, action, decision = "MEDIUM", "REGENERATE", "REGENERATE"
    else:
        level, action, decision = "LOW", "SEND", "PASS"

    return SpamRisk(
        score=score,
        level=level,
        action=action,
        decision=decision,
        reasons=scorer.reasons,
        signals=signals,
        checks=scorer.checks,
        raw={
            "guard": "local_spam_guard",
            "campaign_type": campaign_type,
            "email_from": email_from,
            "recipient_email": recipient_email,
        },
    )


def _strip_html(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value or "")
    return unescape(without_tags)


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _is_suspicious_url(url: str) -> bool:
    return any(re.search(pattern, url, re.IGNORECASE) for pattern in SUSPICIOUS_URL_PATTERNS)


def _repeated_phrases(text: str) -> list[str]:
    tokens = re.findall(r"[a-z][a-z']+", text)
    phrases = [" ".join(tokens[index : index + 3]) for index in range(max(0, len(tokens) - 2))]
    return [phrase for phrase, count in Counter(phrases).items() if count >= 3]


def _subject_problems(subject: str) -> list[str]:
    stripped = subject.strip()
    problems = []
    if not stripped:
        problems.append("subject is empty")
    elif len(stripped) > 78:
        problems.append("subject is longer than 78 characters")
    if re.match(r"^(re|fwd?)\s*:", stripped, re.IGNORECASE):
        problems.append("fake reply/forward prefix")
    return problems
