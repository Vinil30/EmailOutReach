import re
from collections import Counter
from dataclasses import dataclass, field
from html import unescape
from typing import Any


PROMOTIONAL_PHRASES = (
    "100% free",
    "100% guaranteed",
    "act immediately",
    "act now",
    "apply now",
    "as seen on",
    "best price",
    "big savings",
    "buy now",
    "call now",
    "cash bonus",
    "claim your",
    "click below",
    "click here",
    "congratulations",
    "dear friend",
    "don't delete",
    "don't miss",
    "double your",
    "earn extra",
    "earn money",
    "extra income",
    "free gift",
    "free trial",
    "get paid",
    "guaranteed",
    "incredible deal",
    "last chance",
    "limited time",
    "lowest price",
    "make money",
    "miracle",
    "no catch",
    "no cost",
    "no obligation",
    "no strings attached",
    "once in a lifetime",
    "order now",
    "risk free",
    "risk-free",
    "satisfaction guaranteed",
    "special offer",
    "this is not spam",
    "this isn't spam",
    "urgent",
    "while supplies last",
    "winner",
    "work from home",
    "you have been selected",
    "you're a winner",
)

GENERIC_GREETINGS = re.compile(
    r"^\s*(?:dear\s+(?:sir|madam|sir\s*/\s*madam|sir\s+or\s+madam|friend|candidate|user|customer|valued\s+\w+)|"
    r"to\s+whom\s+it\s+may\s+concern|hello\s+(?:friend|dear)|greetings\s+of\s+the\s+day)\b",
    re.IGNORECASE,
)

SENSITIVE_REQUESTS = re.compile(
    r"\b(?:password|passcode|otp|one[- ]time\s+code|bank\s+(?:account|details)|account\s+number|credit\s+card|"
    r"card\s+number|cvv|social\s+security|wire\s+transfer|gift\s+cards?|verify\s+your\s+(?:account|identity)|"
    r"confirm\s+your\s+(?:account|identity|details)|login\s+details|send\s+(?:me\s+)?money)\b",
    re.IGNORECASE,
)

# Letter swaps and spaced-out letters spammers use to dodge keyword filters ("fr33", "F R E E").
OBFUSCATED_WORDS = re.compile(
    r"(?<![\w@$])(?=[a-z0-9@$]*[0-9@$])(?:fr[e3]{2}|[o0]ff[e3]r|m[o0]n[e3]y|c[a4@$]sh|w[i1]nn[e3]r|pr[i1]z[e3]|d[i1]sc[o0]unt|s[a4@$]v[e3])(?![\w@$])",
    re.IGNORECASE,
)
SPACED_LETTERS = re.compile(r"\b(?:[A-Z]\s){3,}[A-Z]\b")

HIDDEN_TEXT = re.compile(
    r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*[0-5](?:\.\d+)?px|font-size\s*:\s*0\b|opacity\s*:\s*0(?:\.0+)?\s*[;\"']|"
    r"color\s*:\s*(?:#fff\b|#ffffff\b|white\b|transparent\b)",
    re.IGNORECASE,
)

EMOJI = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]")

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
    "hidden or invisible text": "Remove hidden, tiny or white-on-white text; filters treat it as a trick.",
    "misleading link text": "Make each link's visible text match where it actually goes.",
    "generic greeting": "Greet the person by name instead of 'Dear Sir/Madam' or 'To whom it may concern'.",
    "requests for sensitive information": "Never ask for passwords, bank or card details by email; it reads as phishing.",
    "obfuscated words": "Spell words normally; tricks like 'fr33' or 'F R E E' are a classic spam signal.",
    "too many emojis": "Use emojis sparingly, if at all, in professional email.",
    "heavy formatting": "Keep formatting light: a little bold is fine, coloured text and many styles are not.",
    "image-heavy email": "Lead with real text; emails that are mostly images get filtered.",
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
        caps_ratio > 0.3 or len(all_caps_words) >= 4,
        2.0,
        f"{round(caps_ratio * 100)}% capitals, {len(all_caps_words)} all-caps words",
    )

    exclamation_count = text.count("!")
    question_count = text.count("?")
    repeated_marks = re.findall(r"[!?]{2,}", text)
    signals["exclamation_count"] = exclamation_count
    signals["question_count"] = question_count
    scorer.check(
        "excessive punctuation",
        "Punctuation",
        exclamation_count >= 3 or question_count >= 4 or bool(repeated_marks),
        1.5,
        f"{exclamation_count} '!' and {question_count} '?'" + (f", {len(repeated_marks)} repeated like '!!'" if repeated_marks else ""),
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
        min(3.0, 0.8 * len(phrase_hits)),
        ", ".join(phrase_hits) or "none found",
    )

    # "Feel free to" is ordinary politeness, not a pressure word.
    pressure_text = re.sub(r"\bfeel free\b", " ", lower_text)
    urgent_hits = re.findall(
        r"\b(?:urgent|urgently|immediately|asap|limited|exclusive|guaranteed|free|hurry|deadline|expires?|expiring|instant|instantly)\b"
        r"|\b(?:act|buy|call|order|reply|respond|join)\s+now\b|\btoday only\b",
        pressure_text,
    )
    signals["urgent_language_count"] = len(urgent_hits)
    scorer.check(
        "excessive promotional or urgent language",
        "Urgency words",
        len(urgent_hits) >= 2,
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

    html = email_body or ""
    # The compliance footer is ours and intentionally small and grey, so it's excluded from styling checks.
    styled_html = re.sub(r"<p[^>]*data-compliance-footer[^>]*>.*?</p>", "", html, flags=re.IGNORECASE | re.DOTALL)

    hidden = HIDDEN_TEXT.findall(styled_html)
    signals["hidden_text_rules"] = len(hidden)
    scorer.check(
        "hidden or invisible text",
        "Hidden text",
        bool(hidden),
        2.5,
        ", ".join(sorted(set(match.strip() for match in hidden))[:3]) or "none",
    )

    mismatched = _mismatched_links(html)
    signals["mismatched_links"] = mismatched[:3]
    scorer.check(
        "misleading link text",
        "Link text matches target",
        bool(mismatched),
        2.5,
        ", ".join(mismatched[:2]) or "every link goes where it says",
    )

    greeting_match = GENERIC_GREETINGS.search(body_text.strip())
    scorer.check(
        "generic greeting",
        "Personal greeting",
        bool(greeting_match),
        1.0,
        f'starts with "{greeting_match.group(0).strip()}"' if greeting_match else "addressed to a person",
    )

    sensitive = sorted({match.lower() for match in SENSITIVE_REQUESTS.findall(text)})
    signals["sensitive_requests"] = sensitive[:5]
    scorer.check(
        "requests for sensitive information",
        "No sensitive requests",
        bool(sensitive),
        3.0,
        ", ".join(sensitive[:3]) or "none",
    )

    combined = f"{subject}\n{body_text}"
    obfuscated = [match.strip() for match in OBFUSCATED_WORDS.findall(combined) + SPACED_LETTERS.findall(combined)]
    signals["obfuscated_words"] = obfuscated[:5]
    scorer.check("obfuscated words", "Spelling tricks", bool(obfuscated), 2.0, ", ".join(obfuscated[:3]) or "none")

    emoji_count = len(EMOJI.findall(f"{subject}{body_text}"))
    signals["emoji_count"] = emoji_count
    scorer.check("too many emojis", "Emojis", emoji_count >= 3, 1.0, f"{emoji_count} emojis")

    emphasis_tags = len(re.findall(r"<(?:b|strong|u|font|big|mark)\b", styled_html, re.IGNORECASE))
    color_styles = len(re.findall(r"(?:^|[;\"'\s])(?:color|background(?:-color)?)\s*:", styled_html, re.IGNORECASE))
    large_fonts = len(re.findall(r"font-size\s*:\s*(?:1[89]|[2-9]\d)px", styled_html, re.IGNORECASE))
    signals["formatting"] = {"emphasis_tags": emphasis_tags, "color_styles": color_styles, "large_fonts": large_fonts}
    scorer.check(
        "heavy formatting",
        "Formatting",
        emphasis_tags >= 5 or color_styles >= 2 or large_fonts >= 1,
        1.0,
        f"{emphasis_tags} bold/underline tags, {color_styles} colour styles",
    )

    images = len(re.findall(r"<img\b", html, re.IGNORECASE))
    signals["image_count"] = images
    scorer.check(
        "image-heavy email",
        "Text vs images",
        images >= 1 and word_count < 60 * images,
        1.5,
        f"{images} images, {word_count} words",
    )

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
    elif len(stripped) > 70:
        problems.append("subject is longer than 70 characters")
    if re.match(r"^(re|fwd?)\s*:", stripped, re.IGNORECASE):
        problems.append("fake reply/forward prefix")
    if "!" in stripped:
        problems.append("exclamation mark in subject")
    letters = re.findall(r"[A-Za-z]", stripped)
    if len(letters) >= 8 and sum(char.isupper() for char in letters) / len(letters) > 0.6:
        problems.append("subject is mostly capitals")
    if re.search(r"[$€£₹%]", stripped):
        problems.append("money or percent sign in subject")
    if re.search(r"\b(?:free|urgent|guaranteed|winner|offer|deal|discount)\b", stripped, re.IGNORECASE):
        problems.append("sales word in subject")
    return problems


def _domain(value: str) -> str:
    match = re.search(r"(?:https?://)?(?:www\.)?([a-z0-9-]+(?:\.[a-z0-9-]+)+)", value.strip().lower())
    return match.group(1) if match else ""


def _mismatched_links(html: str) -> list[str]:
    """Links whose visible text names one site while the href points to another, a phishing tell."""
    mismatches = []
    for href, label in re.findall(r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", html or "", re.IGNORECASE | re.DOTALL):
        visible = _strip_html(label).strip()
        shown, actual = _domain(visible), _domain(href)
        if shown and actual and "." in visible and not (actual.endswith(shown) or shown.endswith(actual)):
            mismatches.append(f"{visible} → {actual}")
    return mismatches
